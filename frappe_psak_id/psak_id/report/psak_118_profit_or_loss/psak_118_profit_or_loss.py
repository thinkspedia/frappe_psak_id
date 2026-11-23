# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

"""PSAK 118 statement of profit or loss as a Script Report.

The amounts come from the statement engine; this module arranges them in period and comparative
columns, scales them to the chosen unit and reports the check against ERPNext's Profit and Loss.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, add_years, escape_html, flt, formatdate, get_last_day, getdate

from frappe_psak_id.psak_id.statement import PROFIT_OR_LOSS_LINE, StatementError, compute_periods

UNITS = {"Full": 1, "Thousands": 1_000, "Millions": 1_000_000}
PERIOD_MONTHS = {"Monthly": 1, "Quarterly": 3, "Yearly": 12}
SAME_PERIOD_LAST_YEAR = "Same Period Last Year"
RESTATED_PRIOR_YEAR = "Restated Prior Year"
MAX_PERIODS = 24
UNMAPPED_LISTED = 5

# PSAK wording in both languages; the report language filter picks one or both, independent of
# the user's interface language
CATEGORY_LABELS = {
	"Operating": ("Operasi", "Operating"),
	"Investing": ("Investasi", "Investing"),
	"Financing": ("Pendanaan", "Financing"),
	"Income Tax": ("Pajak Penghasilan", "Income Tax"),
	"Discontinued Operations": ("Operasi yang Dihentikan", "Discontinued Operations"),
}


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	periods = _validate(filters)
	current = compute_periods(filters.company, periods, filters.cost_center, filters.finance_book)
	comparatives = _comparatives(filters, periods)

	columns = _columns(filters, periods, comparatives)
	data = _rows(filters, columns, current, comparatives)
	return columns, data, _message(current), None, _summary(current)


def get_periods(from_date, to_date, periodicity: str) -> list:
	"""Split the range into calendar-aligned periods of one, three or twelve months."""
	start, end = getdate(from_date), getdate(to_date)
	months = PERIOD_MONTHS[periodicity]
	periods = []
	while start <= end:
		period_end = min(getdate(get_last_day(add_months(start, months - 1))), end)
		periods.append((start, period_end))
		start = getdate(add_days(period_end, 1))
	return periods


def _validate(filters) -> list:
	"""Check the filters, fill in defaults and return the periods of the statement."""
	for fieldname, label in (
		("company", _("Company")),
		("from_date", _("From Date")),
		("to_date", _("To Date")),
	):
		if not filters.get(fieldname):
			frappe.throw(_("Choose the {0} of the statement.").format(label), frappe.MandatoryError)
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("The period starts after it ends."), StatementError)

	filters.periodicity = filters.periodicity if filters.periodicity in PERIOD_MONTHS else "Yearly"
	if filters.unit not in UNITS:
		filters.unit = frappe.db.get_value("PSAK ID Company Policy", filters.company, "default_unit")
		filters.unit = filters.unit if filters.unit in UNITS else "Full"
	filters.language = filters.language if filters.language in ("Indonesian", "English") else "Both"

	if frappe.db.exists("PSAK ID Company Policy", filters.company) and not frappe.has_permission(
		"PSAK ID Company Policy", "read", doc=filters.company
	):
		frappe.throw(
			_("You are not allowed to see the statements of {0}.").format(filters.company),
			frappe.PermissionError,
		)

	periods = get_periods(filters.from_date, filters.to_date, filters.periodicity)
	if len(periods) > MAX_PERIODS:
		frappe.throw(
			_(
				"The statement would have {0} period columns. Choose a shorter range or a longer periodicity."
			).format(len(periods))
		)
	return periods


def _comparatives(filters, periods):
	if filters.comparative not in (SAME_PERIOD_LAST_YEAR, RESTATED_PRIOR_YEAR):
		return None
	prior = [(getdate(add_years(start, -1)), getdate(add_years(end, -1))) for start, end in periods]
	# Restated: the prior year is classified with this year's mappings, as PSAK 118 requires for
	# the comparative of the first year it is applied
	mapping_date = periods[-1][1] if filters.comparative == RESTATED_PRIOR_YEAR else None
	return compute_periods(filters.company, prior, filters.cost_center, filters.finance_book, mapping_date)


def _columns(filters, periods, comparatives) -> list[dict]:
	columns = [{"fieldname": "line", "label": _("Line"), "fieldtype": "Data", "width": 420}]

	def amount_column(fieldname, label, start, end):
		return {
			"fieldname": fieldname,
			"label": label,
			"fieldtype": "Float",
			"precision": 0,
			"width": 150,
			"from_date": str(start),
			"to_date": str(end),
			# The print template reads the unit here: the filter may be empty (company default)
			"unit": filters.unit,
		}

	restated = filters.comparative == RESTATED_PRIOR_YEAR
	for index, (start, end) in enumerate(periods):
		columns.append(amount_column(f"p{index}", _period_label(start, end), start, end))
		if comparatives:
			prior = comparatives[index]
			label = _period_label(prior.from_date, prior.to_date)
			columns.append(
				amount_column(
					f"c{index}",
					_("{0} (Restated)").format(label) if restated else label,
					prior.from_date,
					prior.to_date,
				)
			)
	if len(periods) > 1:
		columns.append(amount_column("total", _("Total"), periods[0][0], periods[-1][1]))
		if comparatives:
			columns.append(
				amount_column(
					"total_c",
					_("Total (Restated)") if restated else _("Total Prior Year"),
					comparatives[0].from_date,
					comparatives[-1].to_date,
				)
			)
	return columns


def _period_label(start, end) -> str:
	if start.day == 1 and end == getdate(get_last_day(start)):
		return formatdate(start, "MMM yyyy")
	if (start.month, start.day, end.month, end.day) == (1, 1, 12, 31) and start.year == end.year:
		return str(start.year)
	return f"{formatdate(start, 'd MMM yyyy')} \u2013 {formatdate(end, 'd MMM yyyy')}"


def _rows(filters, columns, current, comparatives) -> list[dict]:
	"""One row per presented line; amounts are scaled for display only (BR-22)."""
	unit = UNITS[filters.unit]
	statements = {f"p{index}": statement for index, statement in enumerate(current)}
	statements.update({f"c{index}": statement for index, statement in enumerate(comparatives or [])})
	fieldnames = [column["fieldname"] for column in columns[1:]]
	show_headings = frappe.db.get_value("PSAK ID Company Policy", filters.company, "show_category_headings")

	lines_by_column = {
		fieldname: {line.line_code: line for line in statement.lines}
		for fieldname, statement in statements.items()
	}
	rows, heading = [], None
	for line in current[0].lines:
		presented = [lines_by_column[fieldname][line.line_code] for fieldname in statements]
		if all(column_line.hidden for column_line in presented):
			continue

		if show_headings and line.line_type == "Line" and line.category != heading:
			heading = line.category
			rows.append(_label_row(filters, *CATEGORY_LABELS[heading], line_type="Heading"))

		row = _label_row(filters, line.label_id, line.label_en, line_type=line.line_type)
		row.update(
			line_code=line.line_code,
			# Not "indent": that key turns the datatable into a collapsible tree
			indented=bool(show_headings and line.line_type == "Line"),
			is_profit_or_loss=line.line_code == PROFIT_OR_LOSS_LINE,
			accounts={},
		)
		if line.line_type != "Heading":
			for fieldname in fieldnames:
				amount, accounts = _column_amount(
					fieldname, line.line_code, lines_by_column, current, comparatives
				)
				row[fieldname] = flt(amount / unit, 0)
				row["accounts"][fieldname] = accounts
		rows.append(row)
	return rows


def _column_amount(fieldname, line_code, lines_by_column, current, comparatives):
	if fieldname in lines_by_column:
		line = lines_by_column[fieldname][line_code]
		return line.amount, line.accounts
	prefix = "p" if fieldname == "total" else "c"
	parts = [
		lines_by_column[f"{prefix}{index}"][line_code]
		for index in range(len(current if prefix == "p" else comparatives))
	]
	return sum(part.amount for part in parts), sorted(
		{account for part in parts for account in part.accounts}
	)


def _label_row(filters, label_id, label_en, line_type) -> frappe._dict:
	label_id, label_en = label_id or label_en, label_en or label_id
	if filters.language == "Indonesian":
		return frappe._dict(line=label_id, line_type=line_type)
	if filters.language == "English":
		return frappe._dict(line=label_en, line_type=line_type)
	return frappe._dict(line=label_id, label_alt=label_en, line_type=line_type)


def _summary(current) -> list[dict]:
	profit_or_loss = flt(sum(statement.profit_or_loss for statement in current), 2)
	ledger = flt(sum(statement.ledger_profit_or_loss for statement in current), 2)
	difference = flt(profit_or_loss - ledger, 2)
	currency = current[0].currency
	return [
		{
			"label": _("Profit or Loss (PSAK 118)"),
			"value": profit_or_loss,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Blue",
		},
		{
			"label": _("Net Profit in ERPNext Profit and Loss"),
			"value": ledger,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Blue",
		},
		{
			"label": _("Difference to ERPNext"),
			"value": difference,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Green" if not difference else "Red",
		},
	]


def _message(current) -> str | None:
	unmapped = {}
	for statement in current:
		for row in statement.unmapped:
			unmapped[row.account] = flt(unmapped.get(row.account)) + row.amount
	accounts = sorted(account for account, amount in unmapped.items() if flt(amount, 2))
	if not accounts:
		return None
	listed = ", ".join(escape_html(account) for account in accounts[:UNMAPPED_LISTED])
	if len(accounts) > UNMAPPED_LISTED:
		listed = _("{0} and {1} more").format(listed, len(accounts) - UNMAPPED_LISTED)
	return _(
		"{0} accounts with a balance are not mapped to a PSAK 118 line ({1}). They are left out of the "
		"statement, so it does not match ERPNext's Profit and Loss yet. Map them in PSAK ID Account Mapping."
	).format(len(accounts), listed)
