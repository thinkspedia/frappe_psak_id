# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappe_psak_id.psak_id.report_lines import (
	CASH_FLOW,
	FINANCIAL_POSITION,
	OTHER_COMPREHENSIVE_INCOME,
	PROFIT_OR_LOSS,
)

BALANCE_SHEET_ROOT_TYPES = ("Asset", "Liability", "Equity")
CASH_FLOW_FIELDS = ("cash_flow_line", "cash_flow_line_decrease")
CASH_LINE = "FP-CA-CASH"


class PSAKIDMappingTemplate(Document):
	def validate(self):
		codes = {
			row.get(field)
			for row in self.rows
			for field in ("report_line", "oci_line", *CASH_FLOW_FIELDS)
			if row.get(field)
		}
		lines = {
			line.name: line
			for line in frappe.get_all(
				"PSAK ID Report Line",
				filters={"name": ("in", list(codes))},
				fields=["name", "line_type", "statement", "disabled", "category", "source_line"],
			)
		}
		account_types = set(frappe.get_meta("Account").get_options("account_type").split("\n")) - {""}
		seen = {}
		for row in self.rows:
			row.account_pattern = (row.account_pattern or "").strip()
			if not row.account_pattern:
				frappe.throw(_("Row {0}: enter the account pattern.").format(row.idx), frappe.MandatoryError)
			if (
				row.match_on == "Account Type"
				and "*" not in row.account_pattern
				and row.account_pattern not in account_types
			):
				frappe.throw(_("Row {0}: {1} is not an account type.").format(row.idx, row.account_pattern))

			line = lines.get(row.report_line)
			self._validate_line(row, line)
			if line.disabled:
				frappe.throw(_("Row {0}: report line {1} is disabled.").format(row.idx, row.report_line))
			if row.is_final_tax and line.category == "Income Tax":
				frappe.throw(
					_(
						"Row {0}: final income tax (PPh final) is not income tax under PSAK 212. Map it to the "
						"category of the income it is levied on."
					).format(row.idx)
				)
			self._validate_oci_line(row, lines.get(row.oci_line))
			self._validate_cash_flow_lines(row, lines)

			key = (row.root_type or "", row.match_on, row.account_pattern.lower())
			if key in seen:
				frappe.throw(
					_("Row {0} repeats the pattern of row {1}; only the first one would ever match.").format(
						row.idx, seen[key]
					)
				)
			seen[key] = row.idx

	@staticmethod
	def _validate_line(row, line):
		if not line or line.line_type != "Line" or line.statement not in (PROFIT_OR_LOSS, FINANCIAL_POSITION):
			frappe.throw(
				_(
					"Row {0}: map to a line of the profit or loss or the financial position, not to a heading "
					"or subtotal."
				).format(row.idx)
			)
		if row.root_type in BALANCE_SHEET_ROOT_TYPES:
			# The same check the account mapping makes, so a template never proposes a refused mapping
			if line.statement != FINANCIAL_POSITION or line.category != row.root_type:
				frappe.throw(
					_("Row {0}: {1} accounts map to a financial position line of category {1}.").format(
						row.idx, _(row.root_type)
					)
				)
			row.expense_nature, row.is_final_tax = None, 0
		elif line.statement != PROFIT_OR_LOSS:
			frappe.throw(
				_(
					"Row {0}: a financial position line needs Applies To set to Asset, Liability or Equity."
				).format(row.idx)
			)

	@staticmethod
	def _validate_oci_line(row, oci_line):
		if not row.oci_line:
			return
		if row.root_type != "Equity":
			frappe.throw(_("Row {0}: only equity accounts have an OCI line.").format(row.idx))
		if not oci_line or oci_line.line_type != "Line" or oci_line.statement != OTHER_COMPREHENSIVE_INCOME:
			frappe.throw(
				_("Row {0}: the OCI line must be a line of {1}.").format(
					row.idx, _(OTHER_COMPREHENSIVE_INCOME)
				)
			)
		if oci_line.disabled:
			frappe.throw(_("Row {0}: report line {1} is disabled.").format(row.idx, row.oci_line))

	@staticmethod
	def _validate_cash_flow_lines(row, lines):
		"""The same checks the account mapping makes on its cash flow lines."""
		if row.root_type not in BALANCE_SHEET_ROOT_TYPES or row.cash_flow_line_decrease == row.cash_flow_line:
			row.cash_flow_line_decrease = None
		if row.report_line == CASH_LINE and (row.cash_flow_line or row.cash_flow_line_decrease):
			frappe.throw(
				_(
					"Row {0}: accounts of {1} are the cash the statement presents; leave the cash flow lines empty."
				).format(row.idx, CASH_LINE)
			)
		if row.cash_flow_line_decrease and not row.cash_flow_line:
			frappe.throw(
				_("Row {0}: choose the Cash Flow Line before a separate line for decreases.").format(row.idx),
				frappe.MandatoryError,
			)
		for field in CASH_FLOW_FIELDS:
			code = row.get(field)
			if not code:
				continue
			line = lines.get(code)
			if (
				not line
				or line.line_type != "Line"
				or line.statement != CASH_FLOW
				or not line.category
				or line.source_line
			):
				frappe.throw(
					_(
						"Row {0}: map to an operating, investing or financing line of the {1}; {2} is not one."
					).format(row.idx, _(CASH_FLOW), code)
				)
			if line.disabled:
				frappe.throw(_("Row {0}: report line {1} is disabled.").format(row.idx, code))
