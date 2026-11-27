"""Checks a PSAK 118 statement of profit or loss must pass before it is sent for review.

Each issue names what is wrong and what to open to fix it. Blocking issues stop a statement from
being sent for review: accounts with a balance but no report line (BR-02), a difference to
ERPNext's Profit and Loss (BR-07) and, in the first PSAK 118 year, a restated comparative that
does not equal the PSAK 201 profit or loss (BR-19), and conditional mappings of the same priority
that put an account's balance on different lines, since which of them wins is arbitrary. Warnings
need a decision but do not block: Other Items lines above the company's threshold must be
explained in a note (BR-06), and conflicting mappings whose entries net to nothing in the period
should still get distinct priorities.

The statement of financial position adds blocking checks: every balance sheet account with a
balance on the reporting date has a mapping in force then (BR-30), and the statement balances and
equals ERPNext's Balance Sheet (BR-31).

The statement of cash flows is checked for the period it is presented in: from the start of the
fiscal year in a quarterly or yearly package, which it is part of (BR-42), otherwise the period
itself. Balance sheet accounts with a balance or movements, and income or expense accounts with an
amount outside operating profit, need a cash flow line, and closing cash must equal the ledger's
cash and cash equivalents (BR-36). Both block a quarterly or yearly package and are warnings
otherwise. Non-cash transactions are listed for information (BR-35).
"""

import frappe
from frappe.utils import add_years, flt, getdate

from frappe_psak_id.psak_id.cash_flow import CASH_LINE, NO_CASH_FLOW_LINE, compute_cash_flows
from frappe_psak_id.psak_id.financial_position import (
	BALANCE_SHEET_ROOT_TYPES,
	compute_financial_position,
	fiscal_year_start,
	get_account_balances,
	mapped_accounts,
	prior_year_end,
)
from frappe_psak_id.psak_id.statement import DISABLED_LINE, compute_periods, get_mappings

BLOCKING = "Blocking"
WARNING = "Warning"
INFORMATION = "Information"

CONFLICTING_MAPPINGS = "Conflicting Mappings"
OTHER_ITEMS = "Other Items Above Threshold"
ERPNEXT_DIFFERENCE = "Difference to ERPNext"
RESTATEMENT_DIFFERENCE = "Restatement Difference"
UNMAPPED_BALANCE = "Unmapped Balance Sheet Account"
BALANCE_SHEET_DIFFERENCE = "Difference to ERPNext Balance Sheet"
CASH_DIFFERENCE = "Cash Difference"
NON_CASH_TRANSACTION = "Non-cash Transaction"

MONTHLY = "Monthly"
# The packages with a statement of cash flows (BR-42)
CASH_FLOW_PERIODICITIES = ("Quarterly", "Yearly")

CURRENT = "Current"
RESTATED = "Restated"

# Revenue the Other Items threshold percentage applies to
REVENUE_LINE = "PL-OP-REV"


def run_checks(company: str, from_date, to_date, finance_book: str | None = None) -> frappe._dict:
	"""Return the issues of the statement for the period, with the statements they come from.

	In the first PSAK 118 year the prior year is checked too, classified with this period's
	mappings as its restated comparative will be.
	"""
	from_date, to_date = getdate(from_date), getdate(to_date)
	transition = is_transition_period(company, from_date, to_date)
	periods = [(from_date, to_date)]
	if transition:
		periods.insert(0, (getdate(add_years(from_date, -1)), getdate(add_years(to_date, -1))))
	statements = compute_periods(company, periods, finance_book=finance_book, mapping_date=to_date)
	current = statements[-1]
	restated = statements[0] if transition else None

	issues = []
	for statement, period in ((current, CURRENT), (restated, RESTATED)):
		if statement:
			issues += _mapping_issues(statement, period)
	issues += _other_items_issues(company, current)
	if current.ledger_difference:
		issues.append(
			_issue(ERPNEXT_DIFFERENCE, BLOCKING, current, CURRENT, amount=current.ledger_difference)
		)
	if restated and restated.ledger_difference:
		issues.append(
			_issue(RESTATEMENT_DIFFERENCE, BLOCKING, restated, RESTATED, amount=restated.ledger_difference)
		)
	return frappe._dict(issues=issues, current=current, restated=restated)


