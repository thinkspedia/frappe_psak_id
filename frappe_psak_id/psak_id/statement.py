"""PSAK 118 statement of profit or loss computed from ERPNext's General Ledger.

The ledger is only read. GL Entries are summed per account and per value of the dimensions that
mapping conditions use, each group is resolved to one report line, and subtotals are evaluated
from the report lines' formulas.

The GL query applies the same conditions as ERPNext's Profit and Loss Statement (company, period,
cost center with its children, finance book, no Period Closing Vouchers, no cancelled entries),
so the ledger total it returns is ERPNext's net profit or loss; the tests compare it with
ERPNext's report on v15 and v16. Calling that report at run time is not an option: it loads
every GL Entry into Python and takes minutes on a year of a busy company.
"""

from typing import NamedTuple

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate

from frappe_psak_id.psak_id.report_lines import parse_subtotal_formula

PROFIT_OR_LOSS_LINE = "PL-SUB-PL"
BEFORE_FINANCING_LINE = "PL-SUB-PBFT"
CONTINUING_OPERATIONS_LINE = "PL-SUB-CONT"
DISCONTINUED = "Discontinued Operations"


class Condition(NamedTuple):
	column: str  # GL Entry column the condition reads, or "party" for party type + party
	values: frozenset  # accepted values; for a party, (party_type, party) pairs


class Mapping(NamedTuple):
	name: str
	report_line: str
	priority: int
	condition: Condition | None


class StatementError(frappe.ValidationError):
	pass


def compute(
	company: str, from_date, to_date, cost_center: str | None = None, finance_book: str | None = None
):
	"""Return the statement lines, unmapped accounts and the reconciliation to the ledger."""
	from_date, to_date = getdate(from_date), getdate(to_date)
	if from_date > to_date:
		frappe.throw(_("The period starts after it ends."), StatementError)

	policy = _get_policy(company)
	lines = _get_lines()
	mappings = _get_mappings(company, to_date)
	include_default_book = _include_default_book(company, finance_book)
	groups = _get_gl_groups(
		company,
		from_date,
		to_date,
		cost_center,
		finance_book,
		include_default_book,
		columns=sorted({m.condition.column for ms in mappings.values() for m in ms if m.condition}),
	)

	line_amounts, line_accounts, unmapped = {}, {}, {}
	ledger_profit_or_loss = 0.0
	for group in groups:
		ledger_profit_or_loss += flt(group.amount)
		mapping = resolve_mapping(group, mappings.get(group.account, []))
		line = lines.get(mapping.report_line) if mapping else None
		if not line or line.disabled:
			unmapped[group.account] = flt(unmapped.get(group.account)) + flt(group.amount)
			continue
		line_amounts[line.name] = flt(line_amounts.get(line.name)) + flt(group.amount)
		line_accounts.setdefault(line.name, set()).add(group.account)

	categories = {
		line.name: effective_category(line, policy) for line in lines.values() if line.line_type == "Line"
	}
	amounts = evaluate_lines(lines.values(), line_amounts, categories)
	hidden = _hidden_lines(lines.values(), amounts, categories, policy)

	profit_or_loss = flt(amounts.get(PROFIT_OR_LOSS_LINE))
	ledger_profit_or_loss = flt(ledger_profit_or_loss, 2)
	return frappe._dict(
		company=company,
		from_date=from_date,
		to_date=to_date,
		cost_center=cost_center,
		finance_book=finance_book,
		currency=frappe.get_cached_value("Company", company, "default_currency"),
		lines=[
			frappe._dict(
				line_code=line.name,
				label_id=line.label_id,
				label_en=line.label_en,
				line_type=line.line_type,
				category=categories.get(line.name),
				is_other_items=line.is_other_items,
				amount=flt(amounts.get(line.name)),
				accounts=sorted(line_accounts.get(line.name, ())),
				hidden=line.name in hidden,
			)
			for line in sorted(lines.values(), key=lambda line: line.sequence)
			if not line.disabled
		],
		unmapped=[
			frappe._dict(account=account, amount=amount)
			for account, amount in sorted(unmapped.items())
			if flt(amount)
		],
		profit_or_loss=profit_or_loss,
		ledger_profit_or_loss=ledger_profit_or_loss,
		ledger_difference=flt(profit_or_loss - ledger_profit_or_loss, 2),
	)


