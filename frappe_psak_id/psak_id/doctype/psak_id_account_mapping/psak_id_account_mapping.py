# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# Condition types whose value is always a document of the same type
_FIXED_CONDITION_DOCTYPES = {"Cost Center": "Cost Center", "Project": "Project"}


class PSAKIDAccountMapping(Document):
	def validate(self):
		self._validate_account()
		self._validate_report_line()
		self._set_condition_doctype()
		self._validate_condition_value()
		self._validate_expense_nature()
		self._validate_final_tax()
		self._validate_unique_rule()

	def _validate_account(self):
		account = frappe.db.get_value(
			"Account", self.account, ["company", "root_type", "is_group"], as_dict=True
		)
		if not account:
			frappe.throw(_("Account {0} does not exist.").format(self.account), frappe.LinkValidationError)
		if account.company != self.company:
			frappe.throw(_("Account {0} does not belong to {1}.").format(self.account, self.company))
		if account.is_group:
			frappe.throw(_("{0} is a group account. Map the accounts under it instead.").format(self.account))
		if account.root_type not in ("Income", "Expense"):
			frappe.throw(
				_(
					"Only income and expense accounts appear in the statement of profit or loss; {0} is {1}."
				).format(self.account, _(account.root_type))
			)
		self.root_type = account.root_type

	def _validate_report_line(self):
		line = frappe.db.get_value(
			"PSAK ID Report Line",
			self.report_line,
			["line_type", "statement", "disabled", "category"],
			as_dict=True,
		)
		if not line:
			frappe.throw(
				_("Report line {0} does not exist.").format(self.report_line), frappe.LinkValidationError
			)
		if line.line_type != "Line" or line.statement != "Profit or Loss":
			frappe.throw(
				_(
					"Map accounts to a profit or loss line, not to a heading or subtotal. {0} is a {1}."
				).format(self.report_line, _(line.line_type))
			)
		if line.disabled:
			frappe.throw(_("Report line {0} is disabled.").format(self.report_line))
		self.category = line.category

	def _set_condition_doctype(self):
		if not self.condition_type:
			self.accounting_dimension = self.party_type = self.condition_value = None
			self.condition_doctype = None
			return
		if self.condition_type in _FIXED_CONDITION_DOCTYPES:
			self.condition_doctype = _FIXED_CONDITION_DOCTYPES[self.condition_type]
		elif self.condition_type == "Party":
			if not self.party_type:
				frappe.throw(_("Choose the party type of the condition."), frappe.MandatoryError)
			self.condition_doctype = self.party_type
		else:
			if not self.accounting_dimension:
				frappe.throw(_("Choose the accounting dimension of the condition."), frappe.MandatoryError)
			self.condition_doctype = frappe.db.get_value(
				"Accounting Dimension", self.accounting_dimension, "document_type"
			)
		if self.condition_type != "Party":
			self.party_type = None
		if self.condition_type != "Accounting Dimension":
			self.accounting_dimension = None

	def _validate_condition_value(self):
		if not self.condition_type:
			return
		if not self.condition_value:
			frappe.throw(_("Choose the {0} the condition applies to.").format(_(self.condition_doctype)))
		if self.condition_type == "Cost Center":
			company = frappe.db.get_value("Cost Center", self.condition_value, "company")
			if company != self.company:
				frappe.throw(
					_("Cost center {0} does not belong to {1}.").format(self.condition_value, self.company)
				)

	def _validate_expense_nature(self):
		if self.root_type != "Expense":
			self.expense_nature = None
		elif self.category == "Operating" and not self.expense_nature:
			frappe.throw(
				_(
					"Choose the expense nature. Operating expenses are also disclosed by nature (depreciation, "
					"employee benefits, ...)."
				),
				frappe.MandatoryError,
			)

	def _validate_final_tax(self):
		if self.is_final_tax and self.category == "Income Tax":
			frappe.throw(
				_(
					"Final income tax (PPh final) is not income tax under PSAK 212. Map it to the category of "
					"the income it is levied on, for example Final tax expense in Operating."
				)
			)

	def _validate_unique_rule(self):
		filters = {
			"name": ("!=", self.name),
			"company": self.company,
			"account": self.account,
			"priority": self.priority,
			"valid_from": self.valid_from,
		}
		for field in ("condition_type", "condition_doctype", "condition_value"):
			filters[field] = self.get(field) or ("is", "not set")
		duplicate = frappe.db.exists(self.doctype, filters)
		if duplicate:
			frappe.throw(
				_(
					"{0} already maps this account with the same condition, priority and start date. Edit that "
					"mapping or use another priority."
				).format(duplicate),
				frappe.DuplicateEntryError,
			)
