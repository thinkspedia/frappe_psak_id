# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

"""Number cards of the PSAK 118 workspace that a document count cannot express.

The workspace must open in a second, so a card only counts rows: it never reads GL Entries or
computes a statement.
"""

import frappe
from frappe.utils import today


@frappe.whitelist()
def unmapped_accounts(filters=None) -> int:
	"""Income and expense accounts of the PSAK ID companies the user can see that have no mapping
	in force today (FR-05 lists the ones with a balance)."""
	frappe.has_permission("PSAK ID Account Mapping", "read", throw=True)
	companies = frappe.get_list("PSAK ID Company Policy", pluck="name")
	if not companies:
		return 0

	account = frappe.qb.DocType("Account")
	mapping = frappe.qb.DocType("PSAK ID Account Mapping")
	mapped = (
		frappe.qb.from_(mapping)
		.select(mapping.account)
		.where(mapping.company.isin(companies))
		.where(mapping.valid_from <= today())
	)
	return (
		frappe.qb.from_(account)
		.select(frappe.query_builder.functions.Count("*"))
		.where(account.company.isin(companies))
		.where(account.root_type.isin(["Income", "Expense"]))
		.where(account.is_group == 0)
		.where(account.disabled == 0)
		.where(account.name.notin(mapped))
		.run()[0][0]
	)
