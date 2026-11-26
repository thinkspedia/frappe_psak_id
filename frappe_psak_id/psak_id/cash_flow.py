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
* Interest and dividends follow the profit or loss line they are presented on (BR-34): when the
  company's main business activity moves that line into operating profit, they stay in operating
  activities, and balance sheet accounts that name their cash flow line present their movements
  with the other assets or liabilities.
* Vouchers without cash whose accounts all present their movements in investing or financing
  activities, such as a right-of-use asset against its lease liability, are not cash flows: they
  are left out and listed as non-cash transactions (BR-35).
* A revaluation of a cash account in a foreign currency is the effect of exchange rate changes
  on cash, presented after the three activities and taken out of the profit or loss it was
  booked to (BR-36).

Period Closing Vouchers are left out: they only move profit or loss into equity. Since every
voucher balances, the movements of the accounts that are not cash add up to the change in cash,
so the closing balance of the statement must equal the ledger's balance of the accounts mapped to
cash and cash equivalents (BR-36). An account without a line breaks that check and is listed.
"""

import frappe
from frappe import _
from frappe.query_builder import Case
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
UNREALISED_EXCHANGE_DIFFERENCES_LINE = "CF-OP-FX"
EXCHANGE_RATE_EFFECT_LINE = "CF-FX"
OTHER_ASSETS_LINE = "CF-OP-WC-OA"
OTHER_LIABILITIES_LINE = "CF-OP-WC-OL"
# Interest and dividend cash flow lines, with the profit or loss line whose presentation they follow
INTEREST_AND_DIVIDEND_LINES = {
	"CF-INV-INT": "PL-INV-INC",
	"CF-INV-DIV": "PL-INV-INC",
	"CF-FIN-INT": "PL-FIN-INT",
}
NON_CASH_CATEGORIES = ("Investing", "Financing")
# Journal Entry voucher type of ERPNext's Exchange Rate Revaluation and of its reversal
REVALUATION = "Exchange Rate Revaluation"
# Why an account's cash effect is not on the statement, besides the reasons of the other statements
NO_CASH_FLOW_LINE = "No Cash Flow Line"


def compute_cash_flows(
	company: str, from_date, to_date, finance_book: str | None = None, mapping_date=None
) -> frappe._dict:
	"""Return the statement lines from ``from_date`` to ``to_date``, the accounts left out, the
	non-cash transactions and the check of the closing balance against the ledger's cash and cash
	equivalents.

	Accounts are classified with the mappings in force on ``mapping_date`` (default: ``to_date``),
	so a comparative period can be presented like the current one.
	"""
	from_date, to_date = getdate(from_date), getdate(to_date)
	if from_date > to_date:
		frappe.throw(_("The period starts after it ends."), StatementError)
	mapping_date = getdate(mapping_date) if mapping_date else to_date

	profit = compute(company, from_date, to_date, finance_book=finance_book, mapping_date=mapping_date)
	context = _context(company, from_date, to_date, finance_book, mapping_date)
	flows = _Flows(context.lines)

	profit_amounts = {line.line_code: line.amount for line in profit.lines}
	for line in context.lines.values():
		if line.source_line:
			flows.add_amount(line.name, profit_amounts.get(line.source_line))
	_add_profit_or_loss(context, flows)
	non_cash = _non_cash_transactions(context)
	_add_balance_sheet_movements(context, flows, non_cash)
	_add_exchange_rate_effect(context, flows)

	opening_cash = _cash_balance(context, add_days(from_date, -1))
	ledger_closing_cash = _cash_balance(context, to_date)
	flows.add_amount(OPENING_LINE, opening_cash)

	amounts = evaluate_lines(context.lines.values(), flows.line_amounts, flows.categories)
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
			for line in sorted(context.lines.values(), key=lambda line: line.sequence)
			if not line.disabled
		],
		unmapped=flows.unmapped_rows(),
		non_cash=[
			frappe._dict(
				voucher_type=row.voucher_type,
				voucher_no=row.voucher_no,
				posting_date=row.posting_date,
				account=row.account,
				amount=flt(flt(row.debit) - flt(row.credit), 2),
			)
			for row in sorted(non_cash, key=lambda row: (row.posting_date, row.voucher_no, row.account))
		],
		opening_cash=opening_cash,
		closing_cash=closing_cash,
		ledger_closing_cash=ledger_closing_cash,
		cash_difference=flt(closing_cash - ledger_closing_cash, 2),
		# Income or expense accounts without a profit or loss line leave operating profit incomplete
		profit_or_loss_difference=profit.ledger_difference,
	)


def _context(company: str, from_date, to_date, finance_book: str | None, mapping_date) -> frappe._dict:
	policy = get_policy(company)
	lines = get_lines(CASH_FLOW)
	profit_or_loss_lines = get_lines(PROFIT_OR_LOSS)
	profit_or_loss_categories = {
		code: effective_category(line, policy)
		for code, line in profit_or_loss_lines.items()
		if line.line_type == "Line"
	}
	return frappe._dict(
		company=company,
		from_date=from_date,
		to_date=to_date,
		finance_book=finance_book,
		lines=lines,
		profit_or_loss_lines=profit_or_loss_lines,
		balance_sheet_mappings=get_mappings(company, mapping_date, BALANCE_SHEET_ROOT_TYPES),
		profit_or_loss_mappings=get_mappings(company, mapping_date, PROFIT_OR_LOSS_ROOT_TYPES),
		operating_profit_lines=_operating_profit_lines(
			lines, profit_or_loss_lines, profit_or_loss_categories
		),
		# Interest and dividends of an entity whose main business is investing or financing (BR-34)
		operating_interest_lines={
			cash_flow_line
			for cash_flow_line, line in INTEREST_AND_DIVIDEND_LINES.items()
			if profit_or_loss_categories.get(line) == "Operating"
		},
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


def _operating_profit_lines(cash_flow_lines: dict, lines: dict, categories: dict) -> set:
	"""Profit or loss lines added into the lines that cash flow lines start from."""

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


def _add_profit_or_loss(context, flows: _Flows):
	"""Income and expenses outside operating profit, and operating profit items with a line of
	their own, on their cash flow lines."""
	groups = get_gl_groups(
		context.company,
		[(context.from_date, context.to_date)],
		None,
		context.finance_book,
		include_default_book(context.company, context.finance_book),
		columns=_condition_columns(context.profit_or_loss_mappings),
	)
	for group in groups:
		cash_flow_line, in_operating_profit, reason = _profit_or_loss_route(context, group)
		if cash_flow_line:
			flows.add_group(group, cash_flow_line, group.amount)
			if in_operating_profit:
				flows.add_group(group, NON_CASH_ADJUSTMENTS_LINE, -flt(group.amount))
		elif reason:
			flows.leave_out(group.account, reason, None, group.amount)


def _profit_or_loss_route(context, group) -> tuple[str | None, bool, str | None]:
	"""The cash flow line an income or expense GL group moves to, whether it is part of operating
	profit, and why it is left out of the statement."""
	candidates = context.profit_or_loss_mappings.get(group.account, [])
	mapping = resolve_mapping(group, candidates)
	line = context.profit_or_loss_lines.get(mapping.report_line) if mapping else None
	in_operating_profit = bool(line and not line.disabled and line.name in context.operating_profit_lines)
	cash_flow_line = mapping.cash_flow_line if mapping else None
	if in_operating_profit and cash_flow_line in context.operating_interest_lines:
		cash_flow_line = None
	if cash_flow_line or in_operating_profit:
		return cash_flow_line, in_operating_profit, None
	return None, False, _reason(mapping, line, candidates)


def _reason(mapping, line, candidates) -> str:
	if mapping:
		return DISABLED_LINE if not line or line.disabled else NO_CASH_FLOW_LINE
	return NO_MATCHING_CONDITION if candidates else NOT_MAPPED


def _add_balance_sheet_movements(context, flows: _Flows, non_cash: list):
	columns = _condition_columns(context.balance_sheet_mappings)
	excluded = {}
	for row in non_cash:
		totals = excluded.setdefault(_group_key(row, columns), [0.0, 0.0])
		totals[0] += flt(row.debit)
		totals[1] += flt(row.credit)

	for group in _get_movements(context, columns):
		debit, credit = excluded.get(_group_key(group, columns), (0.0, 0.0))
		group.debit, group.credit = flt(group.debit) - debit, flt(group.credit) - credit
		parts, reason = _balance_sheet_parts(context, group)
		if reason:
			flows.leave_out(group.account, reason, None, group.credit - group.debit)
		for line_code, amount in parts:
			flows.add_group(group, line_code, amount)


def _balance_sheet_parts(context, group) -> tuple[list, str | None]:
	"""The cash flow lines a balance sheet GL group's movements are presented on, with their
	amounts, or why they are left out. Cash itself has neither."""
	candidates = context.balance_sheet_mappings.get(group.account, [])
	mapping = resolve_mapping(group, candidates)
	if mapping and mapping.report_line == CASH_LINE:
		return [], None
	if not mapping or not mapping.cash_flow_line:
		return [], NO_CASH_FLOW_LINE if mapping else (NO_MATCHING_CONDITION if candidates else NOT_MAPPED)

	is_asset = group.root_type == "Asset"
	main_line = _presented_line(context, mapping.cash_flow_line, is_asset)
	if not mapping.cash_flow_line_decrease:
		return [(main_line, flt(group.credit) - flt(group.debit))], None
	# An asset increases with debits, a liability or equity account with credits
	increase, decrease = (
		(-flt(group.debit), flt(group.credit)) if is_asset else (flt(group.credit), -flt(group.debit))
	)
	decrease_line = _presented_line(context, mapping.cash_flow_line_decrease, is_asset)
	return [
		(line, amount) for line, amount in ((main_line, increase), (decrease_line, decrease)) if amount
	], None


def _presented_line(context, cash_flow_line: str, is_asset: bool) -> str:
	# Interest or dividends presented in operating activities: a receivable or payable of them is
	# working capital (BR-34)
	if cash_flow_line in context.operating_interest_lines:
		return OTHER_ASSETS_LINE if is_asset else OTHER_LIABILITIES_LINE
	return cash_flow_line


def _non_cash_transactions(context) -> list:
	"""Rows of the vouchers without cash whose accounts all present their movements in investing or
	financing activities (BR-35), per account and condition dimension values."""
	accounts = [
		account
		for account, candidates in context.balance_sheet_mappings.items()
		if any(
			context.lines.get(line) and context.lines[line].category in NON_CASH_CATEGORIES
			for mapping in candidates
			for line in (mapping.cash_flow_line, mapping.cash_flow_line_decrease)
		)
	]
	if not accounts:
		return []

	gle = frappe.qb.DocType("GL Entry")
	vouchers = {
		(row.voucher_type, row.voucher_no)
		for row in _period_entries(context, gle)
		.select(gle.voucher_type, gle.voucher_no)
		.groupby(gle.voucher_type, gle.voucher_no)
		.having(Sum(Case().when(gle.account.isin(accounts), 0).else_(1)) == 0)
		.run(as_dict=True)
	}
	if not vouchers:
		return []

	account = frappe.qb.DocType("Account")
	group_columns = gl_group_columns(gle, _condition_columns(context.balance_sheet_mappings))
	rows_by_voucher = {}
	for row in (
		_period_entries(context, gle)
		.join(account)
		.on(account.name == gle.account)
		.select(
			gle.voucher_type,
			gle.voucher_no,
			gle.posting_date,
			*group_columns,
			account.root_type,
			Sum(gle.debit).as_("debit"),
			Sum(gle.credit).as_("credit"),
		)
		.where(gle.voucher_no.isin(sorted({voucher_no for _type, voucher_no in vouchers})))
		.groupby(gle.voucher_type, gle.voucher_no, gle.posting_date, *group_columns, account.root_type)
		.run(as_dict=True)
	):
		if (row.voucher_type, row.voucher_no) in vouchers:
			rows_by_voucher.setdefault((row.voucher_type, row.voucher_no), []).append(row)

	return [
		row
		for rows in rows_by_voucher.values()
		if all(_is_non_cash_movement(context, row) for row in rows)
		for row in rows
	]


def _is_non_cash_movement(context, row) -> bool:
	parts, reason = _balance_sheet_parts(context, row)
	return (
		not reason
		and bool(parts)
		and all(
			context.lines.get(line_code) and context.lines[line_code].category in NON_CASH_CATEGORIES
			for line_code, _amount in parts
		)
	)


def _add_exchange_rate_effect(context, flows: _Flows):
	"""Revaluations of cash accounts, taken out of the profit or loss they were booked to."""
	journal_entry = frappe.qb.DocType("Journal Entry")
	revaluations = (
		frappe.qb.from_(journal_entry)
		.select(journal_entry.name)
		.where(journal_entry.company == context.company)
		.where(journal_entry.voucher_type == REVALUATION)
		.where(journal_entry.docstatus == 1)
		.where(journal_entry.posting_date[context.from_date : context.to_date])
	)
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	columns = sorted(
		set(_condition_columns(context.balance_sheet_mappings))
		| set(_condition_columns(context.profit_or_loss_mappings))
	)
	group_columns = gl_group_columns(gle, columns)
	rows = (
		_period_entries(context, gle)
		.join(account)
		.on(account.name == gle.account)
		.select(*group_columns, account.root_type, Sum(gle.debit).as_("debit"), Sum(gle.credit).as_("credit"))
		.where(gle.voucher_type == "Journal Entry")
		.where(gle.voucher_no.isin(revaluations))
		.groupby(*group_columns, account.root_type)
		.run(as_dict=True)
	)

	effect = 0.0
	for row in rows:
		if row.root_type in BALANCE_SHEET_ROOT_TYPES and _is_cash(context, row):
			flows.add_group(row, EXCHANGE_RATE_EFFECT_LINE, flt(row.debit) - flt(row.credit))
			effect += flt(row.debit) - flt(row.credit)
	profit_rows = [row for row in rows if row.root_type in PROFIT_OR_LOSS_ROOT_TYPES]
	if not flt(effect, 2) or not profit_rows:
		return

	# The revaluation gain or loss account of the company takes the cash part out of profit or loss
	gain_or_loss = max(profit_rows, key=lambda row: abs(flt(row.credit) - flt(row.debit)))
	gain_or_loss.amount = flt(gain_or_loss.credit) - flt(gain_or_loss.debit)
	cash_flow_line, in_operating_profit, reason = _profit_or_loss_route(context, gain_or_loss)
	line_code = cash_flow_line or (UNREALISED_EXCHANGE_DIFFERENCES_LINE if in_operating_profit else None)
	if line_code:
		flows.add_group(gain_or_loss, line_code, -effect)
	else:
		flows.leave_out(gain_or_loss.account, reason, None, -effect)


def _is_cash(context, group) -> bool:
	mapping = resolve_mapping(group, context.balance_sheet_mappings.get(group.account, []))
	return bool(mapping and mapping.report_line == CASH_LINE)


def _period_entries(context, gle):
	"""GL Entries of the period and finance book, without cancelled entries and Period Closing
	Vouchers."""
	return (
		frappe.qb.from_(gle)
		.where(gle.company == context.company)
		.where(gle.posting_date[context.from_date : context.to_date])
		.where(gle.is_cancelled == 0)
		.where(gle.voucher_type != PERIOD_CLOSING_VOUCHER)
		.where(
			gle.finance_book.isin(finance_books(context.company, context.finance_book))
			| gle.finance_book.isnull()
		)
	)


def _get_movements(context, columns: list) -> list:
	"""Debits and credits of the period per balance sheet account and condition dimension values."""
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	group_columns = gl_group_columns(gle, columns)
	return (
		_period_entries(context, gle)
		.join(account)
		.on(account.name == gle.account)
		.select(*group_columns, account.root_type, Sum(gle.debit).as_("debit"), Sum(gle.credit).as_("credit"))
		.where(account.root_type.isin(BALANCE_SHEET_ROOT_TYPES))
		.groupby(*group_columns, account.root_type)
		.run(as_dict=True)
	)


def _group_key(group, columns: list) -> tuple:
	names = ["account", *(name for column in columns for name in _column_names(column))]
	return tuple(group.get(name) for name in names)


def _column_names(column: str) -> tuple:
	return ("party_type", "party") if column == "party" else (column,)


def _cash_balance(context, date) -> float:
	"""Balance on ``date`` of the accounts mapped to cash and cash equivalents."""
	mappings = context.balance_sheet_mappings
	return flt(
		sum(
			flt(group.balance)
			for group in get_account_balances(
				context.company, date, context.finance_book, columns=_condition_columns(mappings)
			)
			if _is_cash(context, group)
		),
		2,
	)


def _condition_columns(mappings: dict) -> list:
	return sorted({m.condition.column for ms in mappings.values() for m in ms if m.condition})
