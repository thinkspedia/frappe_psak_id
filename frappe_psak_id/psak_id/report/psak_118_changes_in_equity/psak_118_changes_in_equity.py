# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

"""PSAK 118 statement of changes in equity as a Script Report.

The amounts come from the changes in equity engine; this module arranges them in one column per
component of equity and a total column, with the same period of the prior year as a block of its
own above the period, scales them to the chosen unit and reports the checks against the statement
of financial position and total comprehensive income (BR-37).
"""

import frappe
from frappe import _
from frappe.utils import add_years, cint, escape_html, flt, fmt_money, getdate

from frappe_psak_id.psak_id.changes_in_equity import CLOSING_LINE, compute_changes_in_equity
from frappe_psak_id.psak_id.report.psak_118_profit_or_loss.psak_118_profit_or_loss import (
	UNITS,
	_label_row,
	_period_label,
)
from frappe_psak_id.psak_id.statement import StatementError, check_read_access

UNMAPPED_LISTED = 5
TOTAL_COLUMN = "total"


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	periods = _validate(filters)
	# The comparative is classified with the reporting period's mappings, so it is restated in the
	# first year PSAK 118 is applied (FR-31)
	mapping_date = periods[0][1]
	statements = [
		compute_changes_in_equity(filters.company, start, end, filters.finance_book, mapping_date)
		for start, end in periods
	]

	columns = _columns(filters, statements)
	# The comparative block comes first, as in the published statements of listed companies
	data = [
		row
		for block in reversed(range(len(statements)))
		for row in _rows(filters, columns, statements, block)
	]
	current = statements[0]
	return columns, data, _message(current), None, _summary(current)


def _validate(filters) -> list:
	"""Check the filters, fill in defaults and return the period and the comparative period."""
	for fieldname, label in (
		("company", _("Company")),
		("from_date", _("From Date")),
		("to_date", _("To Date")),
	):
		if not filters.get(fieldname):
			frappe.throw(_("Choose the {0} of the statement.").format(label), frappe.MandatoryError)
	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)
	if from_date > to_date:
		frappe.throw(_("The period starts after it ends."), StatementError)

	if filters.unit not in UNITS:
		filters.unit = frappe.db.get_value("PSAK ID Company Policy", filters.company, "default_unit")
		filters.unit = filters.unit if filters.unit in UNITS else "Full"
	filters.language = filters.language if filters.language in ("Indonesian", "English") else "Both"

	check_read_access(filters.company)

	periods = [(from_date, to_date)]
	if cint(filters.comparative):
		periods.append((getdate(add_years(from_date, -1)), getdate(add_years(to_date, -1))))
	return periods


def _columns(filters, statements) -> list[dict]:
	"""The line, one column per component of equity of any period, and total equity."""
	components = {}
	for statement in statements:
		for component in statement.components:
			components.setdefault(component.line_code, component)
	order = [component.line_code for component in statements[0].components]
	order += [code for code in components if code not in order]

	columns = [{"fieldname": "line", "label": _("Line"), "fieldtype": "Data", "width": 320}]
	for index, code in enumerate(order):
		component = components[code]
		label = component.label_en if filters.language == "English" else component.label_id
		columns.append(_amount_column(filters, f"c{index}", label, component=code))
	columns.append(_amount_column(filters, TOTAL_COLUMN, _("Total Equity")))
	return columns


def _amount_column(filters, fieldname: str, label: str, component: str | None = None) -> dict:
	return {
		"fieldname": fieldname,
		"label": label,
		"fieldtype": "Float",
		"precision": 0,
		"width": 140,
		"component": component,
		# The print template reads the unit here: the filter may be empty (company default)
		"unit": filters.unit,
	}


def _rows(filters, columns, statements, block: int) -> list[dict]:
	"""A heading with the period when there are two, then one row per presented line; amounts are
	scaled for display only (P1-BR-22)."""
	statement = statements[block]
	unit = UNITS[filters.unit]
	rows = []
	if len(statements) > 1:
		rows.append(
			frappe._dict(
				line=_period_label(statement.from_date, statement.to_date), line_type="Heading", block=block
			)
		)

	for line in statement.rows:
		row = _label_row(filters, line.label_id, line.label_en, line_type=line.line_type)
		row.update(
			line_code=line.line_code,
			block=block,
			is_total=line.line_code == CLOSING_LINE,
			from_date=str(statement.from_date),
			to_date=str(statement.to_date),
			ledger={},
		)
		for column in columns[1:]:
			fieldname, component = column["fieldname"], column.get("component")
			amount = line.total if fieldname == TOTAL_COLUMN else flt(line.amounts.get(component))
			row[fieldname] = flt(amount / unit, 0)
			ledger = line.ledger.get(component) if component else None
			if ledger:
				row["ledger"][fieldname] = {
					"accounts": ledger["accounts"],
					"filters": ledger["ledger_filters"],
					"exact": ledger["ledger_exact"],
					"by_account": ledger["ledger_accounts"],
				}
		rows.append(row)
	return rows


def _summary(statement) -> list[dict]:
	currency = statement.currency

	def item(label, value, indicator="Blue"):
		return {
			"label": label,
			"value": value,
			"datatype": "Currency",
			"currency": currency,
			"indicator": indicator,
		}

	return [
		item(_("Closing Equity (PSAK 118)"), statement.closing_equity),
		item(_("Equity in the Statement of Financial Position"), statement.position_equity),
		item(
			_("Equity Difference"),
			statement.equity_difference,
			"Green" if not statement.equity_difference else "Red",
		),
		item(
			_("Comprehensive Income Difference"),
			statement.comprehensive_income_difference,
			"Green" if not statement.comprehensive_income_difference else "Red",
		),
	]


def _message(statement) -> str | None:
	messages = []
	accounts = sorted({row.account for row in statement.unmapped})
	if accounts:
		listed = ", ".join(escape_html(account) for account in accounts[:UNMAPPED_LISTED])
		if len(accounts) > UNMAPPED_LISTED:
			listed = _("{0} and {1} more").format(listed, len(accounts) - UNMAPPED_LISTED)
		messages.append(
			_(
				"{0} equity accounts have no component of equity ({1}). They are left out of the "
				"statement. Map them in PSAK ID Account Mapping."
			).format(len(accounts), listed)
		)
	for row in statement.component_differences:
		messages.append(
			_(
				"The closing balance of {0} differs from the statement of financial position by {1}, "
				"because an account's Equity Component is not its report line."
			).format(escape_html(row.component), fmt_money(row.difference, currency=statement.currency))
		)
	if statement.profit_or_loss_difference:
		messages.append(
			_(
				"Profit or loss differs from ERPNext's profit or loss by {0}, because income or expense "
				"accounts are not mapped. The PSAK ID Mapping Control report lists them."
			).format(fmt_money(statement.profit_or_loss_difference, currency=statement.currency))
		)
	return "<br>".join(messages) or None
