# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class PSAKIDCompanyPolicy(Document):
	def validate(self):
		self._validate_other_items_threshold()
		self._validate_financing_choice()

	def _validate_other_items_threshold(self):
		percent = flt(self.other_items_threshold_percent)
		amount = flt(self.other_items_threshold_amount)
		if percent < 0 or amount < 0:
			frappe.throw(_("The Other Items threshold cannot be negative."))
		if percent > 100:
			frappe.throw(_("The Other Items threshold cannot be more than 100% of revenue."))

	def _validate_financing_choice(self):
		# PSAK 118 offers this choice only to entities whose main business is financing customers
		if self.financing_all_operating and not self.main_business_financing:
			frappe.throw(
				_(
					"All Financing Expenses in Operating can only be ticked when customer financing is a main "
					"business activity of the company. Tick Main Business: Customer Financing first."
				)
			)
