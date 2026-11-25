"""PSAK 118 statement of financial position computed from ERPNext's General Ledger.

The ledger is only read: GL Entries are summed per account up to the reporting date in SQL, with
the same finance book choice as the statement of profit or loss, and each account's balance is
resolved to one report line with the balance sheet mappings.

Retained earnings include the profit or loss of the fiscal year so far whether or not a Period
Closing Voucher has been made (BR-32): Period Closing Vouchers of the current fiscal year are left
out and the year's ``PL-SUB-PL`` is added instead, so a closed year is never counted twice.

ERPNext's Balance Sheet totals every Asset account, and presents liabilities, equity and the
provisional profit or loss so that they add up to the same amount. Its total assets are therefore
the ledger's total assets computed here; the tests compare them with ERPNext's report on v15 and
v16 (BR-31).
"""

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe.query_builder.functions import Sum
from frappe.utils import add_days, flt, getdate

from frappe_psak_id.psak_id.report_lines import FINANCIAL_POSITION
from frappe_psak_id.psak_id.statement import (
	DISABLED_LINE,
	NO_MATCHING_CONDITION,
	NOT_MAPPED,
	PROFIT_OR_LOSS_ROOT_TYPES,
	compute,
	evaluate_lines,
	get_lines,
	get_mappings,
	get_policy,
	gl_group_columns,
	include_default_book,
	ledger_filters,
	resolve_mapping,
	tied_mappings,
)

BALANCE_SHEET_ROOT_TYPES = ("Asset", "Liability", "Equity")
PERIOD_CLOSING_VOUCHER = "Period Closing Voucher"

RETAINED_EARNINGS_LINE = "FP-EQ-RE"
TOTAL_ASSETS_LINE = "FP-SUB-TA"
TOTAL_LIABILITIES_AND_EQUITY_LINE = "FP-SUB-TLE"


def compute_financial_position(
	company: str, to_date, finance_book: str | None = None, mapping_date=None
) -> frappe._dict:
	"""Return the statement lines on ``to_date``, unmapped accounts, conflicting mappings and the
	check against ERPNext's Balance Sheet."""
	return compute_positions(company, [to_date], finance_book, mapping_date)[0]


def compute_positions(company: str, dates: list, finance_book: str | None = None, mapping_date=None) -> list:
	"""Return one statement of financial position per date.

	Every date is classified with the mappings in force on ``mapping_date`` (default: the latest
	date), so a comparative column is presented like the current one.
	"""
	dates = [getdate(date) for date in dates]
	mapping_date = getdate(mapping_date) if mapping_date else max(dates)

	get_policy(company)
	lines = get_lines(FINANCIAL_POSITION)
	mappings = get_mappings(company, mapping_date, BALANCE_SHEET_ROOT_TYPES)
	context = frappe._dict(
		company=company,
		finance_book=finance_book,
		mapping_date=mapping_date,
		lines=lines,
		ordered_lines=[
			line for line in sorted(lines.values(), key=lambda line: line.sequence) if not line.disabled
		],
		categories={code: line.category for code, line in lines.items() if line.line_type == "Line"},
		mappings=mappings,
		columns=sorted({m.condition.column for ms in mappings.values() for m in ms if m.condition}),
		currency=frappe.get_cached_value("Company", company, "default_currency"),
	)
	return [_position(context, date) for date in dates]


