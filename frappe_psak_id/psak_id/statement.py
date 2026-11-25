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
from frappe.query_builder import Case, Criterion
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate
from pypika.terms import ExistsCriterion

from frappe_psak_id.psak_id.report_lines import (
	OTHER_COMPREHENSIVE_INCOME,
	PROFIT_OR_LOSS,
	parse_subtotal_formula,
)

PROFIT_OR_LOSS_LINE = "PL-SUB-PL"
BEFORE_FINANCING_LINE = "PL-SUB-PBFT"
CONTINUING_OPERATIONS_LINE = "PL-SUB-CONT"
DISCONTINUED = "Discontinued Operations"
PROFIT_OR_LOSS_ROOT_TYPES = ("Income", "Expense")
OTHER_COMPREHENSIVE_INCOME_LINE = "OCI-SUB-OCI"
TOTAL_COMPREHENSIVE_INCOME_LINE = "OCI-SUB-TCI"
PERIOD_CLOSING_VOUCHER = "Period Closing Voucher"

# Why a GL group has no report line; the Mapping Control report explains each one
NOT_MAPPED = "Not Mapped"
NO_MATCHING_CONDITION = "No Matching Condition"
DISABLED_LINE = "Disabled Line"
# Mapping condition columns that ERPNext's General Ledger report can filter on
LEDGER_FILTER_COLUMNS = ("cost_center", "project")


class Condition(NamedTuple):
	column: str  # GL Entry column the condition reads, or "party" for party type + party
	values: frozenset  # accepted values; for a party, (party_type, party) pairs


class Mapping(NamedTuple):
	name: str
	report_line: str
	priority: int
	condition: Condition | None
	expense_nature: str | None = None


class StatementError(frappe.ValidationError):
	pass


def compute(
	company: str,
	from_date,
	to_date,
	cost_center: str | None = None,
	finance_book: str | None = None,
	mapping_date=None,
):
	"""Return the statement lines, unmapped accounts, conflicting mappings and the reconciliation to the ledger."""
	return compute_periods(company, [(from_date, to_date)], cost_center, finance_book, mapping_date)[0]


def compute_periods(
	company: str,
	periods: list,
	cost_center: str | None = None,
	finance_book: str | None = None,
	mapping_date=None,
) -> list:
	"""Return one statement per period, from a single pass over the General Ledger.

	Every period is classified with the mappings in force on ``mapping_date`` (default: the end of
	the last period), so the columns of one report never mix two classifications. Restated
	comparatives pass the reporting period's end here.
	"""
	periods = [(getdate(start), getdate(end)) for start, end in periods]
	for index, (start, end) in enumerate(periods):
		if start > end:
			frappe.throw(_("The period starts after it ends."), StatementError)
		if index and start <= periods[index - 1][1]:
			frappe.throw(_("The periods of a statement must not overlap."), StatementError)
	mapping_date = getdate(mapping_date) if mapping_date else periods[-1][1]

	policy = get_policy(company)
	lines = get_lines(PROFIT_OR_LOSS)
	mappings = get_mappings(company, mapping_date, PROFIT_OR_LOSS_ROOT_TYPES)
	categories = {
		line.name: effective_category(line, policy) for line in lines.values() if line.line_type == "Line"
	}
	ordered_lines = presentation_order(
		[line for line in sorted(lines.values(), key=lambda line: line.sequence) if not line.disabled],
		categories,
	)
	with_default_book = include_default_book(company, finance_book)
	groups = _get_gl_groups(
		company,
		periods,
		cost_center,
		finance_book,
		with_default_book,
		columns=sorted({m.condition.column for ms in mappings.values() for m in ms if m.condition}),
	)
	groups_by_period = {}
	for group in groups:
		groups_by_period.setdefault(group.period, []).append(group)

	# Other comprehensive income belongs to the entity as a whole, so a statement of one cost
	# center has none
	oci_accounts = {} if cost_center else get_oci_accounts(company, mapping_date)
	oci_lines = get_lines(OTHER_COMPREHENSIVE_INCOME)
	oci_groups_by_period = {}
	if oci_accounts:
		for group in _get_oci_groups(company, periods, finance_book, with_default_book, list(oci_accounts)):
			oci_groups_by_period.setdefault(group.period, []).append(group)

	currency = frappe.get_cached_value("Company", company, "default_currency")
	statements = [
		_statement(
			frappe._dict(
				company=company,
				from_date=start,
				to_date=end,
				cost_center=cost_center,
				finance_book=finance_book,
				currency=currency,
			),
			groups_by_period.get(index, []),
			lines,
			ordered_lines,
			mappings,
			categories,
			policy,
		)
		for index, (start, end) in enumerate(periods)
	]
	for index, statement in enumerate(statements):
		_add_other_comprehensive_income(
			statement, oci_groups_by_period.get(index, []), oci_lines, oci_accounts
		)
	return statements


