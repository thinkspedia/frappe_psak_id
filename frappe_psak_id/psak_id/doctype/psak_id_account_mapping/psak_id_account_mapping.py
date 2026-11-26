# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import formatdate, getdate

from frappe_psak_id.psak_id.mapping import final_until as get_final_until
from frappe_psak_id.psak_id.report_lines import (
	CASH_FLOW,
	FINANCIAL_POSITION,
	OTHER_COMPREHENSIVE_INCOME,
	PROFIT_OR_LOSS,
)

# Condition types whose value is always a document of the same type
_FIXED_CONDITION_DOCTYPES = {"Cost Center": "Cost Center", "Project": "Project"}

# The statement an account's root type is presented in, and the category its line must have there
_ROOT_TYPE_LINES = {
	"Income": (PROFIT_OR_LOSS, None),
	"Expense": (PROFIT_OR_LOSS, None),
	"Asset": (FINANCIAL_POSITION, "Asset"),
	"Liability": (FINANCIAL_POSITION, "Liability"),
	"Equity": (FINANCIAL_POSITION, "Equity"),
}
# The financial position line of cash and cash equivalents; cash and bank accounts belong there
_CASH_LINE = "FP-CA-CASH"

# Fields that decide how GL Entries are classified; notes and the template source do not
_CLASSIFICATION_FIELDS = (
	"company",
	"account",
	"report_line",
	"valid_from",
	"priority",
	"condition_type",
	"accounting_dimension",
	"party_type",
	"condition_doctype",
	"condition_value",
	"expense_nature",
	"is_final_tax",
	"equity_component",
	"oci_line",
	"cash_flow_line",
	"cash_flow_line_decrease",
)
_CASH_FLOW_FIELDS = ("cash_flow_line", "cash_flow_line_decrease")


