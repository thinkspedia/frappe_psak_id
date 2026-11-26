# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet

from frappe_psak_id.psak_id.report_lines import (
	CLASSIFIED_CATEGORIES,
	FINANCIAL_POSITION,
	NEVER_OPERATING_LINES,
	OPTIONAL_CATEGORY_STATEMENTS,
	OTHER_COMPREHENSIVE_INCOME,
	PROFIT_OR_LOSS,
	STATEMENT_CATEGORIES,
	find_cycle,
	parse_subtotal_formula,
)


class PSAKIDReportLine(NestedSet):
	def validate(self):
		self._clear_fields_of_other_line_types()
		self._validate_mandatory_flag()
		self._validate_follows_operating()
		if self.line_type == "Line":
			self._validate_category()
			self._validate_source_line()
		if self.line_type == "Subtotal":
			self._validate_subtotal_formula()

	def on_trash(self):
		if self.mandatory:
			frappe.throw(_("{0} is required by PSAK 118 and cannot be deleted.").format(self.label_en))
		self._check_not_used_in_formulas()
		super().on_trash()

	def _clear_fields_of_other_line_types(self):
		if self.line_type != "Line" or not STATEMENT_CATEGORIES.get(self.statement, ()):
			self.category = None
		if self.line_type != "Line":
			self.is_other_items = 0
		if self.line_type != "Line" or self.statement != PROFIT_OR_LOSS:
			self.follows_operating = 0
		if self.statement != FINANCIAL_POSITION or self.category not in CLASSIFIED_CATEGORIES:
			self.classification = None
		if self.line_type != "Line" or self.statement != OTHER_COMPREHENSIVE_INCOME:
			self.reclassifiable = 0
		if self.line_type != "Subtotal":
			self.subtotal_formula = None
		if self.line_type != "Line":
			self.source_line = None

	def _validate_category(self):
		categories = STATEMENT_CATEGORIES.get(self.statement, ())
		if not categories or (not self.category and self.statement in OPTIONAL_CATEGORY_STATEMENTS):
			return
		if not self.category:
			frappe.throw(_("Choose the PSAK 118 category of this line."), frappe.MandatoryError)
		if self.category not in categories:
			frappe.throw(
				_("A {0} line belongs to one of these categories: {1}.").format(
					_(self.statement), ", ".join(_(category) for category in categories)
				)
			)
		if self.category in CLASSIFIED_CATEGORIES and not self.classification:
			frappe.throw(
				_("Choose whether this {0} line is current or non-current.").format(_(self.category)),
				frappe.MandatoryError,
			)

	def _validate_source_line(self):
		if not self.source_line:
			return
		if self.source_line == self.line_code:
			frappe.throw(_("A line cannot take its amount from itself."))
		source = frappe.db.get_value(self.doctype, self.source_line, ["statement", "line_type"], as_dict=True)
		if not source:
			return
		if source.statement == self.statement:
			frappe.throw(
				_("The source line {0} must belong to another statement than {1}.").format(
					self.source_line, _(self.statement)
				)
			)
		if source.line_type == "Heading":
			frappe.throw(_("{0} is a heading and has no amount to add.").format(self.source_line))

	def _validate_mandatory_flag(self):
		# Only the standard lines shipped with the app carry the flag, and it can never be removed
		installing = frappe.flags.psak_id_installing_standard_lines
		was_mandatory = not self.is_new() and frappe.db.get_value(self.doctype, self.name, "mandatory")
		if was_mandatory:
			self.mandatory = 1
			before = self.get_doc_before_save()
			if before and (
				before.line_type != self.line_type
				or (before.subtotal_formula or "").split() != (self.subtotal_formula or "").split()
			):
				frappe.throw(
					_("{0} is required by PSAK 118; its type and formula cannot be changed.").format(
						self.label_en
					)
				)
		elif self.mandatory and not installing:
			self.mandatory = 0
		if self.mandatory and self.disabled:
			frappe.throw(_("{0} is required by PSAK 118 and cannot be disabled.").format(self.label_en))

	def _validate_follows_operating(self):
		if not self.follows_operating:
			return
		if self.category not in ("Investing", "Financing"):
			frappe.throw(_("Only Investing or Financing lines can follow Operating."))
		if self.line_code in NEVER_OPERATING_LINES:
			frappe.throw(
				_(
					"The share of profit of associates and joint ventures is always Investing, even when "
					"investing is a main business activity."
				)
			)

	def _validate_subtotal_formula(self):
		terms = parse_subtotal_formula(self.subtotal_formula)
		lines = {
			row.name: row
			for row in frappe.get_all(
				self.doctype,
				fields=["name", "statement", "line_type", "subtotal_formula"],
			)
		}
		for term in terms:
			if term.kind == "category":
				if term.ref not in STATEMENT_CATEGORIES.get(self.statement, ()):
					frappe.throw(
						_("{0} is not a category of the {1} statement.").format(
							_(term.ref), _(self.statement)
						)
					)
				continue
			if term.ref == self.line_code:
				frappe.throw(_("A subtotal cannot refer to itself."))
			referenced = lines.get(term.ref)
			# Another statement's subtotal may be carried over, as profit or loss is into total
			# comprehensive income; its separate lines may not
			if not referenced or (
				referenced.statement != self.statement and referenced.line_type != "Subtotal"
			):
				frappe.throw(
					_(
						"The subtotal formula refers to {0}, which is not a {1} line or a subtotal of "
						"another statement."
					).format(term.ref, _(self.statement))
				)
			if referenced.line_type == "Heading":
				frappe.throw(_("{0} is a heading and has no amount to add.").format(term.ref))

		formulas = {
			code: parse_subtotal_formula(row.subtotal_formula)
			for code, row in lines.items()
			if row.line_type == "Subtotal" and row.subtotal_formula and code != self.name
		}
		formulas[self.line_code] = terms
		cycle = find_cycle(formulas)
		if cycle:
			frappe.throw(
				_("The subtotal formulas refer to each other in a loop: {0}.").format(" → ".join(cycle))
			)

	def _check_not_used_in_formulas(self):
		users = [
			row.name
			for row in frappe.get_all(
				self.doctype,
				filters={"line_type": "Subtotal", "name": ("!=", self.name)},
				fields=["name", "subtotal_formula"],
			)
			if any(
				t.kind == "line" and t.ref == self.name for t in parse_subtotal_formula(row.subtotal_formula)
			)
		]
		if users:
			frappe.throw(
				_("{0} is used in the subtotal formula of {1}. Change those formulas first.").format(
					self.line_code, ", ".join(users)
				)
			)
