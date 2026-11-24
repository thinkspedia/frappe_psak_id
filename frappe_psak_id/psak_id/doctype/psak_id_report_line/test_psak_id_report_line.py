# Copyright (c) 2026, Thinkspedia and Contributors
# See license.txt

import frappe

from frappe_psak_id.psak_id.report_lines import (
	STANDARD_LINES,
	FormulaError,
	FormulaTerm,
	find_cycle,
	parse_subtotal_formula,
)
from frappe_psak_id.tests.utils import IntegrationTestCase

MANDATORY = (
	"PL-SUB-OP",
	"PL-SUB-PBFT",
	"PL-SUB-PL",
	"FP-SUB-TA",
	"FP-SUB-EQ",
	"FP-SUB-TLE",
	"OCI-SUB-TCI",
)


class TestSubtotalFormula(IntegrationTestCase):
	def test_parses_lines_and_categories(self):
		self.assertEqual(
			parse_subtotal_formula("+PL-OP-REV -PL-OP-COS +CAT:Income Tax"),
			[
				FormulaTerm(1, "line", "PL-OP-REV"),
				FormulaTerm(-1, "line", "PL-OP-COS"),
				FormulaTerm(1, "category", "Income Tax"),
			],
		)

	def test_parses_category_classification(self):
		self.assertEqual(
			parse_subtotal_formula("+CAT:Asset/Non-current -CAT:Equity"),
			[
				FormulaTerm(1, "category", "Asset", "Non-current"),
				FormulaTerm(-1, "category", "Equity"),
			],
		)

	def test_rejects_missing_sign_unknown_category_and_empty(self):
		for formula in (
			"PL-OP-REV",
			"+CAT:Other",
			"",
			"+PL-OP-REV PL-OP-COS",
			"+CAT:Equity/Current",
			"+CAT:Asset/Long-term",
		):
			with self.subTest(formula=formula), self.assertRaises(FormulaError):
				parse_subtotal_formula(formula)

	def test_find_cycle(self):
		line = lambda ref: FormulaTerm(1, "line", ref)  # noqa: E731
		self.assertIsNone(find_cycle({"A": [line("X")], "B": [line("A")]}))
		self.assertEqual(find_cycle({"A": [line("B")], "B": [line("A")]}), ["A", "B", "A"])


