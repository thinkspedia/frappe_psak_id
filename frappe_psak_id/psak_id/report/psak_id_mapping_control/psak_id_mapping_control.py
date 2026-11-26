# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

"""Mapping Control: what has to be fixed before the PSAK 118 statement can be sent for review.

One row per issue, each with the document to open to fix it. The checks themselves live in
``psak_id/checks.py`` so the Financial Statement runs the same ones. The periodicity is that of the
package the period is checked for: the statement of cash flows is only part of a quarterly or
yearly package, so only there its issues block (BR-42).
"""

import frappe
from frappe import _
from frappe.utils import fmt_money, formatdate, getdate

from frappe_psak_id.psak_id.cash_flow import NO_CASH_FLOW_LINE
from frappe_psak_id.psak_id.checks import (
	BALANCE_SHEET_DIFFERENCE,
	BLOCKING,
	CASH_DIFFERENCE,
	CASH_FLOW_PERIODICITIES,
	CONFLICTING_MAPPINGS,
	CURRENT,
	ERPNEXT_DIFFERENCE,
	INFORMATION,
	MONTHLY,
	NON_CASH_TRANSACTION,
	OTHER_ITEMS,
	RESTATED,
	UNMAPPED_BALANCE,
	WARNING,
	balance_sheet_difference_issues,
	balance_sheet_issues,
	cash_flow_issues,
	run_checks,
)
from frappe_psak_id.psak_id.statement import (
	DISABLED_LINE,
	NO_MATCHING_CONDITION,
	NOT_MAPPED,
	StatementError,
	check_read_access,
)


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	_validate(filters)
	result = run_checks(filters.company, filters.from_date, filters.to_date, filters.finance_book)
	result.issues += balance_sheet_issues(filters.company, filters.to_date, filters.finance_book)
	# The restated comparative is checked in the first PSAK 118 year, as for profit or loss
	result.issues += balance_sheet_difference_issues(
		filters.company, filters.to_date, filters.finance_book, restated=bool(result.restated)
	)
	result.issues += cash_flow_issues(
		filters.company, filters.from_date, filters.to_date, filters.finance_book, filters.periodicity
	)
	currency = result.current.currency
	labels = _line_labels()
	data = [_row(issue, currency, labels, index) for index, issue in enumerate(result.issues)]
	return _columns(currency), data, _message(data), None, _summary(result, data)


def _validate(filters):
	for fieldname, label in (
		("company", _("Company")),
		("from_date", _("From Date")),
		("to_date", _("To Date")),
	):
		if not filters.get(fieldname):
			frappe.throw(_("Choose the {0} to check.").format(label), frappe.MandatoryError)
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("The period starts after it ends."), StatementError)
	if filters.periodicity not in CASH_FLOW_PERIODICITIES:
		filters.periodicity = MONTHLY
	check_read_access(filters.company)