def _statement(result, groups, lines, ordered_lines, mappings, categories, policy):
	line_amounts, line_groups, unmapped, conflicts, natures = {}, {}, {}, {}, {}
	ledger_profit_or_loss = 0.0
	for group in groups:
		ledger_profit_or_loss += flt(group.amount)
		candidates = mappings.get(group.account, [])
		mapping = resolve_mapping(group, candidates)
		line = lines.get(mapping.report_line) if mapping else None
		if not line or line.disabled:
			if mapping:
				key = (group.account, DISABLED_LINE, mapping.report_line)
			else:
				key = (group.account, NO_MATCHING_CONDITION if candidates else NOT_MAPPED, None)
			unmapped[key] = flt(unmapped.get(key)) + flt(group.amount)
			continue
		group.line = line.name
		line_amounts[line.name] = flt(line_amounts.get(line.name)) + flt(group.amount)
		line_groups.setdefault(line.name, []).append(group)
		if mapping.expense_nature:
			key = (line.name, mapping.expense_nature)
			natures[key] = flt(natures.get(key)) + flt(group.amount)
		tied = tied_mappings(group, candidates, mapping)
		if tied:
			key = (group.account, mapping.priority, tuple(sorted(m.name for m in (mapping, *tied))))
			conflicts[key] = flt(conflicts.get(key)) + flt(group.amount)

	amounts = evaluate_lines(lines.values(), line_amounts, categories)
	hidden = _hidden_lines(lines.values(), amounts, categories, policy)

	profit_or_loss = flt(amounts.get(PROFIT_OR_LOSS_LINE))
	ledger_profit_or_loss = flt(ledger_profit_or_loss, 2)
	result.update(
		lines=[
			frappe._dict(
				line_code=line.name,
				label_id=line.label_id,
				label_en=line.label_en,
				line_type=line.line_type,
				category=categories.get(line.name),
				is_other_items=line.is_other_items,
				amount=flt(amounts.get(line.name)),
				**ledger_filters(line.name, line_groups.get(line.name, []), groups),
				hidden=line.name in hidden,
			)
			for line in ordered_lines
		],
		unmapped=[
			frappe._dict(account=account, reason=reason, report_line=report_line, amount=amount)
			for (account, reason, report_line), amount in sorted(unmapped.items(), key=lambda i: i[0][:2])
			if flt(amount)
		],
		# Expenses by nature per line, for the by-nature note of a statement presented by function
		natures=[
			frappe._dict(report_line=line, expense_nature=nature, amount=amount)
			for (line, nature), amount in natures.items()
			if flt(amount, 2)
		],
		conflicts=[
			frappe._dict(account=account, priority=priority, mappings=list(names), amount=amount)
			for (account, priority, names), amount in sorted(conflicts.items())
		],
		profit_or_loss=profit_or_loss,
		ledger_profit_or_loss=ledger_profit_or_loss,
		ledger_difference=flt(profit_or_loss - ledger_profit_or_loss, 2),
	)
	return result


