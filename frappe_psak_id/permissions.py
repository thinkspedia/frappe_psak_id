# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

import frappe


def has_app_permission() -> bool:
	"""Show the PSAK ID tile to users who can read a statement or a company policy."""
	return any(
		frappe.has_permission(doctype, "read")
		for doctype in ("PSAK ID Financial Statement", "PSAK ID Company Policy")
	)