class PSAKIDAccountMapping(Document):
	def validate(self):
		self._validate_account()
		self._validate_report_line()
		self._validate_equity_fields()
		self._validate_cash_flow_lines()
		self._set_condition_doctype()
		self._validate_condition_value()
		self._validate_expense_nature()
		self._validate_final_tax()
		self._validate_unique_rule()
		self._validate_not_in_final_period()

	def on_trash(self):
		self._validate_not_in_final_period(deleting=True)

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
		if account.root_type not in _ROOT_TYPE_LINES:
			frappe.throw(_("{0} has no root type. Set it on the account first.").format(self.account))
		self.root_type = account.root_type

	def _validate_report_line(self):
		statement, category = _ROOT_TYPE_LINES[self.root_type]
		line = _get_line(self.report_line)
		if line.line_type != "Line":
			frappe.throw(
				_("Map accounts to a line, not to a heading or subtotal. {0} is a {1}.").format(
					self.report_line, _(line.line_type)
				)
			)
		if line.statement != statement or (category and line.category != category):
			frappe.throw(
				_("{0} is an income or expense account. Map it to a profit or loss line.").format(
					self.account
				)
				if statement == PROFIT_OR_LOSS
				else _("{0} is a {1} account. Map it to a financial position line of category {1}.").format(
					self.account, _(category)
				)
			)
		if line.disabled:
			frappe.throw(_("Report line {0} is disabled.").format(self.report_line))
		self.category = line.category
		self._warn_cash_account()

	def _warn_cash_account(self):
		if self.root_type != "Asset":
			return
		account_type = frappe.db.get_value("Account", self.account, "account_type")
		is_cash = account_type in ("Cash", "Bank")
		if is_cash != (self.report_line == _CASH_LINE):
			# A warning, not an error: deposits held in a bank account may not be cash equivalents
			frappe.msgprint(
				_(
					"{0} is a {1} account but is mapped to {2}. Cash and cash equivalents are presented in "
					"{3}; map it elsewhere only if it holds deposits that are not cash equivalents."
				).format(self.account, _(account_type), self.report_line, _CASH_LINE)
				if is_cash
				else _(
					"{0} is mapped to {1} but is not a cash or bank account. The statement of cash flows "
					"takes the cash balance from this line."
				).format(self.account, _CASH_LINE),
				title=_("Cash and cash equivalents"),
				indicator="orange",
				alert=True,
			)

	def _validate_equity_fields(self):
		if self.root_type != "Equity":
			self.equity_component = self.oci_line = None
			return
		# The column of the statement of changes in equity; most equity accounts sit in the
		# component of their own line
		self.equity_component = self.equity_component or self.report_line
		component = _get_line(self.equity_component)
		if (
			component.line_type != "Line"
			or component.statement != FINANCIAL_POSITION
			or component.category != "Equity"
		):
			frappe.throw(
				_("The equity component must be an equity line of the {0}; {1} is not.").format(
					_(FINANCIAL_POSITION), self.equity_component
				)
			)
		if not self.oci_line:
			return
		oci_line = _get_line(self.oci_line)
		if oci_line.line_type != "Line" or oci_line.statement != OTHER_COMPREHENSIVE_INCOME:
			frappe.throw(
				_("The OCI line must be a line of {0}; {1} is not.").format(
					_(OTHER_COMPREHENSIVE_INCOME), self.oci_line
				)
			)
		if oci_line.disabled:
			frappe.throw(_("Report line {0} is disabled.").format(self.oci_line))

	def _validate_cash_flow_lines(self):
		if self.root_type in ("Income", "Expense") or self.cash_flow_line_decrease == self.cash_flow_line:
			self.cash_flow_line_decrease = None
		if self.report_line == _CASH_LINE and (self.cash_flow_line or self.cash_flow_line_decrease):
			frappe.throw(
				_(
					"{0} is mapped to {1}, the cash whose flows the statement presents. Leave its cash flow "
					"lines empty."
				).format(self.account, _CASH_LINE)
			)
		if self.cash_flow_line_decrease and not self.cash_flow_line:
			frappe.throw(
				_("Choose the Cash Flow Line before a separate line for decreases."), frappe.MandatoryError
			)
		for field in _CASH_FLOW_FIELDS:
			if self.get(field):
				_validate_cash_flow_line(self.get(field))

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
		if self.root_type not in ("Income", "Expense"):
			self.is_final_tax = 0
		elif self.is_final_tax and self.category == "Income Tax":
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

	def _validate_not_in_final_period(self, deleting=False):
		"""Final statements keep their classification: a mapping in force on or before the end of the
		last final period is neither added, changed nor deleted (BR-09)."""
		previous = None if deleting else self.get_doc_before_save()
		if previous and not any(self.has_value_changed(field) for field in _CLASSIFICATION_FIELDS):
			return
		final_until = get_final_until(self.company)
		if not final_until:
			return
		dates = [self.valid_from] + ([previous.valid_from] if previous else [])
		if min(getdate(date) for date in dates) <= getdate(final_until):
			frappe.throw(
				_(
					"The statements of {0} are final up to {1}, and this mapping is in force then. Set Valid "
					"From after {1} to change the mapping from that date, or reopen the final statement."
				).format(self.company, formatdate(final_until)),
				title=_("Final period"),
			)


def _validate_cash_flow_line(name: str):
	line = _get_line(name)
	# Lines taken from another statement and those outside the three activities (opening cash,
	# effect of exchange rates) are computed, not mapped
	if line.line_type != "Line" or line.statement != CASH_FLOW or not line.category or line.source_line:
		frappe.throw(
			_("Map accounts to an operating, investing or financing line of the {0}; {1} is not one.").format(
				_(CASH_FLOW), name
			)
		)
	if line.disabled:
		frappe.throw(_("Report line {0} is disabled.").format(name))


def _get_line(name: str) -> frappe._dict:
	line = frappe.db.get_value(
		"PSAK ID Report Line",
		name,
		["line_type", "statement", "disabled", "category", "source_line"],
		as_dict=True,
	)
	if not line:
		frappe.throw(_("Report line {0} does not exist.").format(name), frappe.LinkValidationError)
	return line