def _add_other_comprehensive_income(statement, groups, lines, oci_accounts):
	"""Other comprehensive income of the period and total comprehensive income (BR-38).

	Movements of equity accounts with an OCI line are presented on that line, income positive.
	A line that is disabled after its accounts were mapped leaves them unmapped, like a profit or
	loss line.
	"""
	line_amounts, line_groups = {}, {}
	for group in groups:
		line = lines.get(oci_accounts[group.account])
		if not line or line.disabled:
			statement.unmapped.append(
				frappe._dict(
					account=group.account,
					reason=DISABLED_LINE,
					report_line=oci_accounts[group.account],
					amount=flt(group.amount),
				)
			)
			continue
		group.line = line.name
		line_amounts[line.name] = flt(line_amounts.get(line.name)) + flt(group.amount)
		line_groups.setdefault(line.name, []).append(group)

	amounts = evaluate_lines(
		lines.values(), line_amounts, {}, known={PROFIT_OR_LOSS_LINE: statement.profit_or_loss}
	)
	statement.update(
		has_other_comprehensive_income=bool(oci_accounts),
		oci_lines=[
			frappe._dict(
				line_code=line.name,
				label_id=line.label_id,
				label_en=line.label_en,
				line_type=line.line_type,
				category=None,
				is_other_items=line.is_other_items,
				amount=flt(amounts.get(line.name)),
				**ledger_filters(line.name, line_groups.get(line.name, []), groups),
				hidden=False,
			)
			for line in sorted(lines.values(), key=lambda line: line.sequence)
			if not line.disabled
		],
		other_comprehensive_income=flt(amounts.get(OTHER_COMPREHENSIVE_INCOME_LINE)),
		total_comprehensive_income=flt(amounts.get(TOTAL_COMPREHENSIVE_INCOME_LINE)),
	)


def ledger_filters(line_code: str, own: list, groups: list) -> dict:
	"""The General Ledger filters for the entries behind one line (its drill-down).

	``accounts`` are the line's accounts. When a conditional mapping splits one of them between
	lines, ``ledger_filters`` adds the cost centers or projects this line takes. One set of
	filters applies to every account, so ``ledger_exact`` is false when the ledger would still
	show entries that are on another line. ``ledger_accounts`` then gives the filters and amount
	per account, which are exact unless the split is by party or another accounting dimension
	(the General Ledger cannot filter on those).
	"""
	accounts = sorted({group.account for group in own})
	filters, exact = _ledger_filters(line_code, own, groups)
	by_account = []
	if not exact and len(accounts) > 1:
		for account in accounts:
			own_groups = [group for group in own if group.account == account]
			account_filters, account_exact = _ledger_filters(line_code, own_groups, groups)
			by_account.append(
				{
					"account": account,
					"amount": flt(sum(flt(group.amount) for group in own_groups), 2),
					"filters": account_filters,
					"exact": account_exact,
				}
			)
	return {
		"accounts": accounts,
		"ledger_filters": filters,
		"ledger_exact": exact,
		"ledger_accounts": by_account,
	}


def _ledger_filters(line_code: str, own: list, groups: list) -> tuple[dict, bool]:
	accounts = {group.account for group in own}
	others = [group for group in groups if group.account in accounts and group.get("line") != line_code]
	filters = {}
	for column in LEDGER_FILTER_COLUMNS:
		values = {group.get(column) for group in own}
		# The General Ledger cannot select entries without a value
		if None in values or "" in values:
			continue
		if any(group.get(column) not in values for group in others):
			filters[column] = sorted(values)
	exact = not any(
		all(group.get(column) in values for column, values in filters.items()) for group in others
	)
	return filters, exact


def presentation_order(lines: list, categories: dict) -> list:
	"""Lines in the order they are presented.

	A line presented in another category than its own (an entity whose main business is investing
	or financing, BR-04 / BR-20) moves just above the first subtotal that closes that category, so
	it is read with the lines it is added to.
	"""
	moved = {
		line.name: categories[line.name]
		for line in lines
		if line.line_type == "Line" and categories.get(line.name) != line.category
	}
	if not moved:
		return list(lines)

	by_code = {line.name: line for line in lines}
	waiting = dict(moved)
	ordered = []
	for line in lines:
		if line.name in moved:
			continue
		if line.line_type == "Subtotal":
			closes = {
				term.ref for term in parse_subtotal_formula(line.subtotal_formula) if term.kind == "category"
			}
			for code in [code for code, category in waiting.items() if category in closes]:
				ordered.append(by_code[code])
				del waiting[code]
		ordered.append(line)
	# A category no subtotal closes keeps its lines at the end rather than dropping them
	ordered.extend(by_code[code] for code in waiting)
	return ordered


