"""PSAK 118 statement of cash flows, indirect method, computed from ERPNext's General Ledger.

The statement starts from operating profit or loss (BR-33): a line with a ``source_line`` takes
that profit or loss line's amount. Every other amount is the cash effect, credit minus debit, of
an account that is not cash:

* An income or expense account whose mapping names a cash flow line presents its profit or loss
  on that line. When the account is part of operating profit, the same amount is taken out of
  operating activities on the non-cash adjustments line, so a gain on a disposal ends up in the
  proceeds of the disposal.
* A balance sheet account presents its movements of the period on its cash flow line, or, when
  its mapping also names a line for decreases, its increases on the first and its decreases on
  the second (gross, per direction: an asset increases with debits, a liability or equity
  account with credits).

Period Closing Vouchers are left out: they only move profit or loss into equity. Since every
voucher balances, the movements of the accounts that are not cash add up to the change in cash,
so the closing balance of the statement must equal the ledger's balance of the accounts mapped to
cash and cash equivalents (BR-36). An account without a line breaks that check and is listed.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import add_days, flt, getdate

from frappe_psak_id.psak_id.financial_position import (
	BALANCE_SHEET_ROOT_TYPES,
	finance_books,
	get_account_balances,
)
from frappe_psak_id.psak_id.report_lines import CASH_FLOW, PROFIT_OR_LOSS, parse_subtotal_formula
from frappe_psak_id.psak_id.statement import (
	DISABLED_LINE,
	NO_MATCHING_CONDITION,
	NOT_MAPPED,
	PERIOD_CLOSING_VOUCHER,
	PROFIT_OR_LOSS_ROOT_TYPES,
	StatementError,
	compute,
	effective_category,
	evaluate_lines,
	get_gl_groups,
	get_lines,
	get_mappings,
	get_policy,
	gl_group_columns,
	include_default_book,
	ledger_filters,
	resolve_mapping,
)

CASH_LINE = "FP-CA-CASH"
OPENING_LINE = "CF-OPEN"
CLOSING_LINE = "CF-SUB-CLOSE"
# Operating profit items whose cash flow is presented on another line are taken out here
NON_CASH_ADJUSTMENTS_LINE = "CF-OP-ADJ"
# Why an account's cash effect is not on the statement, besides the reasons of the other statements
NO_CASH_FLOW_LINE = "No Cash Flow Line"


def compute_cash_flows(
	company: str, from_date, to_date, finance_book: str | None = None, mapping_date=None
) -> frappe._dict:
	"""Return the statement lines from ``from_date`` to ``to_date``, the accounts left out and the
	check of the closing balance against the ledger's cash and cash equivalents.

	Accounts are classified with the mappings in force on ``mapping_date`` (default: ``to_date``),
	so a comparative period can be presented like the current one.
	"""
	from_date, to_date = getdate(from_date), getdate(to_date)
	if from_date > to_date:
		frappe.throw(_("The period starts after it ends."), StatementError)
	mapping_date = getdate(mapping_date) if mapping_date else to_date

	profit = compute(company, from_date, to_date, finance_book=finance_book, mapping_date=mapping_date)
	lines = get_lines(CASH_FLOW)
	flows = _Flows(lines)
	context = frappe._dict(
		company=company,
		from_date=from_date,
		to_date=to_date,
		finance_book=finance_book,
		mapping_date=mapping_date,
		balance_sheet_mappings=get_mappings(company, mapping_date, BALANCE_SHEET_ROOT_TYPES),
	)

	profit_amounts = {line.line_code: line.amount for line in profit.lines}
	for line in lines.values():
		if line.source_line:
			flows.add_amount(line.name, profit_amounts.get(line.source_line))
	profit_or_loss_lines = get_lines(PROFIT_OR_LOSS)
	operating_profit_lines = _operating_profit_lines(company, lines, profit_or_loss_lines)
	_add_profit_or_loss(context, flows, profit_or_loss_lines, operating_profit_lines)
	_add_balance_sheet_movements(context, flows)

	opening_cash = _cash_balance(context, add_days(from_date, -1))
	ledger_closing_cash = _cash_balance(context, to_date)
	flows.add_amount(OPENING_LINE, opening_cash)

	amounts = evaluate_lines(lines.values(), flows.line_amounts, flows.categories)
	closing_cash = flt(amounts.get(CLOSING_LINE), 2)
	return frappe._dict(
		company=company,
		from_date=from_date,
		to_date=to_date,
		finance_book=finance_book,
		currency=profit.currency,
		lines=[
			frappe._dict(
				line_code=line.name,
				label_id=line.label_id,
				label_en=line.label_en,
				line_type=line.line_type,
				category=line.category,
				is_other_items=line.is_other_items,
				amount=flt(amounts.get(line.name)),
				**ledger_filters(line.name, flows.line_groups.get(line.name, []), flows.groups),
			)
			for line in sorted(lines.values(), key=lambda line: line.sequence)
			if not line.disabled
		],
		unmapped=flows.unmapped_rows(),
		opening_cash=opening_cash,
		closing_cash=closing_cash,
		ledger_closing_cash=ledger_closing_cash,
		cash_difference=flt(closing_cash - ledger_closing_cash, 2),
		# Income or expense accounts without a profit or loss line leave operating profit incomplete
		profit_or_loss_difference=profit.ledger_difference,
	)


class _Flows:
	"""Amounts per cash flow line, the GL groups behind them and the accounts left out."""

	def __init__(self, lines: dict):
		self.lines = lines
		self.categories = {
			code: line.category for code, line in lines.items() if line.line_type == "Line" and line.category
		}
		self.line_amounts, self.line_groups, self.unmapped = {}, {}, {}
		self.groups = []

	def add_amount(self, line_code: str, amount):
		self.line_amounts[line_code] = flt(self.line_amounts.get(line_code)) + flt(amount)

	def add_group(self, group, line_code: str, amount):
		"""Present ``amount`` of one GL group on a line; a disabled or missing line leaves it out."""
		line = self.lines.get(line_code)
		if not line or line.disabled or line.line_type != "Line":
			self.leave_out(group.account, DISABLED_LINE, line_code, amount)
			return
		part = frappe._dict(group, line=line_code, amount=flt(amount))
		self.groups.append(part)
		self.line_groups.setdefault(line_code, []).append(part)
		self.add_amount(line_code, amount)

	def leave_out(self, account: str, reason: str, line_code: str | None, amount):
		key = (account, reason, line_code)
		self.unmapped[key] = flt(self.unmapped.get(key)) + flt(amount)

	def unmapped_rows(self) -> list:
		return [
			frappe._dict(account=account, reason=reason, report_line=line_code, amount=amount)
			for (account, reason, line_code), amount in sorted(self.unmapped.items(), key=lambda i: i[0][:2])
			if flt(amount, 2)
		]


def _operating_profit_lines(company: str, cash_flow_lines: dict, lines: dict) -> set:
	"""Profit or loss lines added into the lines that cash flow lines start from."""
	policy = get_policy(company)
	categories = {
		code: effective_category(line, policy) for code, line in lines.items() if line.line_type == "Line"
	}

	def expand(code: str) -> set:
		line = lines.get(code)
		if not line or line.disabled:
			return set()
		if line.line_type != "Subtotal":
			return {code}
		included = set()
		for term in parse_subtotal_formula(line.subtotal_formula):
			if term.kind == "line":
				included |= expand(term.ref)
			else:
				included |= {line_code for line_code, category in categories.items() if category == term.ref}
		return included

	return set().union(*(expand(line.source_line) for line in cash_flow_lines.values() if line.source_line))


def _add_profit_or_loss(context, flows: _Flows, lines: dict, operating_profit_lines: set):
	"""Income and expenses outside operating profit, and operating profit items with a line of
	their own, on their cash flow lines."""
	mappings = get_mappings(context.company, context.mapping_date, PROFIT_OR_LOSS_ROOT_TYPES)
	groups = get_gl_groups(
		context.company,
		[(context.from_date, context.to_date)],
		None,
		context.finance_book,
		include_default_book(context.company, context.finance_book),
		columns=_condition_columns(mappings),
	)
	for group in groups:
		candidates = mappings.get(group.account, [])
		mapping = resolve_mapping(group, candidates)
		line = lines.get(mapping.report_line) if mapping else None
		in_operating_profit = bool(line and not line.disabled and line.name in operating_profit_lines)
		if mapping and mapping.cash_flow_line:
			flows.add_group(group, mapping.cash_flow_line, group.amount)
			if in_operating_profit:
				flows.add_group(group, NON_CASH_ADJUSTMENTS_LINE, -flt(group.amount))
		elif not in_operating_profit:
			flows.leave_out(group.account, _reason(mapping, line, candidates), None, group.amount)


def _add_balance_sheet_movements(context, flows: _Flows):
	for group in _get_movements(context):
		candidates = context.balance_sheet_mappings.get(group.account, [])
		mapping = resolve_mapping(group, candidates)
		if mapping and mapping.report_line == CASH_LINE:
			continue
		cash_effect = flt(group.credit) - flt(group.debit)
		if not mapping or not mapping.cash_flow_line:
			reason = NO_CASH_FLOW_LINE if mapping else (NO_MATCHING_CONDITION if candidates else NOT_MAPPED)
			flows.leave_out(group.account, reason, None, cash_effect)
			continue
		if not mapping.cash_flow_line_decrease:
			flows.add_group(group, mapping.cash_flow_line, cash_effect)
			continue
		# An asset increases with debits, a liability or equity account with credits
		increase, decrease = (
			(-flt(group.debit), flt(group.credit))
			if group.root_type == "Asset"
			else (flt(group.credit), -flt(group.debit))
		)
		if increase:
			flows.add_group(group, mapping.cash_flow_line, increase)
		if decrease:
			flows.add_group(group, mapping.cash_flow_line_decrease, decrease)


def _reason(mapping, line, candidates) -> str:
	if mapping:
		return DISABLED_LINE if not line or line.disabled else NO_CASH_FLOW_LINE
	return NO_MATCHING_CONDITION if candidates else NOT_MAPPED


def _get_movements(context) -> list:
	"""Debits and credits of the period per balance sheet account and condition dimension values,
	without Period Closing Vouchers."""
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	group_columns = gl_group_columns(gle, _condition_columns(context.balance_sheet_mappings))
	return (
		frappe.qb.from_(gle)
		.join(account)
		.on(account.name == gle.account)
		.select(
			*group_columns,
			account.root_type,
			Sum(gle.debit).as_("debit"),
			Sum(gle.credit).as_("credit"),
		)
		.where(gle.company == context.company)
		.where(account.root_type.isin(BALANCE_SHEET_ROOT_TYPES))
		.where(gle.posting_date[context.from_date : context.to_date])
		.where(gle.is_cancelled == 0)
		.where(gle.voucher_type != PERIOD_CLOSING_VOUCHER)
		.where(
			gle.finance_book.isin(finance_books(context.company, context.finance_book))
			| gle.finance_book.isnull()
		)
		.groupby(*group_columns, account.root_type)
		.run(as_dict=True)
	)


def _cash_balance(context, date) -> float:
	"""Balance on ``date`` of the accounts mapped to cash and cash equivalents."""
	mappings = context.balance_sheet_mappings
	balance = 0.0
	for group in get_account_balances(
		context.company, date, context.finance_book, columns=_condition_columns(mappings)
	):
		mapping = resolve_mapping(group, mappings.get(group.account, []))
		if mapping and mapping.report_line == CASH_LINE:
			balance += flt(group.balance)
	return flt(balance, 2)


def _condition_columns(mappings: dict) -> list:
	return sorted({m.condition.column for ms in mappings.values() for m in ms if m.condition})
