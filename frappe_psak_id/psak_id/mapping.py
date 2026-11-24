"""Apply a mapping template to a company (FR-04).

A template turns into ordinary PSAK ID Account Mappings, one per account the template matches,
each recording the template and its version. Accounts that already have a mapping are left as they
are, so applying a template again, or a second template, only fills the gaps.
"""

import re

import frappe
from frappe import _
from frappe.utils import getdate, strip_html

from frappe_psak_id.psak_id.statement import check_read_access


def pattern_regex(pattern: str) -> re.Pattern:
	"""``*`` matches any text, everything else literally, ignoring case and outer spaces."""
	parts = (re.escape(part) for part in (pattern or "").strip().split("*"))
	return re.compile(f"^{'.*'.join(parts)}$", re.IGNORECASE)


def match_row(account, rows: list):
	"""The first template row whose pattern matches the account, or None."""
	for row, regex in rows:
		if row.root_type and row.root_type != account.root_type:
			continue
		value = account.account_number if row.match_on == "Number" else account.account_name
		if value and regex.match(value.strip()):
			return row
	return None


@frappe.whitelist()
def apply_template(template: str, company: str, valid_from: str) -> dict:
	"""Map the company's unmapped income and expense accounts with the template.

	Returns the accounts mapped (``created``), already mapped (``skipped``), matched by no row
	(``unmatched``) and refused by the mapping's validation (``failed``, with the reason).
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
	accounts = frappe.get_all(
		"Account",
		filters={
			"company": company,
			"is_group": 0,
			"disabled": 0,
			"root_type": ("in", ("Income", "Expense")),
		},
		fields=["name", "account_name", "account_number", "root_type"],
		order_by="lft",
	)

	result = frappe._dict(created=[], skipped=[], unmatched=[], failed=[])
	for account in accounts:
		if account.name in mapped:
			result.skipped.append(account.name)
			continue
		row = match_row(account, rows)
		if not row:
			result.unmatched.append(account.name)
			continue

		expense_nature = row.expense_nature
		if account.root_type == "Expense" and categories.get(row.report_line) == "Operating":
			# Operating expenses need a nature for the by-nature note; the template may leave it
			# open for rows that also match income accounts
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
				"source_template": template.name,
				"source_template_version": template.template_version,
			}
		)
		frappe.db.savepoint("psak_id_apply_template")
		try:
			mapping.insert()
		except frappe.ValidationError as error:
			frappe.db.rollback(save_point="psak_id_apply_template")
			frappe.clear_messages()
			result.failed.append({"account": account.name, "reason": strip_html(str(error))})
			continue
		result.created.append(
			{"account": account.name, "report_line": row.report_line, "mapping": mapping.name}
		)
	return result
