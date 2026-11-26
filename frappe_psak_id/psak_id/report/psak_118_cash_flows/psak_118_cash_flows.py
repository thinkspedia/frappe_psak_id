# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

"""PSAK 118 statement of cash flows as a Script Report.

The amounts come from the cash flow engine; this module arranges them in the period column and
the same period of the prior year, scales them to the chosen unit and reports the check of the
closing balance against the ledger's cash and cash equivalents (BR-36).
"""

import frappe
from frappe import _
from frappe.utils import add_years, cint, escape_html, flt, fmt_money, getdate

from frappe_psak_id.psak_id.cash_flow import CLOSING_LINE, compute_cash_flows
from frappe_psak_id.psak_id.report.psak_118_profit_or_loss.psak_118_profit_or_loss import (
	UNITS,
	_label_row,
	_period_label,
)
from frappe_psak_id.psak_id.statement import StatementError, check_read_access

UNMAPPED_LISTED = 5

# PSAK wording in both languages, per activity
HEADING_LABELS = {
	"Operating": ("Arus Kas dari Aktivitas Operasi", "Cash Flows from Operating Activities"),
	"Investing": ("Arus Kas dari Aktivitas Investasi", "Cash Flows from Investing Activities"),
	"Financing": ("Arus Kas dari Aktivitas Pendanaan", "Cash Flows from Financing Activities"),
}


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	periods = _validate(filters)
	# The comparative is classified with the reporting period's mappings, so it is restated in the
	# first year PSAK 118 is applied (FR-31)
	mapping_date = periods[0][1]
	statements = [
		compute_cash_flows(filters.company, start, end, filters.finance_book, mapping_date)
		for start, end in periods
	]

	columns = _columns(filters, statements)
	data = _rows(filters, columns, statements)
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
	columns = [{"fieldname": "line", "label": _("Line"), "fieldtype": "Data", "width": 420}]
	for index, statement in enumerate(statements):
		columns.append(
			{
				"fieldname": f"p{index}",
				"label": _period_label(statement.from_date, statement.to_date),
				"fieldtype": "Float",
				"precision": 0,
				"width": 160,
				"from_date": str(statement.from_date),
				"to_date": str(statement.to_date),
				# The print template reads the unit here: the filter may be empty (company default)
				"unit": filters.unit,
			}
		)
	return columns


def _rows(filters, columns, statements) -> list[dict]:
	"""One row per presented line; amounts are scaled for display only (P1-BR-22)."""
	unit = UNITS[filters.unit]
	lines_by_column = {
		f"p{index}": {line.line_code: line for line in statement.lines}
		for index, statement in enumerate(statements)
	}
	show_headings = frappe.db.get_value("PSAK ID Company Policy", filters.company, "show_category_headings")

	rows, heading = [], None
	for line in statements[0].lines:
		if show_headings and line.line_type == "Line" and line.category in HEADING_LABELS:
			if line.category != heading:
				heading = line.category
				rows.append(_label_row(filters, *HEADING_LABELS[heading], line_type="Heading"))

		row = _label_row(filters, line.label_id, line.label_en, line_type=line.line_type)
		row.update(
			line_code=line.line_code,
			# Not "indent": that key turns the datatable into a collapsible tree
			indented=bool(show_headings and line.line_type == "Line" and line.category),
			is_total=line.line_code == CLOSING_LINE,
			ledger={},
		)
		for column in columns[1:]:
			fieldname = column["fieldname"]
			column_line = lines_by_column[fieldname][line.line_code]
			row[fieldname] = flt(column_line.amount / unit, 0)
			row["ledger"][fieldname] = {
				"accounts": column_line.accounts,
				"filters": column_line.ledger_filters,
				"exact": column_line.ledger_exact,
				"by_account": column_line.ledger_accounts,
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
		item(_("Closing Cash (PSAK 118)"), statement.closing_cash),
		item(_("Cash and Cash Equivalents in the Ledger"), statement.ledger_closing_cash),
		item(
			_("Cash Difference"),
			statement.cash_difference,
			"Green" if not statement.cash_difference else "Red",
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
				"{0} accounts with movements in the period have no cash flow line ({1}). They are left out "
				"of the statement, so the closing cash does not match the ledger yet. Set their Cash Flow "
				"Line in PSAK ID Account Mapping."
			).format(len(accounts), listed)
		)
	if statement.profit_or_loss_difference:
		messages.append(
			_(
				"Operating profit or loss differs from ERPNext's profit or loss by {0}, because income or "
				"expense accounts are not mapped. The PSAK ID Mapping Control report lists them."
			).format(fmt_money(statement.profit_or_loss_difference, currency=statement.currency))
		)
	vouchers = sorted({row.voucher_no for row in statement.non_cash})
	if vouchers:
		listed = ", ".join(escape_html(voucher) for voucher in vouchers[:UNMAPPED_LISTED])
		if len(vouchers) > UNMAPPED_LISTED:
			listed = _("{0} and {1} more").format(listed, len(vouchers) - UNMAPPED_LISTED)
		messages.append(
			_(
				"{0} vouchers are non-cash transactions of investing or financing activities ({1}). They are "
				"left out of the cash flows and disclosed as non-cash transactions."
			).format(len(vouchers), listed)
		)
	return "<br>".join(messages) or None