def balance_sheet_issues(company: str, to_date, finance_book: str | None = None) -> list:
	"""Balance sheet accounts with a balance on ``to_date`` but no mapping in force then (BR-30).

	The amount is the balance as presented: debit balances of assets, credit balances of
	liabilities and equity are positive.
	"""
	to_date = getdate(to_date)
	mapped = mapped_accounts(company, to_date)
	statement = frappe._dict(from_date=to_date, to_date=to_date)
	return [
		_issue(
			UNMAPPED_BALANCE,
			BLOCKING,
			statement,
			CURRENT,
			account=row.account,
			amount=flt(row.balance if row.root_type == "Asset" else -row.balance, 2),
		)
		for row in sorted(get_account_balances(company, to_date, finance_book), key=lambda row: row.account)
		if row.account not in mapped
	]


def balance_sheet_difference_issues(
	company: str, to_date, finance_book: str | None = None, restated: bool = False
) -> list:
	"""The difference of the statement of financial position to ERPNext's Balance Sheet on
	``to_date`` and, with ``restated``, on the prior fiscal year end classified with the mappings in
	force on ``to_date``, as the restated comparative of the statement is (BR-31, FR-31)."""
	positions = [(compute_financial_position(company, to_date, finance_book), CURRENT)]
	if restated:
		prior = compute_financial_position(
			company, prior_year_end(company, to_date), finance_book, mapping_date=to_date
		)
		positions.append((prior, RESTATED))
	return [
		_issue(BALANCE_SHEET_DIFFERENCE, BLOCKING, position, period, amount=position.ledger_difference)
		for position, period in positions
		if position.ledger_difference
	]


def financial_position_issues(position, period=CURRENT) -> list:
	"""Unmapped accounts, conflicting mappings and the difference to ERPNext's Balance Sheet of a
	computed statement of financial position (BR-30, BR-31).

	Stricter than ``balance_sheet_issues``: an account whose mappings exist but none applies, or
	whose line is disabled, is not on the statement either.
	"""
	issues = _mapping_issues(position, period)
	if position.ledger_difference:
		issues.append(
			_issue(BALANCE_SHEET_DIFFERENCE, BLOCKING, position, period, amount=position.ledger_difference)
		)
	return issues


def cash_flow_period(company: str, from_date, to_date, periodicity: str = MONTHLY) -> tuple:
	"""The period a package of ``periodicity`` presents cash flows for: from the start of the fiscal
	year in a quarterly or yearly package (BR-42)."""
	if periodicity in CASH_FLOW_PERIODICITIES:
		return fiscal_year_start(company, to_date), getdate(to_date)
	return getdate(from_date), getdate(to_date)


def cash_flow_issues(
	company: str, from_date, to_date, finance_book: str | None = None, periodicity: str = MONTHLY
) -> list:
	"""Missing cash flow lines, the difference of closing cash to the ledger (BR-36) and the
	non-cash transactions (BR-35) of the statement of cash flows of a package of ``periodicity``."""
	from_date, to_date = cash_flow_period(company, from_date, to_date, periodicity)
	statement = compute_cash_flows(company, from_date, to_date, finance_book)
	return cash_flow_statement_issues(statement, periodicity)


def cash_flow_statement_issues(statement, periodicity: str = MONTHLY) -> list:
	"""The checks of :func:`cash_flow_issues` for a statement of cash flows already computed."""
	severity = BLOCKING if periodicity in CASH_FLOW_PERIODICITIES else WARNING

	issues = [
		_issue(
			row.reason,
			severity,
			statement,
			CURRENT,
			account=row.account,
			report_line=row.report_line,
			amount=row.amount,
		)
		for row in statement.unmapped
		# Missing or disabled profit or loss and financial position lines are checked with their
		# statements; a disabled cash flow line is named
		if row.reason == NO_CASH_FLOW_LINE or (row.reason == DISABLED_LINE and row.report_line)
	]
	listed = {issue.account for issue in issues}
	issues += [
		_issue(
			NO_CASH_FLOW_LINE,
			severity,
			statement,
			CURRENT,
			account=row.account,
			amount=flt(row.balance if row.root_type == "Asset" else -row.balance, 2),
			balance_only=True,
		)
		for row in _balances_without_cash_flow_line(
			statement.company, statement.to_date, statement.finance_book
		)
		if row.account not in listed
	]
	if statement.cash_difference:
		issues.append(_issue(CASH_DIFFERENCE, severity, statement, CURRENT, amount=statement.cash_difference))
	return issues + _non_cash_issues(statement)


