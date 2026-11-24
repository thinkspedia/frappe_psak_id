# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

import frappe
from frappe.permissions import add_permission, update_permission_property


def has_app_permission() -> bool:
	"""Show the PSAK ID tile to users who can read a statement or a company policy."""
	return any(
		frappe.has_permission(doctype, "read")
		for doctype in ("PSAK ID Financial Statement", "PSAK ID Company Policy")
	)


AUDITOR = "PSAK ID - Auditor"


def grant_auditor_version_read() -> None:
	"""Let the auditor read the change history of PSAK ID documents (PRD-001 role matrix).

	Frappe grants Version to System Manager only. The rule is added the way Role Permissions
	Manager adds one, as a Custom DocPerm next to copies of the standard rules, so Frappe's own
	files stay unchanged. The hooks below limit it to PSAK ID documents the auditor can read.
	"""
	if not frappe.db.exists("Role", AUDITOR) or frappe.db.exists(
		"Custom DocPerm", {"parent": "Version", "role": AUDITOR, "permlevel": 0}
	):
		return
	add_permission("Version", AUDITOR, 0, "read")
	update_permission_property("Version", AUDITOR, 0, "report", 1)


def revoke_auditor_version_read() -> None:
	frappe.db.delete("Custom DocPerm", {"parent": "Version", "role": AUDITOR})
	frappe.clear_cache(doctype="Version")


def version_query_conditions(user: str | None = None) -> str:
	"""Version list: a user who reads Version only as the auditor sees the versions of the PSAK ID
	documents they can read."""
	user = user or frappe.session.user
	if _reads_every_version(user):
		return ""
	clauses = []
	for doctype in _psak_doctypes():
		if not frappe.has_permission(doctype, "read", user=user):
			continue
		names = frappe.get_list(doctype, pluck="name", user=user)
		if names:
			clauses.append(
				f"(`tabVersion`.`ref_doctype` = {frappe.db.escape(doctype)} and `tabVersion`.`docname` in "
				f"({', '.join(frappe.db.escape(name) for name in names)}))"
			)
	return f"({' or '.join(clauses)})" if clauses else "1=0"


def version_has_permission(doc, ptype=None, user=None, debug=False) -> bool:
	"""The same limit for one version. Returning True leaves every other user's access as it is:
	a permission hook can only take access away."""
	user = user or frappe.session.user
	if _reads_every_version(user):
		return True
	return doc.ref_doctype in _psak_doctypes() and bool(
		frappe.has_permission(doc.ref_doctype, "read", doc.docname, user=user)
	)


def _reads_every_version(user: str) -> bool:
	roles = {rule.role for rule in frappe.get_meta("Version").permissions if rule.read and not rule.permlevel}
	return bool((roles - {AUDITOR}) & set(frappe.get_roles(user)))


def _psak_doctypes() -> list[str]:
	return frappe.get_all("DocType", {"module": "PSAK ID", "istable": 0}, pluck="name")
