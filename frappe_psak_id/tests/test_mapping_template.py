import frappe

from frappe_psak_id.psak_id.mapping import apply_template, match_row, pattern_regex
from frappe_psak_id.psak_id.mapping_templates import STANDARD_TEMPLATE_VERSION, STANDARD_TEMPLATES
from frappe_psak_id.tests.utils import IntegrationTestCase, get_account, make_account, make_company

COMPANY = "_Test PSAK Template Company"
SERVICES = "Services (Standard)"
STAFF_USER = "psak-template-staff@example.com"


class TestPatterns(IntegrationTestCase):
	def test_star_matches_any_text_and_case_is_ignored(self):
		regex = pattern_regex(" *Interest Income* ")
		self.assertTrue(regex.match("Bank interest income on deposits"))
		self.assertTrue(regex.match("INTEREST INCOME"))
		self.assertFalse(regex.match("Interest"))
		self.assertTrue(pattern_regex("41*").match("4110"))
		self.assertFalse(pattern_regex("4.1*").match("4110"))

	def test_first_matching_row_of_the_right_root_type_wins(self):
		row = lambda pattern, line, root_type=None, match_on="Name": frappe._dict(  # noqa: E731
			account_pattern=pattern, report_line=line, root_type=root_type, match_on=match_on
		)
		rows = [
			(r, pattern_regex(r.account_pattern))
			for r in (
				row("*penjualan*", "PL-OP-REV", "Income"),
				row("*penjualan*", "PL-OP-SELL", "Expense"),
				row("6*", "PL-OP-GA", match_on="Number"),
			)
		]
		account = frappe._dict(account_name="Beban Penjualan", account_number="6100", root_type="Expense")
		self.assertEqual(match_row(account, rows).report_line, "PL-OP-SELL")
		account.account_name = "Beban Kantor"
		self.assertEqual(match_row(account, rows).report_line, "PL-OP-GA")
		account.account_number = None
		self.assertIsNone(match_row(account, rows))


class TestMappingTemplate(IntegrationTestCase):
	def make_template(self, *rows):
		return frappe.get_doc(
			{
				"doctype": "PSAK ID Mapping Template",
				"template_name": "_Test PSAK Template",
				"industry": "Services",
				"template_version": "1",
				"rows": [
					{"match_on": "Name", "account_pattern": pattern, "report_line": line, **extra}
					for pattern, line, extra in rows
				],
			}
		)

	def test_standard_templates_are_installed(self):
		for template in STANDARD_TEMPLATES:
			doc = frappe.get_doc("PSAK ID Mapping Template", template["template_name"])
			self.assertEqual(doc.template_version, STANDARD_TEMPLATE_VERSION)
			self.assertEqual(len(doc.rows), len(template["rows"]))
		self.assertEqual(
			sorted(template["industry"] for template in STANDARD_TEMPLATES),
			["Investment Holding", "Manufacturing", "Property", "Services", "Trading"],
		)

	def test_subtotals_final_tax_as_income_tax_and_repeated_patterns_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_template(("*profit*", "PL-SUB-OP", {})).insert()
		with self.assertRaises(frappe.ValidationError):
			self.make_template(("*pph final*", "PL-TAX", {"is_final_tax": 1})).insert()
		with self.assertRaises(frappe.ValidationError):
			self.make_template(("*sales*", "PL-OP-REV", {}), ("*Sales* ", "PL-OP-OTH", {})).insert()


class TestApplyTemplate(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COMPANY, "_TPT")
		frappe.db.delete("PSAK ID Account Mapping", {"company": COMPANY})
		cls.extra = {
			"interest_income": make_account(COMPANY, "Interest Income", "Indirect Income"),
			"technician": make_account(COMPANY, "Gaji Teknisi Lapangan", "Indirect Expenses"),
			"final_tax": make_account(COMPANY, "PPh Final Bunga Deposito", "Indirect Expenses"),
			"interest_expense": make_account(COMPANY, "Interest Expense", "Indirect Expenses"),
			"unknown": make_account(COMPANY, "Xyzzy", "Indirect Expenses"),
		}

	def mappings(self):
		return {
			row.account: row
			for row in frappe.get_all(
				"PSAK ID Account Mapping",
				filters={"company": COMPANY},
				fields=[
					"name",
					"account",
					"report_line",
					"expense_nature",
					"is_final_tax",
					"valid_from",
					"source_template",
					"source_template_version",
				],
			)
		}

	def test_services_template_maps_the_standard_chart(self):
		sales = get_account(COMPANY, "Sales")
		existing = frappe.get_doc(
			{
				"doctype": "PSAK ID Account Mapping",
				"company": COMPANY,
				"account": sales,
				"report_line": "PL-OP-OTH",
				"valid_from": "2027-01-01",
				"priority": 10,
			}
		).insert()

		result = apply_template(SERVICES, COMPANY, "2027-01-01")
		self.assertEqual(result.skipped, [sales])
		self.assertEqual(result.unmatched, [self.extra["unknown"]])
		self.assertEqual(result.failed, [])

		mappings = self.mappings()
		self.assertEqual(mappings[sales].name, existing.name)
		self.assertEqual(mappings[sales].report_line, "PL-OP-OTH")
		expected = {
			get_account(COMPANY, "Service"): ("PL-OP-REV", None, 0),
			get_account(COMPANY, "Cost of Goods Sold"): ("PL-OP-COS", "Raw Materials and Goods", 0),
			get_account(COMPANY, "Salary"): ("PL-OP-GA", "Employee Benefits", 0),
			get_account(COMPANY, "Depreciation"): ("PL-OP-GA", "Depreciation", 0),
			get_account(COMPANY, "Commission on Sales"): ("PL-OP-SELL", "Other", 0),
			get_account(COMPANY, "Exchange Gain/Loss"): ("PL-OP-OTH", "Other", 0),
			get_account(COMPANY, "Miscellaneous Expenses"): ("PL-OP-OTH", "Other", 0),
			self.extra["interest_income"]: ("PL-INV-INC", None, 0),
			self.extra["technician"]: ("PL-OP-COS", "Employee Benefits", 0),
			self.extra["final_tax"]: ("PL-INV-INC", None, 1),
			self.extra["interest_expense"]: ("PL-FIN-INT", None, 0),
		}
		for account, (line, nature, final_tax) in expected.items():
			mapping = mappings[account]
			self.assertEqual(
				(mapping.report_line, mapping.expense_nature or None, mapping.is_final_tax),
				(line, nature, final_tax),
				account,
			)
		created = mappings[get_account(COMPANY, "Salary")]
		self.assertEqual(str(created.valid_from), "2027-01-01")
		self.assertEqual(
			(created.source_template, created.source_template_version),
			(SERVICES, STANDARD_TEMPLATE_VERSION),
		)

		again = apply_template(SERVICES, COMPANY, "2027-01-01")
		self.assertEqual(again.created, [])
		self.assertEqual(again.unmatched, [self.extra["unknown"]])

	def test_staff_may_not_apply_a_template(self):
		if not frappe.db.exists("User", STAFF_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": STAFF_USER,
					"first_name": "PSAK Template Staff",
					"send_welcome_email": 0,
				}
			).insert().add_roles("PSAK ID - Accounting - Staff")
		frappe.set_user(STAFF_USER)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			apply_template(SERVICES, COMPANY, "2027-01-01")