def _position(context, to_date) -> frappe._dict:
	company, finance_book = context.company, context.finance_book
	year_start = fiscal_year_start(company, to_date)
	groups = get_account_balances(
		company, to_date, finance_book, columns=context.columns, closing_from=year_start
	)
	profit = compute(
		company, year_start, to_date, finance_book=finance_book, mapping_date=context.mapping_date
	)
	# Profit or loss of earlier years that no Period Closing Voucher has moved to equity yet
	unclosed = profit_or_loss_before(company, year_start, finance_book)

	line_amounts, line_groups, unmapped, conflicts = {}, {}, {}, {}
	ledger_total_assets = 0.0
	for group in groups:
		# Assets are presented with their debit balance, liabilities and equity with their credit
		amount = flt(group.balance) if group.root_type == "Asset" else -flt(group.balance)
		if group.root_type == "Asset":
			ledger_total_assets += amount
		candidates = context.mappings.get(group.account, [])
		mapping = resolve_mapping(group, candidates)
		line = context.lines.get(mapping.report_line) if mapping else None
		if not line or line.disabled:
			if mapping:
				key = (group.account, DISABLED_LINE, mapping.report_line)
			else:
				key = (group.account, NO_MATCHING_CONDITION if candidates else NOT_MAPPED, None)
			unmapped[key] = flt(unmapped.get(key)) + amount
			continue
		group.line = line.name
		line_amounts[line.name] = flt(line_amounts.get(line.name)) + amount
		line_groups.setdefault(line.name, []).append(group)
		tied = tied_mappings(group, candidates, mapping)
		if tied:
			key = (group.account, mapping.priority, tuple(sorted(m.name for m in (mapping, *tied))))
			conflicts[key] = flt(conflicts.get(key)) + amount

	profit_or_loss = flt(profit.profit_or_loss + unclosed, 2)
	line_amounts[RETAINED_EARNINGS_LINE] = flt(line_amounts.get(RETAINED_EARNINGS_LINE)) + profit_or_loss
	amounts = evaluate_lines(context.lines.values(), line_amounts, context.categories)

	total_assets = flt(amounts.get(TOTAL_ASSETS_LINE), 2)
	total_liabilities_and_equity = flt(amounts.get(TOTAL_LIABILITIES_AND_EQUITY_LINE), 2)
	ledger_total_assets = flt(ledger_total_assets, 2)
	return frappe._dict(
		company=company,
		from_date=year_start,
		to_date=getdate(to_date),
		finance_book=finance_book,
		currency=context.currency,
		lines=[
			frappe._dict(
				line_code=line.name,
				label_id=line.label_id,
				label_en=line.label_en,
				line_type=line.line_type,
				category=line.category,
				classification=line.classification,
				is_other_items=line.is_other_items,
				amount=flt(amounts.get(line.name)),
				**ledger_filters(line.name, line_groups.get(line.name, []), groups),
			)
			for line in context.ordered_lines
		],
		unmapped=[
			frappe._dict(account=account, reason=reason, report_line=report_line, amount=amount)
			for (account, reason, report_line), amount in sorted(unmapped.items(), key=lambda i: i[0][:2])
			if flt(amount, 2)
		],
		conflicts=[
			frappe._dict(account=account, priority=priority, mappings=list(names), amount=amount)
			for (account, priority, names), amount in sorted(conflicts.items())
		],
		profit_or_loss=profit_or_loss,
		# Accounts of the year's profit or loss without a line make retained earnings incomplete
		profit_or_loss_difference=profit.ledger_difference,
		total_assets=total_assets,
		total_liabilities_and_equity=total_liabilities_and_equity,
		balance_difference=flt(total_assets - total_liabilities_and_equity, 2),
		ledger_total_assets=ledger_total_assets,
		# Both totals must equal ERPNext's total assets; report the side that does not
		ledger_difference=flt(total_assets - ledger_total_assets, 2)
		or flt(total_liabilities_and_equity - ledger_total_assets, 2),
	)


def fiscal_year_start(company: str, date):
	"""First day of the company's fiscal year that contains ``date``."""
	return getdate(get_fiscal_year(date, company=company, as_dict=True).year_start_date)


def prior_year_end(company: str, date):
	"""Last day of the fiscal year before the one that contains ``date``: the comparative date."""
	return getdate(add_days(fiscal_year_start(company, date), -1))


def get_account_balances(
	company: str, to_date, finance_book: str | None = None, columns=(), closing_from=None
) -> list:
	"""Debit minus credit of every balance sheet account with a balance on ``to_date``, per value
	of ``columns`` (the dimensions that mapping conditions read).

	Period Closing Vouchers are included, since they move a year's profit or loss into an equity
	account, except those posted on or after ``closing_from``.
	"""
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	group_columns = gl_group_columns(gle, columns)
	query = (
		frappe.qb.from_(gle)
		.join(account)
		.on(account.name == gle.account)
		.select(*group_columns, account.root_type, (Sum(gle.debit) - Sum(gle.credit)).as_("balance"))
		.where(gle.company == company)
		.where(account.root_type.isin(BALANCE_SHEET_ROOT_TYPES))
		.where(gle.posting_date <= getdate(to_date))
		.where(gle.is_cancelled == 0)
		.where(gle.finance_book.isin(_books(company, finance_book)) | gle.finance_book.isnull())
		.groupby(*group_columns, account.root_type)
	)
	if closing_from:
		query = query.where(
			(gle.voucher_type != PERIOD_CLOSING_VOUCHER) | (gle.posting_date < getdate(closing_from))
		)
	return [row for row in query.run(as_dict=True) if flt(row.balance, 2)]


def profit_or_loss_before(company: str, date, finance_book: str | None = None) -> float:
	"""Credit minus debit of the income and expense accounts before ``date``, Period Closing
	Vouchers included: what earlier years left out of equity."""
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	result = (
		frappe.qb.from_(gle)
		.join(account)
		.on(account.name == gle.account)
		.select(Sum(gle.credit) - Sum(gle.debit))
		.where(gle.company == company)
		.where(account.root_type.isin(PROFIT_OR_LOSS_ROOT_TYPES))
		.where(gle.posting_date < getdate(date))
		.where(gle.is_cancelled == 0)
		.where(gle.finance_book.isin(_books(company, finance_book)) | gle.finance_book.isnull())
		.run()
	)
	return flt(result[0][0], 2) if result else 0.0


def mapped_accounts(company: str, to_date) -> set:
	"""Balance sheet accounts with a mapping in force on ``to_date``."""
	return set(
		frappe.get_all(
			"PSAK ID Account Mapping",
			filters={
				"company": company,
				"valid_from": ("<=", getdate(to_date)),
				"root_type": ("in", BALANCE_SHEET_ROOT_TYPES),
			},
			pluck="account",
			distinct=True,
		)
	)


def _books(company: str, finance_book: str | None) -> list:
	books = [finance_book or ""]
	if include_default_book(company, finance_book):
		books.append(frappe.get_cached_value("Company", company, "default_finance_book") or "")
	return books
