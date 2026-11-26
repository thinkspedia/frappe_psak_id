"""Apply a mapping template to a company (FR-04).

A template turns into ordinary PSAK ID Account Mappings, one per account the template matches,
each recording the template and its version. Accounts that already have a mapping are left as they
are, so applying a template again, or a second template, only fills the gaps.

A template applies to the root types it has rows for: a row without one is for income and expense
accounts, so a profit or loss template leaves the balance sheet alone.

Mappings made before the cash flow lines existed lack them. Applying a template with them can
complete those mappings instead of skipping them: from the chosen date, the account keeps its
lines and gains the cash flow lines of the template row that matches it.
"""

import re

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, strip_html

from frappe_psak_id.psak_id.statement import PROFIT_OR_LOSS_ROOT_TYPES, check_read_access

# What each kind of row compares its pattern with
_MATCH_FIELDS = {"Name": "account_name", "Number": "account_number", "Account Type": "account_type"}


def row_root_types(row) -> tuple:
	"""The root types of the accounts a template row applies to."""
	return (row.root_type,) if row.root_type else PROFIT_OR_LOSS_ROOT_TYPES


def pattern_regex(pattern: str) -> re.Pattern:
	"""``*`` matches any text, everything else literally, ignoring case and outer spaces."""
	parts = (re.escape(part) for part in (pattern or "").strip().split("*"))
	return re.compile(f"^{'.*'.join(parts)}$", re.IGNORECASE)


def match_row(account, rows: list):
	"""The first template row whose pattern matches the account, or None."""
	for row, regex in rows:
		if account.root_type not in row_root_types(row):
			continue
		value = account.get(_MATCH_FIELDS.get(row.match_on, "account_name"))
		if value and regex.match(value.strip()):
			return row
	return None


def final_until(company: str):
	"""End date of the company's last final statement, or None: mappings in force then stay as they
	are (BR-09)."""
	return frappe.db.get_value(
		"PSAK ID Financial Statement",
		{"company": company, "docstatus": 1},
		"to_date",
		order_by="to_date desc",
	)


@frappe.whitelist()
def default_valid_from(company: str):
	"""The date new mappings of the company start by default: the PSAK 118 adoption date, or the day
	after its last final statement when that is later, since earlier mappings are refused."""
	check_read_access(company)
	adoption_date = frappe.db.get_value("PSAK ID Company Policy", company, "adoption_date")
	final = final_until(company)
	dates = [getdate(date) for date in (adoption_date, add_days(final, 1) if final else None) if date]
	return max(dates) if dates else None


@frappe.whitelist()
def apply_template(template: str, company: str, valid_from: str, complete_cash_flow: bool = False) -> dict:
	"""Map the company's unmapped accounts of the root types the template has rows for.

	Returns the accounts mapped (``created``), already mapped (``skipped``), matched by no row
	(``unmatched``) and refused by the mapping's validation (``failed``, with the reason). With
	``complete_cash_flow``, mappings in force without a cash flow line get the template's
	(``completed``).
	"""
	frappe.has_permission("PSAK ID Account Mapping", "create", throw=True)
	template = frappe.get_doc("PSAK ID Mapping Template", template)
	template.check_permission("read")
	check_read_access(company)
	if not valid_from:
		frappe.throw(_("Choose the date the mappings are valid from."), frappe.MandatoryError)
	valid_from = getdate(valid_from)

	rows = [(row, pattern_regex(row.account_pattern)) for row in template.rows]
	categories = dict(frappe.get_all("PSAK ID Report Line", fields=["name", "category"], as_list=True))
	mapped = set(frappe.get_all("PSAK ID Account Mapping", filters={"company": company}, pluck="account"))
	missing_cash_flow = _mappings_without_cash_flow(company) if cint(complete_cash_flow) else {}
	accounts = frappe.get_all(
		"Account",
		filters={
			"company": company,
			"is_group": 0,
			"disabled": 0,
			"root_type": ("in", sorted({root for row, _regex in rows for root in row_root_types(row)})),
		},
		fields=["name", "account_name", "account_number", "account_type", "root_type"],
		order_by="lft",
	)

	result = frappe._dict(created=[], completed=[], skipped=[], unmatched=[], failed=[])
	for account in accounts:
		row = match_row(account, rows)
		if account.name in mapped:
			if row and row.cash_flow_line and account.name in missing_cash_flow:
				_complete_cash_flow(missing_cash_flow[account.name], row, valid_from, result)
			else:
				result.skipped.append(account.name)
			continue
		if not row:
			result.unmatched.append(account.name)
			continue
		_create_mapping(account, row, template, company, valid_from, categories, result)
	return result


