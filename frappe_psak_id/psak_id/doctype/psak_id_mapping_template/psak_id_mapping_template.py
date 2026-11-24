# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PSAKIDMappingTemplate(Document):
	def validate(self):
		lines = {
			line.name: line
			for line in frappe.get_all(
				"PSAK ID Report Line",
				filters={"name": ("in", list({row.report_line for row in self.rows}))},
				fields=["name", "line_type", "statement", "disabled", "category"],
			)
		}
		seen = {}
		for row in self.rows:
			row.account_pattern = (row.account_pattern or "").strip()
			if not row.account_pattern:
				frappe.throw(_("Row {0}: enter the account pattern.").format(row.idx), frappe.MandatoryError)

			line = lines.get(row.report_line)
			if not line or line.line_type != "Line" or line.statement != "Profit or Loss":
				frappe.throw(
					_("Row {0}: map to a profit or loss line, not to a heading or subtotal.").format(row.idx)
				)
			if line.disabled:
				frappe.throw(_("Row {0}: report line {1} is disabled.").format(row.idx, row.report_line))
			if row.is_final_tax and line.category == "Income Tax":
				frappe.throw(
					_(
						"Row {0}: final income tax (PPh final) is not income tax under PSAK 212. Map it to the "
						"category of the income it is levied on."
					).format(row.idx)
				)

			key = (row.root_type or "", row.match_on, row.account_pattern.lower())
			if key in seen:
				frappe.throw(
					_("Row {0} repeats the pattern of row {1}; only the first one would ever match.").format(
						row.idx, seen[key]
					)
				)
			seen[key] = row.idx