def is_transition_period(company: str, from_date, to_date) -> bool:
	"""Whether the period lies in the first year PSAK 118 is applied (BR-11)."""
	adoption_date = frappe.db.get_value("PSAK ID Company Policy", company, "adoption_date")
	if not adoption_date:
		return False
	adoption_date = getdate(adoption_date)
	return adoption_date <= getdate(from_date) and getdate(to_date) < getdate(add_years(adoption_date, 1))


def other_items_threshold(company: str, revenue: float) -> float | None:
	"""The smaller of the policy's percentage of revenue and amount; None when neither is set."""
	percent, amount = frappe.db.get_value(
		"PSAK ID Company Policy",
		company,
		["other_items_threshold_percent", "other_items_threshold_amount"],
	)
	limits = []
	if flt(percent):
		limits.append(abs(flt(revenue)) * flt(percent) / 100)
	if flt(amount):
		limits.append(flt(amount))
	return min(limits) if limits else None


def _mapping_issues(statement, period) -> list:
	issues = [
		_issue(
			row.reason,
			BLOCKING,
			statement,
			period,
			account=row.account,
			report_line=row.report_line,
			amount=row.amount,
		)
		for row in statement.unmapped
	]
	issues += [
		_issue(
			CONFLICTING_MAPPINGS,
			BLOCKING if flt(row.amount, 2) else WARNING,
			statement,
			period,
			account=row.account,
			mappings=row.mappings,
			priority=row.priority,
			amount=row.amount,
		)
		for row in statement.conflicts
	]
	return issues


def _balances_without_cash_flow_line(company: str, to_date, finance_book: str | None) -> list:
	"""Balance sheet accounts with a balance on ``to_date`` and a mapping in force then without a
	cash flow line: their next movements would be left out of the cash flows."""
	mappings = get_mappings(company, to_date, BALANCE_SHEET_ROOT_TYPES)
	missing = {
		account
		for account, candidates in mappings.items()
		if any(mapping.report_line != CASH_LINE and not mapping.cash_flow_line for mapping in candidates)
	}
	return sorted(
		(row for row in get_account_balances(company, to_date, finance_book) if row.account in missing),
		key=lambda row: row.account,
	)


def _non_cash_issues(statement) -> list:
	"""One issue per non-cash voucher, for the amount of its debits."""
	debits = {}
	for row in statement.non_cash:
		key = (row.voucher_type, row.voucher_no)
		debits[key] = flt(debits.get(key)) + max(flt(row.amount), 0)
	return [
		_issue(
			NON_CASH_TRANSACTION,
			INFORMATION,
			statement,
			CURRENT,
			voucher_type=voucher_type,
			voucher_no=voucher_no,
			amount=flt(amount, 2),
		)
		for (voucher_type, voucher_no), amount in debits.items()
	]


def _other_items_issues(company: str, statement) -> list:
	lines = {line.line_code: line for line in statement.lines}
	revenue = lines[REVENUE_LINE].amount if REVENUE_LINE in lines else 0
	threshold = other_items_threshold(company, revenue)
	if threshold is None:
		return []
	return [
		_issue(
			OTHER_ITEMS,
			WARNING,
			statement,
			CURRENT,
			report_line=line.line_code,
			amount=line.amount,
			threshold=flt(threshold, 2),
		)
		for line in statement.lines
		if line.is_other_items and line.line_type == "Line" and abs(flt(line.amount, 2)) > flt(threshold, 2)
	]


def _issue(check, severity, statement, period, **values) -> frappe._dict:
	return frappe._dict(
		check=check,
		severity=severity,
		period=period,
		from_date=statement.from_date,
		to_date=statement.to_date,
		**values,
	)