def resolve_mapping(group, candidates: list[Mapping]) -> Mapping | None:
	"""Pick the mapping for one GL group: the matching conditional mapping with the lowest
	priority number, else the unconditional mapping with the lowest priority number."""
	ordered = sorted(candidates, key=lambda m: (m.condition is None, m.priority))
	for mapping in ordered:
		if mapping.condition is None or _matches(group, mapping.condition):
			return mapping
	return None


def tied_mappings(group, candidates: list[Mapping], chosen: Mapping) -> list[Mapping]:
	"""Other conditional mappings that match the group at the chosen priority but name another
	line. Which of them wins then depends on the order rows come from the database."""
	if chosen.condition is None:
		return []
	return [
		mapping
		for mapping in candidates
		if mapping is not chosen
		and mapping.condition is not None
		and mapping.priority == chosen.priority
		and mapping.report_line != chosen.report_line
		and _matches(group, mapping.condition)
	]


def effective_category(line, policy) -> str:
	"""The category a line is presented in, after the main business activity choices."""
	if line.category == "Investing" and line.follows_operating and policy.main_business_investing:
		return "Operating"
	if line.category == "Financing" and policy.main_business_financing:
		if policy.financing_all_operating or line.follows_operating:
			return "Operating"
	return line.category


def evaluate_lines(lines, line_amounts: dict, categories: dict, known: dict | None = None) -> dict:
	"""Amounts of every line: mapped amounts for lines, formulas for subtotals.

	A category term adds the lines presented in that category, or with a classification
	(``CAT:Asset/Current``) only the lines of that classification. ``known`` gives the amounts of
	lines of another statement that a formula refers to.
	"""
	by_code = {line.name: line for line in lines}
	category_totals = {}
	for code, category in categories.items():
		classification = by_code[code].get("classification") if code in by_code else None
		for key in (category, (category, classification)):
			category_totals[key] = flt(category_totals.get(key)) + flt(line_amounts.get(code))

	amounts = dict(known or {})

	def amount_of(code):
		if code in amounts:
			return amounts[code]
		line = by_code.get(code)
		if not line or line.disabled:
			value = 0.0
		elif line.line_type == "Subtotal":
			value = 0.0
			for term in parse_subtotal_formula(line.subtotal_formula):
				if term.kind == "line":
					part = amount_of(term.ref)
				elif term.classification:
					part = category_totals.get((term.ref, term.classification), 0.0)
				else:
					part = category_totals.get(term.ref, 0.0)
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


def check_read_access(company: str):
	"""Refuse users who may not see the company's PSAK ID data (User Permission on Company)."""
	if frappe.db.exists("PSAK ID Company Policy", company) and not frappe.has_permission(
		"PSAK ID Company Policy", "read", doc=company
	):
		frappe.throw(
			_("You are not allowed to see the statements of {0}.").format(company),
			frappe.PermissionError,
		)


def get_policy(company):
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


def get_lines(statement: str) -> dict:
	rows = frappe.get_all(
		"PSAK ID Report Line",
		filters={"statement": statement},
		fields=[
			"name",
			"label_id",
			"label_en",
			"line_type",
			"category",
			"classification",
			"sequence",
			"subtotal_formula",
			"follows_operating",
			"is_other_items",
			"disabled",
		],
	)
	return {row.name: row for row in rows}