def resolve_mapping(group, candidates: list[Mapping]) -> Mapping | None:
	"""Pick the mapping for one GL group: the matching conditional mapping with the lowest
	priority number, else the unconditional mapping with the lowest priority number."""
	ordered = sorted(candidates, key=lambda m: (m.condition is None, m.priority))
	for mapping in ordered:
		if mapping.condition is None or _matches(group, mapping.condition):
			return mapping
	return None


def effective_category(line, policy) -> str:
	"""The category a line is presented in, after the main business activity choices."""
	if line.category == "Investing" and line.follows_operating and policy.main_business_investing:
		return "Operating"
	if line.category == "Financing" and policy.main_business_financing:
		if policy.financing_all_operating or line.follows_operating:
			return "Operating"
	return line.category


def evaluate_lines(lines, line_amounts: dict, categories: dict) -> dict:
	"""Amounts of every line: mapped amounts for lines, formulas for subtotals."""
	by_code = {line.name: line for line in lines}
	category_totals = {}
	for code, category in categories.items():
		category_totals[category] = flt(category_totals.get(category)) + flt(line_amounts.get(code))

	amounts = {}

	def amount_of(code):
		if code in amounts:
			return amounts[code]
		line = by_code.get(code)
		if not line or line.disabled:
			value = 0.0
		elif line.line_type == "Subtotal":
			value = 0.0
			for term in parse_subtotal_formula(line.subtotal_formula):
				part = category_totals.get(term.ref, 0.0) if term.kind == "category" else amount_of(term.ref)
				value += term.sign * flt(part)
		else:
			value = flt(line_amounts.get(code))
		amounts[code] = value
		return value

	for code in by_code:
		amount_of(code)
	return amounts


def _matches(group, condition: Condition) -> bool:
	if condition.column == "party":
		return (group.party_type, group.party) in condition.values
	return group.get(condition.column) in condition.values


def _get_policy(company):
	policy = frappe.db.get_value(
		"PSAK ID Company Policy",
		company,
		[
			"reporting_framework",
			"main_business_investing",
			"main_business_financing",
			"financing_all_operating",
		],
		as_dict=True,
	)
	if not policy:
		frappe.throw(
			_(
				"{0} has no PSAK ID Company Policy yet. Create one before preparing PSAK 118 statements."
			).format(company),
			StatementError,
		)
	if policy.reporting_framework != "SAK Indonesia":
		frappe.throw(
			_(
				"PSAK 118 statements are only prepared for companies reporting under SAK Indonesia; {0} uses {1}."
			).format(company, policy.reporting_framework),
			StatementError,
		)
	return policy


def _get_lines() -> dict:
	rows = frappe.get_all(
		"PSAK ID Report Line",
		filters={"statement": "Profit or Loss"},
		fields=[
			"name",
			"label_id",
			"label_en",
			"line_type",
			"category",
			"sequence",
			"subtotal_formula",
			"follows_operating",
			"is_other_items",
			"disabled",
		],
	)
	return {row.name: row for row in rows}