class TestPSAKIDReportLine(IntegrationTestCase):
	def _line(self, **values):
		return frappe.get_doc(
			{
				"doctype": "PSAK ID Report Line",
				"statement": "Profit or Loss",
				"label_id": "Uji",
				"label_en": "Test",
				"sequence": 999,
				**values,
			}
		)

	def test_standard_lines_are_installed_in_order(self):
		for statement, lines in STANDARD_LINES.items():
			standard = [line["line_code"] for line in lines]
			with self.subTest(statement=statement):
				codes = frappe.get_all(
					"PSAK ID Report Line",
					filters={"name": ("in", standard), "statement": statement},
					order_by="sequence asc",
					pluck="name",
				)
				self.assertEqual(codes, standard)

	def test_only_the_required_subtotals_are_mandatory(self):
		self.assertEqual(
			sorted(frappe.get_all("PSAK ID Report Line", filters={"mandatory": 1}, pluck="name")),
			sorted(MANDATORY),
		)

	def test_mandatory_line_cannot_be_disabled_deleted_or_changed(self):
		line = frappe.get_doc("PSAK ID Report Line", "PL-SUB-OP")
		line.disabled = 1
		with self.assertRaises(frappe.ValidationError):
			line.save()

		line.reload()
		line.subtotal_formula = "+PL-OP-REV"
		with self.assertRaises(frappe.ValidationError):
			line.save()

		line.reload()
		line.mandatory = 0
		line.save()
		self.assertEqual(frappe.db.get_value("PSAK ID Report Line", "PL-SUB-OP", "mandatory"), 1)

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("PSAK ID Report Line", "PL-SUB-OP")

	def test_user_cannot_create_a_mandatory_line(self):
		line = self._line(line_code="_T-LINE", line_type="Line", category="Operating", mandatory=1).insert()
		self.assertEqual(line.mandatory, 0)

	def test_line_needs_category_and_subtotal_needs_formula(self):
		with self.assertRaises(frappe.MandatoryError):
			self._line(line_code="_T-NOCAT", line_type="Line").insert()
		with self.assertRaises(FormulaError):
			self._line(line_code="_T-NOFORMULA", line_type="Subtotal").insert()

	def test_fields_of_other_line_types_are_cleared(self):
		line = self._line(
			line_code="_T-SUB",
			line_type="Subtotal",
			category="Operating",
			is_other_items=1,
			subtotal_formula="+PL-OP-REV",
		).insert()
		self.assertIsNone(line.category)
		self.assertEqual(line.is_other_items, 0)

	def test_formula_must_refer_to_existing_amount_lines(self):
		with self.assertRaises(frappe.ValidationError):
			self._line(line_code="_T-BAD", line_type="Subtotal", subtotal_formula="+PL-NOPE").insert()

		self._line(line_code="_T-HEAD", line_type="Heading").insert()
		with self.assertRaises(frappe.ValidationError):
			self._line(line_code="_T-BAD2", line_type="Subtotal", subtotal_formula="+_T-HEAD").insert()

		with self.assertRaises(frappe.ValidationError):
			self._line(line_code="_T-SELF", line_type="Subtotal", subtotal_formula="+_T-SELF").insert()

	def test_formula_loop_is_rejected(self):
		first = self._line(line_code="_T-A", line_type="Subtotal", subtotal_formula="+PL-OP-REV").insert()
		self._line(line_code="_T-B", line_type="Subtotal", subtotal_formula="+_T-A").insert()
		first.subtotal_formula = "+_T-B"
		with self.assertRaises(frappe.ValidationError):
			first.save()

	def test_line_used_in_a_formula_cannot_be_deleted(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("PSAK ID Report Line", "PL-OP-REV")

	def test_follows_operating_rules(self):
		with self.assertRaises(frappe.ValidationError):
			self._line(
				line_code="_T-OPFOLLOW", line_type="Line", category="Operating", follows_operating=1
			).insert()

		associates = frappe.get_doc("PSAK ID Report Line", "PL-INV-ASSOC")
		associates.follows_operating = 1
		with self.assertRaises(frappe.ValidationError):
			associates.save()

	def test_financial_position_line_needs_its_category_and_classification(self):
		with self.assertRaises(frappe.ValidationError):
			self._line(
				line_code="_T-FP-OP", statement="Financial Position", line_type="Line", category="Operating"
			).insert()
		with self.assertRaises(frappe.MandatoryError):
			self._line(
				line_code="_T-FP-NOCLS", statement="Financial Position", line_type="Line", category="Asset"
			).insert()

		equity = self._line(
			line_code="_T-FP-EQ",
			statement="Financial Position",
			line_type="Line",
			category="Equity",
			classification="Current",
			follows_operating=1,
		).insert()
		self.assertIsNone(equity.classification)
		self.assertEqual(equity.follows_operating, 0)

	def test_profit_or_loss_line_takes_only_its_own_categories(self):
		with self.assertRaises(frappe.ValidationError):
			self._line(line_code="_T-PL-ASSET", line_type="Line", category="Asset").insert()

		line = self._line(
			line_code="_T-PL-CLS",
			line_type="Line",
			category="Operating",
			classification="Current",
			reclassifiable=1,
		).insert()
		self.assertIsNone(line.classification)
		self.assertEqual(line.reclassifiable, 0)

	def test_other_comprehensive_income_line_has_no_category(self):
		line = self._line(
			line_code="_T-OCI",
			statement="Other Comprehensive Income",
			line_type="Line",
			category="Operating",
			reclassifiable=1,
		).insert()
		self.assertIsNone(line.category)
		self.assertEqual(line.reclassifiable, 1)

	def test_formula_categories_belong_to_the_statement(self):
		with self.assertRaises(frappe.ValidationError):
			self._line(
				line_code="_T-FP-SUB",
				statement="Financial Position",
				line_type="Subtotal",
				subtotal_formula="+CAT:Operating",
			).insert()

	def test_formula_adds_only_subtotals_of_another_statement(self):
		self._line(
			line_code="_T-OCI-SUB",
			statement="Other Comprehensive Income",
			line_type="Subtotal",
			subtotal_formula="+PL-SUB-PL +OCI-SUB-OCI",
		).insert()
		with self.assertRaises(frappe.ValidationError):
			self._line(
				line_code="_T-OCI-BAD",
				statement="Other Comprehensive Income",
				line_type="Subtotal",
				subtotal_formula="+PL-OP-REV",
			).insert()

	def test_formula_loop_across_statements_is_rejected(self):
		first = self._line(line_code="_T-PL-A", line_type="Subtotal", subtotal_formula="+PL-OP-REV").insert()
		self._line(
			line_code="_T-OCI-B",
			statement="Other Comprehensive Income",
			line_type="Subtotal",
			subtotal_formula="+_T-PL-A",
		).insert()
		first.subtotal_formula = "+_T-OCI-B"
		with self.assertRaises(frappe.ValidationError):
			first.save()
