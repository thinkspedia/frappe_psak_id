# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

"""PSAK 118 statement of financial position as a Script Report.

The amounts come from the financial position engine; this module arranges them in a reporting
date column and the prior year end comparative, scales them to the chosen unit and reports the
check against ERPNext's Balance Sheet (BR-31).
"""

import frappe
from frappe import _
from frappe.utils import cint, escape_html, flt, fmt_money, formatdate, getdate

from frappe_psak_id.psak_id.financial_position import (
	RETAINED_EARNINGS_LINE,
	TOTAL_ASSETS_LINE,
	TOTAL_LIABILITIES_AND_EQUITY_LINE,
	compute_positions,
	prior_year_end,
)
from frappe_psak_id.psak_id.report.psak_118_profit_or_loss.psak_118_profit_or_loss import (
	UNITS,
	_label_row,
)
from frappe_psak_id.psak_id.statement import check_read_access

UNMAPPED_LISTED = 5

# PSAK wording in both languages, per category and classification
HEADING_LABELS = {
	("Asset", "Non-current"): ("Aset Tidak Lancar", "Non-current Assets"),
	("Asset", "Current"): ("Aset Lancar", "Current Assets"),
	("Liability", "Current"): ("Liabilitas Jangka Pendek", "Current Liabilities"),
	("Liability", "Non-current"): ("Liabilitas Jangka Panjang", "Non-current Liabilities"),
	("Equity", None): ("Ekuitas", "Equity"),
}


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	dates = _validate(filters)
	# The comparative is classified with the reporting date's mappings, like the current column
	positions = compute_positions(filters.company, dates, filters.finance_book, mapping_date=dates[0])

	columns = _columns(filters, positions)
	data = _rows(filters, columns, positions)
	current = positions[0]
	return columns, data, _message(current), None, _summary(current)


def _validate(filters) -> list:
	"""Check the filters, fill in defaults and return the reporting date and the comparative date."""
	for fieldname, label in (("company", _("Company")), ("to_date", _("Date"))):
		if not filters.get(fieldname):
			frappe.throw(_("Choose the {0} of the statement.").format(label), frappe.MandatoryError)

	if filters.unit not in UNITS:
		filters.unit = frappe.db.get_value("PSAK ID Company Policy", filters.company, "default_unit")
		filters.unit = filters.unit if filters.unit in UNITS else "Full"
	filters.language = filters.language if filters.language in ("Indonesian", "English") else "Both"

	check_read_access(filters.company)

	to_date = getdate(filters.to_date)
	if not cint(filters.comparative):
		return [to_date]
	return [to_date, prior_year_end(filters.company, to_date)]


def _columns(filters, positions) -> list[dict]:
	columns = [{"fieldname": "line", "label": _("Line"), "fieldtype": "Data", "width": 420}]
	for index, position in enumerate(positions):
		columns.append(
			{
				"fieldname": f"p{index}",
				"label": formatdate(position.to_date, "d MMM yyyy"),
				"fieldtype": "Float",
				"precision": 0,
				"width": 160,
				# The General Ledger opens at the start of the fiscal year, with its opening balance
				"from_date": str(position.from_date),
				"to_date": str(position.to_date),
				# The print template reads the unit here: the filter may be empty (company default)
				"unit": filters.unit,
			}
		)
	return columns


def _rows(filters, columns, positions) -> list[dict]:
	"""One row per presented line; amounts are scaled for display only (P1-BR-22)."""
	unit = UNITS[filters.unit]
	lines_by_column = {
		f"p{index}": {line.line_code: line for line in position.lines}
		for index, position in enumerate(positions)
	}
	show_headings = frappe.db.get_value("PSAK ID Company Policy", filters.company, "show_category_headings")

	rows, heading = [], None
	for line in positions[0].lines:
		key = (line.category, line.classification or None)
		if show_headings and line.line_type == "Line" and key != heading and key in HEADING_LABELS:
			heading = key
			rows.append(_label_row(filters, *HEADING_LABELS[key], line_type="Heading"))

		row = _label_row(filters, line.label_id, line.label_en, line_type=line.line_type)
		row.update(
			line_code=line.line_code,
			# Not "indent": that key turns the datatable into a collapsible tree
			indented=bool(show_headings and line.line_type == "Line"),
			is_total=line.line_code in (TOTAL_ASSETS_LINE, TOTAL_LIABILITIES_AND_EQUITY_LINE),
			ledger={},
		)
		for column in columns[1:]:
			fieldname = column["fieldname"]
			column_line = lines_by_column[fieldname][line.line_code]
			row[fieldname] = flt(column_line.amount / unit, 0)
			row["ledger"][fieldname] = {
				"accounts": column_line.accounts,
				"filters": column_line.ledger_filters,
				# Retained earnings also hold the year's profit or loss, which is not in its accounts
				"exact": column_line.ledger_exact and line.line_code != RETAINED_EARNINGS_LINE,
				"by_account": column_line.ledger_accounts,
			}
		rows.append(row)
	return rows


def _summary(position) -> list[dict]:
	currency = position.currency

	def item(label, value, indicator="Blue"):
		return {
			"label": label,
			"value": value,
			"datatype": "Currency",
			"currency": currency,
			"indicator": indicator,
		}

	return [
		item(_("Total Assets (PSAK 118)"), position.total_assets),
		item(_("Total Liabilities and Equity (PSAK 118)"), position.total_liabilities_and_equity),
		item(_("Total Assets in ERPNext Balance Sheet"), position.ledger_total_assets),
		item(
			_("Difference to ERPNext"),
			position.ledger_difference,
			"Green" if not position.ledger_difference else "Red",
		),
	]


def _message(position) -> str | None:
	messages = []
	accounts = sorted({row.account for row in position.unmapped})
	if accounts:
		listed = ", ".join(escape_html(account) for account in accounts[:UNMAPPED_LISTED])
		if len(accounts) > UNMAPPED_LISTED:
			listed = _("{0} and {1} more").format(listed, len(accounts) - UNMAPPED_LISTED)
		messages.append(
			_(
				"{0} balance sheet accounts with a balance are not mapped to a PSAK 118 line ({1}). They are "
				"left out of the statement, so it does not match ERPNext's Balance Sheet yet. Map them in "
				"PSAK ID Account Mapping."
			).format(len(accounts), listed)
		)
	if position.profit_or_loss_difference:
		messages.append(
			_(
				"The profit or loss of the year in retained earnings differs from ERPNext's by {0}, because "
				"income or expense accounts are not mapped. The PSAK ID Mapping Control report lists them."
			).format(fmt_money(position.profit_or_loss_difference, currency=position.currency))
		)
	return "<br>".join(messages) or None