def _get_mappings(company: str, to_date) -> dict[str, list[Mapping]]:
	"""Mappings in force at the end of the period, grouped by account.

	For each account and condition only the latest start date counts, so a reclassification from a
	later date replaces the earlier rule instead of competing with it.
	"""
	rows = frappe.get_all(
		"PSAK ID Account Mapping",
		filters={"company": company, "valid_from": ("<=", to_date)},
		fields=[
			"name",
			"account",
			"report_line",
			"priority",
			"valid_from",
			"condition_type",
			"condition_doctype",
			"condition_value",
			"party_type",
			"accounting_dimension",
		],
		order_by="valid_from desc, priority asc",
	)
	latest = {}
	for row in rows:
		key = (row.account, row.condition_type, row.condition_doctype, row.condition_value, row.priority)
		latest.setdefault(key, row)

	dimension_columns = _dimension_columns()
	mappings = {}
	for row in latest.values():
		mappings.setdefault(row.account, []).append(
			Mapping(row.name, row.report_line, row.priority, _condition(row, dimension_columns))
		)
	return mappings


def _condition(row, dimension_columns: dict) -> Condition | None:
	if not row.condition_type:
		return None
	if row.condition_type == "Party":
		return Condition("party", frozenset({(row.party_type, row.condition_value)}))
	if row.condition_type == "Cost Center":
		column = "cost_center"
	elif row.condition_type == "Project":
		column = "project"
	else:
		column = dimension_columns[row.accounting_dimension]
	return Condition(column, frozenset(_with_descendants(row.condition_doctype, row.condition_value)))


def _with_descendants(doctype: str, name: str) -> list[str]:
	# A condition on a group (a parent cost center, a dimension group) covers everything below it
	if not frappe.get_cached_value("DocType", doctype, "is_tree"):
		return [name]
	lft, rgt = frappe.db.get_value(doctype, name, ["lft", "rgt"])
	return frappe.get_all(doctype, filters={"lft": (">=", lft), "rgt": ("<=", rgt)}, pluck="name")


def _dimension_columns() -> dict:
	return {
		row.name: row.fieldname
		for row in frappe.get_all("Accounting Dimension", fields=["name", "fieldname"])
	}


def _include_default_book(company: str, finance_book: str | None) -> bool:
	# Same choice as ERPNext's report default: the company's default book is included unless
	# another book is asked for (ERPNext refuses to combine two different books)
	default_book = frappe.get_cached_value("Company", company, "default_finance_book")
	return not (finance_book and default_book and finance_book != default_book)


def _get_gl_groups(company, from_date, to_date, cost_center, finance_book, include_default_book, columns):
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	group_columns = [gle.account]
	for column in columns:
		if column == "party":
			group_columns += [gle.party_type, gle.party]
		else:
			group_columns.append(gle[column])

	books = [finance_book or ""]
	if include_default_book:
		books.append(frappe.get_cached_value("Company", company, "default_finance_book") or "")

	query = (
		frappe.qb.from_(gle)
		.join(account)
		.on(account.name == gle.account)
		.select(*group_columns, (Sum(gle.credit) - Sum(gle.debit)).as_("amount"))
		.where(gle.company == company)
		.where(account.root_type.isin(["Income", "Expense"]))
		.where(gle.posting_date[from_date:to_date])
		.where(gle.is_cancelled == 0)
		.where(gle.voucher_type != "Period Closing Voucher")
		.where(gle.finance_book.isin(books) | gle.finance_book.isnull())
		.groupby(*group_columns)
	)
	if cost_center:
		query = query.where(gle.cost_center.isin(_with_descendants("Cost Center", cost_center)))
	return query.run(as_dict=True)


def _hidden_lines(lines, amounts: dict, categories: dict, policy) -> set:
	hidden = set()
	# PSAK 118 does not present this subtotal when all financing expenses are shown in Operating
	if policy.main_business_financing and policy.financing_all_operating:
		hidden.add(BEFORE_FINANCING_LINE)
	# Without discontinued operations, profit from continuing operations equals profit or loss
	has_discontinued = any(
		flt(amounts.get(code)) for code, category in categories.items() if category == DISCONTINUED
	)
	if not has_discontinued:
		hidden.add(CONTINUING_OPERATIONS_LINE)
		hidden.update(code for code, category in categories.items() if category == DISCONTINUED)
	return hidden
