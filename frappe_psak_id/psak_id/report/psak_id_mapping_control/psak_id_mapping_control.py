# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

"""Mapping Control: what has to be fixed before the PSAK 118 statement can be sent for review.

One row per issue, each with the document to open to fix it. The checks themselves live in
``psak_id/checks.py`` so the Financial Statement runs the same ones.
"""

import frappe
from frappe import _
from frappe.utils import fmt_money, formatdate, getdate

from frappe_psak_id.psak_id.checks import (
	BLOCKING,
	CONFLICTING_MAPPINGS,
	ERPNEXT_DIFFERENCE,
	OTHER_ITEMS,
	RESTATED,
	UNMAPPED_BALANCE,
	balance_sheet_issues,
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
	check_read_access(filters.company)


def _columns(currency) -> list[dict]:
	return [
		{"fieldname": "check_label", "label": _("Check"), "fieldtype": "Data", "width": 200},
		{"fieldname": "severity_label", "label": _("Severity"), "fieldtype": "Data", "width": 100},
		{"fieldname": "period_label", "label": _("Period"), "fieldtype": "Data", "width": 200},
		{"fieldname": "subject", "label": _("Account or Line"), "fieldtype": "Data", "width": 240},
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
	if issue.check == UNMAPPED_BALANCE:
		period = _("At {0}").format(formatdate(issue.to_date))

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
	elif issue.check == ERPNEXT_DIFFERENCE:
		label = _("Difference to ERPNext")
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
		check_label=label,
		severity=issue.severity,
		severity_label=_("Blocking") if issue.severity == BLOCKING else _("Warning"),
		period_label=period,
		subject=issue.account or line or "",
		amount=issue.amount,
		currency=currency,
		detail=detail,
		account=issue.account,
		report_line=issue.report_line,
		from_date=str(issue.from_date),
		to_date=str(issue.to_date),
	)


def _line_labels() -> dict:
	# Disabled lines are not part of the statement, so their labels come from the master
	field = "label_id" if (frappe.local.lang or "").startswith("id") else "label_en"
	return {
		row.name: f"{row.name} {row[field] or row.label_en}"
		for row in frappe.get_all("PSAK ID Report Line", fields=["name", "label_id", "label_en"])
	}


def _summary(result, data) -> list[dict]:
	blocking = sum(1 for row in data if row.severity == BLOCKING)
	warnings = len(data) - blocking
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
			"label": _("Difference to ERPNext"),
			"value": result.current.ledger_difference,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Red" if result.current.ledger_difference else "Green",
		},
	]
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
	return summary


def _message(data) -> str | None:
	if not data:
		return _("No issues. The statement of this period can be sent for review.")
	if not any(row.severity == BLOCKING for row in data):
		return _("No blocking issues. Review the warnings before sending the statement for review.")
	return None