def _columns(currency) -> list[dict]:
	return [
		{"fieldname": "check_label", "label": _("Check"), "fieldtype": "Data", "width": 200},
		{"fieldname": "severity_label", "label": _("Severity"), "fieldtype": "Data", "width": 100},
		{"fieldname": "period_label", "label": _("Period"), "fieldtype": "Data", "width": 200},
		{"fieldname": "subject", "label": _("Account, Line or Voucher"), "fieldtype": "Data", "width": 240},
		{
			"fieldname": "amount",
			"label": _("Amount"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		},
		{"fieldname": "detail", "label": _("What To Do"), "fieldtype": "Data", "width": 360},
		{"fieldname": "fix", "label": _("Fix"), "fieldtype": "Data", "width": 150},
	]


def _row(issue, currency, labels, index) -> frappe._dict:
	line = labels.get(issue.report_line, issue.report_line)
	period = f"{formatdate(issue.from_date)} \u2013 {formatdate(issue.to_date)}"
	if issue.period == RESTATED:
		period = _("{0} (restated)").format(period)
	if issue.check in (UNMAPPED_BALANCE, BALANCE_SHEET_DIFFERENCE):
		period = _("At {0}").format(formatdate(issue.to_date))
		if issue.period == RESTATED:
			period = _("{0} (restated)").format(period)

	if issue.check == NOT_MAPPED:
		label = _("Unmapped account")
		detail = _("Has a balance but no mapping in force at the end of the period. Map it to a line.")
	elif issue.check == UNMAPPED_BALANCE:
		label = _("Unmapped balance sheet account")
		detail = _(
			"Has a balance at the end of the period but no mapping in force then. Map it to a financial "
			"position line."
		)
	elif issue.check == NO_MATCHING_CONDITION:
		label = _("No matching condition")
		detail = _(
			"Some entries match none of the account's conditional mappings. Add a mapping without a "
			"condition as the fallback."
		)
	elif issue.check == DISABLED_LINE:
		label = _("Mapped to a disabled line")
		detail = _("Mapped to {0}, which is disabled. Map the account to another line.").format(line)
	elif issue.check == CONFLICTING_MAPPINGS:
		label = _("Conflicting mappings")
		detail = _(
			"Mappings {0} match the same entries at priority {1} and name different lines. Give one of "
			"them a smaller priority number."
		).format(", ".join(issue.mappings), issue.priority)
	elif issue.check == OTHER_ITEMS:
		label = _("Other Items above threshold")
		detail = _(
			"Above the threshold of {0}. Explain it in a note of the statement, or map its accounts to "
			"more specific lines."
		).format(fmt_money(issue.threshold, currency=currency))
	elif issue.check == BALANCE_SHEET_DIFFERENCE:
		label = _("Difference to ERPNext Balance Sheet")
		detail = _(
			"The statement of financial position differs from ERPNext's Balance Sheet by this amount. "
			"Map the balance sheet accounts listed above. Profit or loss accounts left unmapped since "
			"the start of the fiscal year also leave their profit out of retained earnings."
		)
	elif issue.check == NO_CASH_FLOW_LINE and issue.balance_only:
		label = _("No cash flow line")
		detail = _(
			"Has a balance but its mapping has no cash flow line, so its movements would be left out of "
			"the statement of cash flows. Set the Cash Flow Line of the mapping."
		)
	elif issue.check == NO_CASH_FLOW_LINE:
		label = _("No cash flow line")
		detail = _(
			"Its cash effect in the period is left out of the statement of cash flows. Set the Cash Flow "
			"Line of its mapping."
		)
	elif issue.check == CASH_DIFFERENCE:
		label = _("Cash difference")
		detail = _(
			"Closing cash of the statement of cash flows differs from the balance of the accounts mapped "
			"to cash and cash equivalents. Set the missing cash flow lines listed above."
		)
	elif issue.check == NON_CASH_TRANSACTION:
		label = _("Non-cash transaction")
		detail = _(
			"Left out of investing and financing cash flows and disclosed as a non-cash transaction. "
			"Check that no cash was paid or received."
		)
	elif issue.check == ERPNEXT_DIFFERENCE:
		label = _("Difference to ERPNext Profit and Loss")
		detail = _(
			"The profit or loss differs from ERPNext's Profit and Loss by this amount. Map the accounts "
			"listed above; nothing is absorbed into a line."
		)
	else:
		label = _("Restatement difference")
		detail = _(
			"The restated prior year differs from its PSAK 201 profit or loss (ERPNext's Profit and "
			"Loss). Restating only reclassifies, so map the accounts listed for the restated period."
		)

	return frappe._dict(
		# Position in the report data, for the Fix link: the datatable may sort the rows
		row_index=index,
		check=issue.check,
		period=issue.period,
		check_label=label,
		severity=issue.severity,
		severity_label=_severity_label(issue.severity),
		period_label=period,
		subject=issue.account or issue.voucher_no or line or "",
		amount=issue.amount,
		currency=currency,
		detail=detail,
		account=issue.account,
		report_line=issue.report_line,
		voucher_type=issue.voucher_type,
		voucher_no=issue.voucher_no,
		from_date=str(issue.from_date),
		to_date=str(issue.to_date),
	)


def _severity_label(severity: str) -> str:
	return {BLOCKING: _("Blocking"), WARNING: _("Warning")}.get(severity, _("Information"))


def _line_labels() -> dict:
	# Disabled lines are not part of the statement, so their labels come from the master
	field = "label_id" if (frappe.local.lang or "").startswith("id") else "label_en"
	return {
		row.name: f"{row.name} {row[field] or row.label_en}"
		for row in frappe.get_all("PSAK ID Report Line", fields=["name", "label_id", "label_en"])
	}


def _summary(result, data) -> list[dict]:
	blocking = sum(1 for row in data if row.severity == BLOCKING)
	warnings = sum(1 for row in data if row.severity == WARNING)
	currency = result.current.currency
	summary = [
		{
			"label": _("Blocking Issues"),
			"value": blocking,
			"datatype": "Int",
			"indicator": "Red" if blocking else "Green",
		},
		{
			"label": _("Warnings"),
			"value": warnings,
			"datatype": "Int",
			"indicator": "Orange" if warnings else "Green",
		},
		{
			"label": _("Difference to ERPNext Profit and Loss"),
			"value": result.current.ledger_difference,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Red" if result.current.ledger_difference else "Green",
		},
	]
	for period, label in (
		(CURRENT, _("Difference to ERPNext Balance Sheet")),
		(RESTATED, _("Restated Balance Sheet Difference")),
	):
		if period == RESTATED and not result.restated:
			continue
		difference = sum(
			row.amount for row in data if row.check == BALANCE_SHEET_DIFFERENCE and row.period == period
		)
		summary.append(
			{
				"label": label,
				"value": difference,
				"datatype": "Currency",
				"currency": currency,
				"indicator": "Red" if difference else "Green",
			}
		)
	if result.restated:
		summary.append(
			{
				"label": _("Restatement Difference"),
				"value": result.restated.ledger_difference,
				"datatype": "Currency",
				"currency": currency,
				"indicator": "Red" if result.restated.ledger_difference else "Green",
			}
		)
	cash_difference = sum(row.amount for row in data if row.check == CASH_DIFFERENCE)
	summary.append(
		{
			"label": _("Cash Difference"),
			"value": cash_difference,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Red" if cash_difference else "Green",
		}
	)
	return summary


def _message(data) -> str | None:
	if not any(row.severity != INFORMATION for row in data):
		return _("No issues. The statement of this period can be sent for review.")
	if not any(row.severity == BLOCKING for row in data):
		return _("No blocking issues. Review the warnings before sending the statement for review.")
	return None
