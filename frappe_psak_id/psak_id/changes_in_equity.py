"""PSAK 118 statement of changes in equity computed from ERPNext's General Ledger.

The columns are the components of equity: the equity lines of the statement of financial position
that the equity accounts' mappings name as their Equity Component (by default their report line).
The rows are the lines of the Changes in Equity statement:

* The opening balance of each component is the balance of its accounts the day before the period.
  Retained earnings also take the profit or loss that no Period Closing Voucher has moved into
  equity yet (BR-32): the ledger's for earlier fiscal years and, as in the statement of financial
  position, PSAK 118 profit or loss from the start of the fiscal year, so a period that starts in
  the middle of the year ends on equity in the statement of financial position.
* Profit or loss of the period (``PL-SUB-PL``) is presented in retained earnings. Period Closing
  Vouchers are left out, since they only move that profit or loss into an equity account.
* A voucher that only moves amounts between equity accounts is a transfer between components.
* Other movements of an account with an OCI line are other comprehensive income.
* Other movements of an account in treasury shares are treasury shares.
* Every other movement follows the cash flow line of the account's own mapping, by direction when
  the mapping names a line for decreases: dividends paid are dividends, proceeds from issuing shares
  are issues of shares, and anything else is other changes. The counter account is not used: cash
  has no cash flow line, and a dividend payable is usually working capital.

The closing balance of each component must equal its equity in the statement of financial position
on the same date, and total comprehensive income must equal ``OCI-SUB-TCI`` (BR-37).
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import add_days, flt, getdate

from frappe_psak_id.psak_id.financial_position import (
	RETAINED_EARNINGS_LINE,
	compute_financial_position,
	finance_books,
	fiscal_year_start,
	get_account_balances,
	profit_or_loss_before,
)
from frappe_psak_id.psak_id.report_lines import CHANGES_IN_EQUITY, FINANCIAL_POSITION
from frappe_psak_id.psak_id.statement import (
	DISABLED_LINE,
	NO_MATCHING_CONDITION,
	NOT_MAPPED,
	PERIOD_CLOSING_VOUCHER,
	StatementError,
	compute,
	evaluate_lines,
	get_lines,
	get_mappings,
	gl_group_columns,
	ledger_filters,
	resolve_mapping,
)

EQUITY = "Equity"
OPENING_LINE = "EQ-OPEN"
PROFIT_OR_LOSS_LINE = "EQ-PL"
OTHER_COMPREHENSIVE_INCOME_LINE = "EQ-OCI"
TOTAL_COMPREHENSIVE_INCOME_LINE = "EQ-SUB-TCI"
TRANSFER_LINE = "EQ-TRANSFER"
TREASURY_SHARES_LINE = "EQ-TREAS"
OTHER_CHANGES_LINE = "EQ-OTH"
CLOSING_LINE = "EQ-CLOSE"
TOTAL_EQUITY_LINE = "FP-SUB-EQ"
TREASURY_SHARES_COMPONENT = "FP-EQ-TREAS"
# Why an equity account is left out when its component is not an enabled equity line
INVALID_EQUITY_COMPONENT = "Invalid Equity Component"
# The changes in equity line of an equity account's movements, by the cash flow line they are on
CASH_FLOW_MOVEMENT_LINES = {"CF-FIN-DIV": "EQ-DIV", "CF-FIN-EQ": "EQ-ISSUE"}


def compute_changes_in_equity(
	company: str, from_date, to_date, finance_book: str | None = None, mapping_date=None
) -> frappe._dict:
	"""Return the components of equity, the statement rows from ``from_date`` to ``to_date`` with
	an amount per component, the accounts left out and the checks against the statement of financial
	position and total comprehensive income.

	Accounts are classified with the mappings in force on ``mapping_date`` (default: ``to_date``),
	so a comparative period can be presented like the current one.
	"""
	from_date, to_date = getdate(from_date), getdate(to_date)
	if from_date > to_date:
		frappe.throw(_("The period starts after it ends."), StatementError)
	mapping_date = getdate(mapping_date) if mapping_date else to_date

	context = _context(company, from_date, to_date, finance_book, mapping_date)
	cells = _Cells(context)
	_add_opening_balances(context, cells)
	profit = compute(company, from_date, to_date, finance_book=finance_book, mapping_date=mapping_date)
	cells.add(PROFIT_OR_LOSS_LINE, RETAINED_EARNINGS_LINE, profit.profit_or_loss)
	_add_movements(context, cells)

	position = compute_financial_position(company, to_date, finance_book, mapping_date)
	return _result(context, cells, profit, position)


def _context(company: str, from_date, to_date, finance_book: str | None, mapping_date) -> frappe._dict:
	mappings = get_mappings(company, mapping_date, (EQUITY,))
	return frappe._dict(
		company=company,
		from_date=from_date,
		to_date=to_date,
		finance_book=finance_book,
		mapping_date=mapping_date,
		lines=get_lines(CHANGES_IN_EQUITY),
		position_lines=get_lines(FINANCIAL_POSITION),
		mappings=mappings,
		equity_fields=_equity_fields(mappings),
		columns=sorted({m.condition.column for ms in mappings.values() for m in ms if m.condition}),
	)


def _equity_fields(mappings: dict) -> dict:
	"""Equity Component and OCI Line of each mapping, by mapping name."""
	names = [mapping.name for candidates in mappings.values() for mapping in candidates]
	if not names:
		return {}
	return {
		row.name: row
		for row in frappe.get_all(
			"PSAK ID Account Mapping",
			filters={"name": ("in", names)},
			fields=["name", "report_line", "equity_component", "oci_line"],
		)
	}


class _Cells:
	"""Amounts per line and component, the GL groups behind them and the accounts left out."""

	def __init__(self, context):
		self.context = context
		self.amounts, self.groups, self.unmapped = {}, {}, {}
		self.all_groups = []

	def add(self, line_code: str, component: str, amount):
		key = (line_code, component)
		self.amounts[key] = flt(self.amounts.get(key)) + flt(amount)

	def add_group(self, group, line_code: str, component: str, amount):
		"""Present ``amount`` of one GL group in a cell; a disabled or missing line leaves it out."""
		line = self.context.lines.get(line_code)
		if not line or line.disabled or line.line_type != "Line":
			self.leave_out(group.account, DISABLED_LINE, line_code, amount)
			return
		part = frappe._dict(group, line=_cell_key(line_code, component), amount=flt(amount))
		self.all_groups.append(part)
		self.groups.setdefault((line_code, component), []).append(part)
		self.add(line_code, component, amount)

	def leave_out(self, account: str, reason: str, line_code: str | None, amount):
		"""Leave ``amount`` out; ``line_code`` is the disabled line or invalid component it is on."""
		key = (account, reason, line_code)
		self.unmapped[key] = flt(self.unmapped.get(key)) + flt(amount)

	def components(self) -> set:
		return {component for (_line, component), amount in self.amounts.items() if flt(amount, 2)}


def _cell_key(line_code: str, component: str) -> str:
	return f"{line_code}|{component}"


def _component(context, group) -> tuple[str | None, frappe._dict | None, str | None]:
	"""The component an equity GL group belongs to, its mapping's equity fields, and why it is left
	out when it has no valid component."""
	candidates = context.mappings.get(group.account, [])
	mapping = resolve_mapping(group, candidates)
	if not mapping:
		return None, None, NO_MATCHING_CONDITION if candidates else NOT_MAPPED
	fields = context.equity_fields.get(mapping.name) or frappe._dict(report_line=mapping.report_line)
	component = fields.equity_component or fields.report_line
	line = context.position_lines.get(component)
	if not line or line.disabled or line.category != EQUITY:
		return component, fields, INVALID_EQUITY_COMPONENT
	return component, frappe._dict(fields, mapping=mapping), None


def _add_opening_balances(context, cells: _Cells):
	"""Equity on the day before the period: account balances with the Period Closing Vouchers of
	earlier fiscal years, and the profit or loss that none has closed yet in retained earnings."""
	opening_date = add_days(context.from_date, -1)
	year_start = fiscal_year_start(context.company, context.from_date)
	for group in get_account_balances(
		context.company, opening_date, context.finance_book, columns=context.columns, closing_from=year_start
	):
		if group.root_type != EQUITY:
			continue
		component, _fields, reason = _component(context, group)
		if reason:
			cells.leave_out(group.account, reason, component, -flt(group.balance))
			continue
		cells.add(OPENING_LINE, component, -flt(group.balance))
	cells.add(
		OPENING_LINE,
		RETAINED_EARNINGS_LINE,
		profit_or_loss_before(context.company, year_start, context.finance_book),
	)
	if context.from_date > year_start:
		earlier = compute(
			context.company,
			year_start,
			opening_date,
			finance_book=context.finance_book,
			mapping_date=context.mapping_date,
		)
		cells.add(OPENING_LINE, RETAINED_EARNINGS_LINE, earlier.profit_or_loss)


def _add_movements(context, cells: _Cells):
	"""Movements of equity accounts in the period, per voucher, on their changes in equity line."""
	rows = _equity_movements(context)
	outside_equity = _vouchers_outside_equity(context, {row.voucher_no for row in rows})
	for row in rows:
		component, fields, reason = _component(context, row)
		amount = flt(row.credit) - flt(row.debit)
		if reason:
			cells.leave_out(row.account, reason, component, amount)
			continue
		if (row.voucher_type, row.voucher_no) not in outside_equity:
			cells.add_group(row, TRANSFER_LINE, component, amount)
		elif fields.oci_line:
			cells.add_group(row, OTHER_COMPREHENSIVE_INCOME_LINE, component, amount)
		elif component == TREASURY_SHARES_COMPONENT:
			cells.add_group(row, TREASURY_SHARES_LINE, component, amount)
		else:
			for line_code, part in _movement_parts(fields.mapping, row):
				cells.add_group(row, line_code, component, part)


def _movement_parts(mapping, row) -> list[tuple[str, float]]:
	"""The changes in equity lines of one movement by the cash flow lines of its mapping: increases
	(credits) and decreases (debits) apart when the mapping names a line for decreases."""
	if not mapping.cash_flow_line_decrease:
		return [(_movement_line(mapping.cash_flow_line), flt(row.credit) - flt(row.debit))]
	return [
		(line_code, amount)
		for line_code, amount in (
			(_movement_line(mapping.cash_flow_line), flt(row.credit)),
			(_movement_line(mapping.cash_flow_line_decrease), -flt(row.debit)),
		)
		if amount
	]


def _movement_line(cash_flow_line: str | None) -> str:
	return CASH_FLOW_MOVEMENT_LINES.get(cash_flow_line, OTHER_CHANGES_LINE)


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


def _equity_movements(context) -> list:
	"""Debits and credits of the period per voucher, equity account and condition dimension values."""
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	group_columns = gl_group_columns(gle, context.columns)
	return (
		_period_entries(context, gle)
		.join(account)
		.on(account.name == gle.account)
		.select(
			gle.voucher_type,
			gle.voucher_no,
			*group_columns,
			account.root_type,
			Sum(gle.debit).as_("debit"),
			Sum(gle.credit).as_("credit"),
		)
		.where(account.root_type == EQUITY)
		.groupby(gle.voucher_type, gle.voucher_no, *group_columns, account.root_type)
		.run(as_dict=True)
	)


def _vouchers_outside_equity(context, voucher_nos: set) -> set:
	"""The vouchers among ``voucher_nos`` with an entry in an account that is not equity."""
	if not voucher_nos:
		return set()
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	rows = (
		_period_entries(context, gle)
		.join(account)
		.on(account.name == gle.account)
		.select(gle.voucher_type, gle.voucher_no)
		.distinct()
		.where(gle.voucher_no.isin(sorted(voucher_nos)))
		.where(account.root_type != EQUITY)
		.run(as_dict=True)
	)
	return {(row.voucher_type, row.voucher_no) for row in rows}


def _result(context, cells: _Cells, profit, position) -> frappe._dict:
	position_amounts = {line.line_code: flt(line.amount) for line in position.lines}
	components = _ordered_components(
		context,
		cells.components()
		| {
			code
			for code, amount in position_amounts.items()
			if _is_component(context, code) and flt(amount, 2)
		},
	)
	ordered_lines = [
		line for line in sorted(context.lines.values(), key=lambda line: line.sequence) if not line.disabled
	]
	amounts = {
		component: evaluate_lines(
			context.lines.values(),
			{line_code: amount for (line_code, cell), amount in cells.amounts.items() if cell == component},
			{},
		)
		for component in components
	}

	rows = []
	for line in ordered_lines:
		cell_amounts = {component: flt(amounts[component].get(line.name)) for component in components}
		rows.append(
			frappe._dict(
				line_code=line.name,
				label_id=line.label_id,
				label_en=line.label_en,
				line_type=line.line_type,
				is_other_items=line.is_other_items,
				amounts=cell_amounts,
				total=flt(sum(cell_amounts.values())),
				ledger={
					component: ledger_filters(
						_cell_key(line.name, component),
						cells.groups.get((line.name, component), []),
						cells.all_groups,
					)
					for component in components
					if cells.groups.get((line.name, component))
				},
			)
		)

	closing = {component: flt(amounts[component].get(CLOSING_LINE), 2) for component in components}
	total_comprehensive_income = flt(
		sum(flt(amounts[component].get(TOTAL_COMPREHENSIVE_INCOME_LINE)) for component in components), 2
	)
	total_equity = flt(position_amounts.get(TOTAL_EQUITY_LINE), 2)
	return frappe._dict(
		company=context.company,
		from_date=context.from_date,
		to_date=context.to_date,
		finance_book=context.finance_book,
		currency=profit.currency,
		components=[
			frappe._dict(
				line_code=code,
				label_id=context.position_lines[code].label_id,
				label_en=context.position_lines[code].label_en,
			)
			for code in components
		],
		rows=rows,
		unmapped=[
			frappe._dict(account=account, reason=reason, report_line=line_code, amount=amount)
			for (account, reason, line_code), amount in sorted(cells.unmapped.items(), key=lambda i: i[0][:2])
			if flt(amount, 2)
		],
		closing_equity=flt(sum(closing.values()), 2),
		position_equity=total_equity,
		equity_difference=flt(sum(closing.values()) - total_equity, 2),
		# Components whose closing balance differs from their line in the statement of financial
		# position, for example accounts presented in another column than their report line
		component_differences=[
			frappe._dict(
				component=component,
				closing=closing[component],
				position=flt(position_amounts.get(component), 2),
				difference=flt(closing[component] - flt(position_amounts.get(component)), 2),
			)
			for component in components
			if flt(closing[component] - flt(position_amounts.get(component)), 2)
		],
		total_comprehensive_income=total_comprehensive_income,
		statement_total_comprehensive_income=flt(profit.total_comprehensive_income, 2),
		comprehensive_income_difference=flt(
			total_comprehensive_income - flt(profit.total_comprehensive_income), 2
		),
		# Income or expense accounts without a profit or loss line leave profit or loss incomplete
		profit_or_loss_difference=profit.ledger_difference,
	)


def _is_component(context, code: str) -> bool:
	line = context.position_lines.get(code)
	return bool(line and line.line_type == "Line" and line.category == EQUITY and not line.disabled)


def _ordered_components(context, codes: set) -> list[str]:
	"""Components in the order of the statement of financial position; retained earnings always
	have a column, since profit or loss is presented there."""
	codes = {code for code in codes | {RETAINED_EARNINGS_LINE} if code in context.position_lines}
	return sorted(codes, key=lambda code: context.position_lines[code].sequence)