def _create_mapping(account, row, template, company, valid_from, categories, result):
	expense_nature = row.expense_nature
	if account.root_type == "Expense" and categories.get(row.report_line) == "Operating":
		# Operating expenses need a nature for the by-nature note; the template may leave it open
		# for rows that also match income accounts
		expense_nature = expense_nature or "Other"
	mapping = frappe.get_doc(
		{
			"doctype": "PSAK ID Account Mapping",
			"company": company,
			"account": account.name,
			"report_line": row.report_line,
			"valid_from": valid_from,
			"priority": 10,
			"expense_nature": expense_nature,
			"is_final_tax": row.is_final_tax,
			"oci_line": row.oci_line if account.root_type == "Equity" else None,
			"cash_flow_line": row.cash_flow_line,
			"cash_flow_line_decrease": row.cash_flow_line_decrease,
			"source_template": template.name,
			"source_template_version": template.template_version,
		}
	)
	if _save(mapping, account.name, result):
		result.created.append(
			{"account": account.name, "report_line": row.report_line, "mapping": mapping.name}
		)


def _mappings_without_cash_flow(company: str) -> dict[str, list[str]]:
	"""The latest mapping of each account, condition and priority of the company, by account, when
	it has no cash flow line: the mappings in force from now on that the statement needs one on."""
	latest = {}
	for row in frappe.get_all(
		"PSAK ID Account Mapping",
		filters={"company": company},
		fields=[
			"name",
			"account",
			"priority",
			"condition_type",
			"condition_doctype",
			"condition_value",
			"cash_flow_line",
		],
		order_by="valid_from desc",
	):
		key = (row.account, row.condition_type, row.condition_doctype, row.condition_value, row.priority)
		latest.setdefault(key, row)
	missing = {}
	for row in latest.values():
		if not row.cash_flow_line:
			missing.setdefault(row.account, []).append(row.name)
	return missing


def _complete_cash_flow(mapping_names: list[str], row, valid_from, result):
	"""Give each mapping the template row's cash flow lines from ``valid_from``: a new mapping that
	copies one in force before then, so the statements up to that date keep their classification
	(BR-09), or the mapping itself when it starts on or after that date."""
	for name in mapping_names:
		current = frappe.get_doc("PSAK ID Account Mapping", name)
		mapping = current if getdate(current.valid_from) >= valid_from else frappe.copy_doc(current)
		mapping.valid_from = max(getdate(current.valid_from), valid_from)
		mapping.cash_flow_line = row.cash_flow_line
		mapping.cash_flow_line_decrease = row.cash_flow_line_decrease
		if _save(mapping, current.account, result):
			result.completed.append(
				{"account": current.account, "cash_flow_line": row.cash_flow_line, "mapping": mapping.name}
			)


def _save(mapping, account: str, result) -> bool:
	"""Save the mapping, or record why its validation refused it."""
	frappe.db.savepoint("psak_id_apply_template")
	try:
		mapping.insert() if mapping.is_new() else mapping.save()
	except frappe.ValidationError as error:
		frappe.db.rollback(save_point="psak_id_apply_template")
		frappe.clear_messages()
		result.failed.append({"account": account, "reason": strip_html(str(error))})
		return False
	return True