def get_mappings(company: str, to_date, root_types: tuple) -> dict[str, list[Mapping]]:
	"""Mappings in force at the end of the period of accounts of ``root_types``, grouped by account.

	For each account and condition only the latest start date counts, so a reclassification from a
	later date replaces the earlier rule instead of competing with it.
	"""
	rows = frappe.get_all(
		"PSAK ID Account Mapping",
		filters={
			"company": company,
			"valid_from": ("<=", to_date),
			"root_type": ("in", root_types),
		},
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
			"expense_nature",
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
			Mapping(
				row.name,
				row.report_line,
				row.priority,
				_condition(row, dimension_columns),
				row.expense_nature or None,
			)
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


def include_default_book(company: str, finance_book: str | None) -> bool:
	# Same choice as ERPNext's report default: the company's default book is included unless
	# another book is asked for (ERPNext refuses to combine two different books)
	default_book = frappe.get_cached_value("Company", company, "default_finance_book")
	return not (finance_book and default_book and finance_book != default_book)


def gl_group_columns(gle, columns) -> list:
	"""GL Entry columns to group by: the account and the dimensions mapping conditions read."""
	group_columns = [gle.account]
	for column in columns:
		if column == "party":
			group_columns += [gle.party_type, gle.party]
		else:
			group_columns.append(gle[column])
	return group_columns


def _get_gl_groups(company, periods, cost_center, finance_book, with_default_book, columns):
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	group_columns = gl_group_columns(gle, columns)

	period = Case()
	for index, (start, end) in enumerate(periods):
		period = period.when(gle.posting_date[start:end], index)
	period = period.as_("period")

	books = [finance_book or ""]
	if with_default_book:
		books.append(frappe.get_cached_value("Company", company, "default_finance_book") or "")

	query = (
		frappe.qb.from_(gle)
		.join(account)
		.on(account.name == gle.account)
		.select(*group_columns, period, (Sum(gle.credit) - Sum(gle.debit)).as_("amount"))
		.where(gle.company == company)
		.where(account.root_type.isin(PROFIT_OR_LOSS_ROOT_TYPES))
		.where(Criterion.any([gle.posting_date[start:end] for start, end in periods]))
		.where(gle.is_cancelled == 0)
		.where(gle.voucher_type != PERIOD_CLOSING_VOUCHER)
		.where(gle.finance_book.isin(books) | gle.finance_book.isnull())
		.groupby(*group_columns, period)
	)
	if cost_center:
		query = query.where(gle.cost_center.isin(_with_descendants("Cost Center", cost_center)))
	return query.run(as_dict=True)


def get_oci_accounts(company: str, to_date) -> dict:
	"""Equity accounts whose latest mapping in force on ``to_date`` names an OCI line, with that line."""
	rows = frappe.get_all(
		"PSAK ID Account Mapping",
		filters={"company": company, "valid_from": ("<=", to_date), "root_type": "Equity"},
		fields=["account", "oci_line"],
		order_by="valid_from desc, priority asc",
	)
	latest = {}
	for row in rows:
		latest.setdefault(row.account, row.oci_line)
	return {account: line for account, line in latest.items() if line}


def _get_oci_groups(company, periods, finance_book, with_default_book, accounts):
	"""Credit minus debit of OCI accounts per period, without Period Closing Vouchers and without
	vouchers that only move amounts between equity accounts (a transfer between components)."""
	gle = frappe.qb.DocType("GL Entry")
	other = frappe.qb.DocType("GL Entry").as_("other")
	other_account = frappe.qb.DocType("Account").as_("other_account")
	outside_equity = ExistsCriterion(
		frappe.qb.from_(other)
		.join(other_account)
		.on(other_account.name == other.account)
		.select(other.name)
		.where(other.voucher_type == gle.voucher_type)
		.where(other.voucher_no == gle.voucher_no)
		.where(other.is_cancelled == 0)
		.where(other_account.root_type != "Equity")
	)

	period = Case()
	for index, (start, end) in enumerate(periods):
		period = period.when(gle.posting_date[start:end], index)
	period = period.as_("period")

	books = [finance_book or ""]
	if with_default_book:
		books.append(frappe.get_cached_value("Company", company, "default_finance_book") or "")

	return (
		frappe.qb.from_(gle)
		.select(gle.account, period, (Sum(gle.credit) - Sum(gle.debit)).as_("amount"))
		.where(gle.company == company)
		.where(gle.account.isin(accounts))
		.where(Criterion.any([gle.posting_date[start:end] for start, end in periods]))
		.where(gle.is_cancelled == 0)
		.where(gle.voucher_type != PERIOD_CLOSING_VOUCHER)
		.where(gle.finance_book.isin(books) | gle.finance_book.isnull())
		.where(outside_equity)
		.groupby(gle.account, period)
		.run(as_dict=True)
	)


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
