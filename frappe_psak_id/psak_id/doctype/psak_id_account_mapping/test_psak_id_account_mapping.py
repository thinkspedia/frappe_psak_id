# Copyright (c) 2026, Thinkspedia and Contributors
# See license.txt

import frappe

from frappe_psak_id.tests.utils import IntegrationTestCase, get_account, make_account, make_company

# The tests build their own company and chart. Test records of the linked doctypes are skipped:
# ERPNext's fail on a site where its setup wizard never ran, and following DocType links walks
# into doctypes of apps that are not installed. Frappe v16 reads the first name, v15 the second.
IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Company",
	"Account",
	"PSAK ID Report Line",
	"Accounting Dimension",
	"Party Type",
	"DocType",
]
test_ignore = IGNORE_TEST_RECORD_DEPENDENCIES


class TestPSAKIDAccountMapping(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = make_company("_Test PSAK Mapping Company", "_TPM")
		cls.other_company = make_company("_Test PSAK Other Company", "_TPO")
		make_account(cls.company, "Interest Income", "Indirect Income")
		make_account(cls.company, "Interest Expense", "Indirect Expenses")
		make_account(cls.company, "Tax Expense", "Indirect Expenses")

	def setUp(self):
		frappe.db.delete("PSAK ID Account Mapping", {"company": self.company})

	def _mapping(self, account_name, report_line, **values):
		return frappe.get_doc(
			{
				"doctype": "PSAK ID Account Mapping",
				"company": self.company,
				"account": get_account(self.company, account_name),
				"report_line": report_line,
				"valid_from": "2027-01-01",
				"priority": 10,
				**values,
			}
		)

	def test_revenue_mapping_copies_root_type_and_category(self):
		mapping = self._mapping("Sales", "PL-OP-REV").insert()
		self.assertEqual(mapping.root_type, "Income")
		self.assertEqual(mapping.category, "Operating")
		self.assertTrue(mapping.name.startswith("PSAK-MAP-"))

	def test_account_must_be_a_profit_or_loss_leaf_of_the_company(self):
		cases = {
			"group": dict(account=get_account(self.company, "Direct Income")),
			"asset": dict(account=get_account(self.company, "Cash")),
			"other company": dict(account=get_account(self.other_company, "Sales")),
		}
		for case, values in cases.items():
			with self.subTest(case), self.assertRaises(frappe.ValidationError):
				self._mapping("Sales", "PL-OP-REV", **values).insert()

	def test_report_line_must_be_a_line(self):
		with self.assertRaises(frappe.ValidationError):
			self._mapping("Sales", "PL-SUB-OP").insert()

	def test_operating_expense_needs_a_nature_other_categories_do_not(self):
		with self.assertRaises(frappe.MandatoryError):
			self._mapping("Salary", "PL-OP-GA").insert()

		salary = self._mapping("Salary", "PL-OP-GA", expense_nature="Employee Benefits").insert()
		self.assertEqual(salary.expense_nature, "Employee Benefits")

		interest = self._mapping("Interest Expense", "PL-FIN-INT").insert()
		self.assertFalse(interest.expense_nature)

		income = self._mapping("Service", "PL-OP-REV", expense_nature="Other").insert()
		self.assertFalse(income.expense_nature)

	def test_final_tax_cannot_be_income_tax(self):
		with self.assertRaises(frappe.ValidationError):
			self._mapping("Tax Expense", "PL-TAX", is_final_tax=1).insert()

		mapping = self._mapping("Tax Expense", "PL-OP-FTAX", is_final_tax=1, expense_nature="Other").insert()
		self.assertEqual(mapping.category, "Operating")

	def test_cost_center_condition(self):
		cost_center = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 0})
		mapping = self._mapping(
			"Interest Income",
			"PL-INV-INC",
			condition_type="Cost Center",
			condition_doctype="Cost Center",
			condition_value=cost_center,
			priority=1,
		).insert()
		self.assertEqual(mapping.condition_doctype, "Cost Center")

		with self.assertRaises(frappe.ValidationError):
			self._mapping("Interest Income", "PL-INV-INC", condition_type="Cost Center", priority=2).insert()

		other_cost_center = frappe.db.get_value("Cost Center", {"company": self.other_company, "is_group": 0})
		with self.assertRaises(frappe.ValidationError):
			self._mapping(
				"Interest Income",
				"PL-INV-INC",
				condition_type="Cost Center",
				condition_doctype="Cost Center",
				condition_value=other_cost_center,
				priority=3,
			).insert()

	def test_party_condition_needs_party_type(self):
		with self.assertRaises(frappe.MandatoryError):
			self._mapping("Interest Income", "PL-INV-INC", condition_type="Party").insert()

	def test_condition_doctype_follows_the_condition_and_clears_without_one(self):
		cost_center = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 0})
		mapping = self._mapping(
			"Sales",
			"PL-OP-REV",
			condition_type="Cost Center",
			condition_doctype="Cost Center",
			condition_value=cost_center,
		).insert()

		mapping.condition_type = None
		mapping.save()
		self.assertFalse(mapping.condition_value)
		self.assertFalse(mapping.condition_doctype)

	def test_same_rule_twice_is_rejected(self):
		self._mapping("Sales", "PL-OP-REV").insert()
		with self.assertRaises(frappe.DuplicateEntryError):
			self._mapping("Sales", "PL-OP-REV").insert()
		self._mapping("Sales", "PL-OP-REV", priority=20).insert()
		self._mapping("Sales", "PL-OP-REV", valid_from="2028-01-01").insert()
