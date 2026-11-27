import datetime
from unittest.mock import patch

import frappe

from frappe_psak_id.psak_id.mapping import apply_template, default_valid_from, match_row, pattern_regex
from frappe_psak_id.psak_id.mapping_templates import (
	BALANCE_SHEET_TEMPLATE_VERSION,
	PROFIT_OR_LOSS_TEMPLATE_VERSION,
	STANDARD_TEMPLATE_VERSION,
	STANDARD_TEMPLATES,
)
from frappe_psak_id.tests.test_financial_statement import make_policy
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	get_account,
	make_account,
	make_company,
	make_cost_center,
)

COMPANY = "_Test PSAK Template Company"
BALANCE_SHEET_COMPANY = "_Test PSAK Template Balance Sheet Company"
CASH_FLOW_COMPANY = "_Test PSAK Template Cash Flow Company"
SERVICES = "Services (Standard)"
SERVICES_1_1 = "Services (Standard 1.1)"
SERVICES_1_2 = "Services (Standard 1.2)"
BALANCE_SHEET_ROOT_TYPES = ("Asset", "Liability", "Equity")
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
				row("Bank", "FP-CA-CASH", "Asset", match_on="Account Type"),
			)
		]
		bank = frappe._dict(account_name="BCA 123", account_type="Bank", root_type="Asset")
		self.assertEqual(match_row(bank, rows).report_line, "FP-CA-CASH")
		# A row without a root type is for income and expense accounts only
		bank.update(account_number="6200", account_type=None)
		self.assertIsNone(match_row(bank, rows))

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
			self.assertEqual(doc.template_version, template["template_version"])
			self.assertEqual(len(doc.rows), len(template["rows"]))
		industries = ["Investment Holding", "Manufacturing", "Property", "Services", "Trading"]
		for version in (
			PROFIT_OR_LOSS_TEMPLATE_VERSION,
			BALANCE_SHEET_TEMPLATE_VERSION,
			STANDARD_TEMPLATE_VERSION,
		):
			self.assertEqual(
				sorted(t["industry"] for t in STANDARD_TEMPLATES if t["template_version"] == version),
				industries,
			)

	def test_subtotals_final_tax_as_income_tax_and_repeated_patterns_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_template(("*profit*", "PL-SUB-OP", {})).insert()
		with self.assertRaises(frappe.ValidationError):
			self.make_template(("*pph final*", "PL-TAX", {"is_final_tax": 1})).insert()
		with self.assertRaises(frappe.ValidationError):
			self.make_template(("*sales*", "PL-OP-REV", {}), ("*Sales* ", "PL-OP-OTH", {})).insert()

	def test_balance_sheet_rows_need_a_line_of_their_root_type(self):
		for rows in (
			# A financial position line needs the root type it is for
			[("*cash*", "FP-CA-CASH", {})],
			[("*cash*", "FP-CL-AP", {"root_type": "Asset"})],
			[("*cash*", "PL-OP-OTH", {"root_type": "Asset"})],
			# Only equity rows have an OCI line, and it is a line of that statement
			[("*reserve*", "FP-CA-OTH", {"root_type": "Asset", "oci_line": "OCI-NR-REV"})],
			[("*reserve*", "FP-EQ-OCI", {"root_type": "Equity", "oci_line": "FP-EQ-RE"})],
			[("Bnak", "FP-CA-CASH", {"root_type": "Asset", "match_on": "Account Type"})],
		):
			with self.assertRaises(frappe.ValidationError, msg=rows):
				self.make_template(*rows).insert()

		template = self.make_template(
			("Bank", "FP-CA-CASH", {"root_type": "Asset", "match_on": "Account Type"}),
			("*reserve*", "FP-EQ-OCI", {"root_type": "Equity", "oci_line": "OCI-NR-REV"}),
		).insert()
		self.assertEqual(len(template.rows), 2)

	def test_cash_flow_lines_are_those_an_account_mapping_accepts(self):
		for rows in (
			# The cash itself has no cash flow line
			[("Bank", "FP-CA-CASH", {"root_type": "Asset", "cash_flow_line": "CF-OP-WC-OA"})],
			[
				(
					"*loan*",
					"FP-CL-BORR",
					{"root_type": "Liability", "cash_flow_line_decrease": "CF-FIN-BORR-OUT"},
				)
			],
			# Lines of another statement, computed lines and lines outside the activities
			[("*debtor*", "FP-CA-AR", {"root_type": "Asset", "cash_flow_line": "PL-OP-REV"})],
			[("*debtor*", "FP-CA-AR", {"root_type": "Asset", "cash_flow_line": "CF-OP-START"})],
			[("*debtor*", "FP-CA-AR", {"root_type": "Asset", "cash_flow_line": "CF-OPEN"})],
			[("*debtor*", "FP-CA-AR", {"root_type": "Asset", "cash_flow_line": "CF-SUB-OP"})],
		):
			with self.assertRaises(frappe.ValidationError, msg=rows):
				self.make_template(*rows).insert()

		template = self.make_template(
			(
				"*loan*",
				"FP-CL-BORR",
				{
					"root_type": "Liability",
					"cash_flow_line": "CF-FIN-BORR-IN",
					"cash_flow_line_decrease": "CF-FIN-BORR-OUT",
				},
			),
			# Income and expense accounts have one line for their amount
			(
				"*interest expense*",
				"PL-FIN-INT",
				{"cash_flow_line": "CF-FIN-INT", "cash_flow_line_decrease": "CF-FIN-OTH"},
			),
		)
		frappe.delete_doc("PSAK ID Mapping Template", template.template_name, force=True, ignore_missing=True)
		template.insert()
		self.assertEqual(template.rows[0].cash_flow_line_decrease, "CF-FIN-BORR-OUT")
		self.assertIsNone(template.rows[1].cash_flow_line_decrease)

	def test_standard_template_names_a_cash_flow_line_for_every_balance_sheet_row_but_cash(self):
		for template in STANDARD_TEMPLATES:
			for row in template["rows"]:
				has_line = bool(row.get("cash_flow_line"))
				if template["template_version"] != STANDARD_TEMPLATE_VERSION:
					self.assertFalse(has_line, row)
				elif row["root_type"] in BALANCE_SHEET_ROOT_TYPES:
					self.assertEqual(has_line, row["report_line"] != "FP-CA-CASH", row)


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

	def test_mappings_start_after_the_last_final_statement_by_default(self):
		make_policy(COMPANY, "2026-01-01")
		with patch("frappe_psak_id.psak_id.mapping.final_until", return_value=None):
			self.assertEqual(default_valid_from(COMPANY), datetime.date(2026, 1, 1))
		# Mappings in force in a final period are refused (BR-09)
		with patch("frappe_psak_id.psak_id.mapping.final_until", return_value=datetime.date(2026, 1, 31)):
			self.assertEqual(default_valid_from(COMPANY), datetime.date(2026, 2, 1))
		with patch("frappe_psak_id.psak_id.mapping.final_until", return_value=datetime.date(2025, 12, 31)):
			self.assertEqual(default_valid_from(COMPANY), datetime.date(2026, 1, 1))

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
			(SERVICES, PROFIT_OR_LOSS_TEMPLATE_VERSION),
		)
		# A profit or loss template leaves the balance sheet alone
		self.assertNotIn(get_account(COMPANY, "Cash"), mappings)

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


class TestApplyBalanceSheetTemplate(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(BALANCE_SHEET_COMPANY, "_TPB")
		frappe.db.delete("PSAK ID Account Mapping", {"company": BALANCE_SHEET_COMPANY})

	def test_template_maps_every_balance_sheet_account_of_the_standard_chart(self):
		result = apply_template(SERVICES_1_1, BALANCE_SHEET_COMPANY, "2027-01-01")
		self.assertEqual(result.failed, [])
		balance_sheet = frappe.get_all(
			"Account",
			filters={
				"company": BALANCE_SHEET_COMPANY,
				"is_group": 0,
				"root_type": ("in", ("Asset", "Liability", "Equity")),
			},
			pluck="name",
		)
		self.assertTrue(balance_sheet)
		self.assertEqual(set(balance_sheet) & set(result.unmatched), set())

		mappings = {
			row.account: row
			for row in frappe.get_all(
				"PSAK ID Account Mapping",
				filters={"company": BALANCE_SHEET_COMPANY},
				fields=["account", "report_line", "oci_line", "source_template_version"],
			)
		}
		expected = {
			"Cash": "FP-CA-CASH",
			"Debtors": "FP-CA-AR",
			"Stock In Hand": "FP-CA-INV",
			"Buildings": "FP-NCA-PPE",
			"Accumulated Depreciation": "FP-NCA-PPE",
			"Software": "FP-NCA-INTANG",
			# Typed Payable in the standard chart, but an asset
			"Employee Advances": "FP-CA-PREP",
			"Earnest Money": "FP-CA-FIN",
			"Creditors": "FP-CL-AP",
			"Payroll Payable": "FP-CL-ACCR",
			"Customer Advances": "FP-CL-CONTRACT",
			"Secured Loans": "FP-CL-BORR",
			"Long-term Provisions": "FP-NCL-PROV",
			"Short-term Provisions": "FP-CL-PROV",
			"Employee Benefits Obligation": "FP-NCL-EB",
			"Capital Stock": "FP-EQ-CAP",
			"Dividends Paid": "FP-EQ-RE",
			"Opening Balance Equity": "FP-EQ-OTH",
			"Revaluation Surplus": "FP-EQ-OCI",
		}
		for account_name, line in expected.items():
			account = get_account(BALANCE_SHEET_COMPANY, account_name)
			# The v15 standard chart has no Software account
			if account in balance_sheet:
				self.assertEqual(mappings[account].report_line, line, account_name)
		revaluation = mappings[get_account(BALANCE_SHEET_COMPANY, "Revaluation Surplus")]
		self.assertEqual(revaluation.oci_line, "OCI-NR-REV")
		self.assertEqual(revaluation.source_template_version, BALANCE_SHEET_TEMPLATE_VERSION)
		self.assertIsNone(mappings[get_account(BALANCE_SHEET_COMPANY, "Cash")].oci_line)
		# The income and expense rows of version 1.0 are part of version 1.1
		self.assertEqual(mappings[get_account(BALANCE_SHEET_COMPANY, "Salary")].report_line, "PL-OP-GA")


class TestCompleteCashFlowLines(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(CASH_FLOW_COMPANY, "_TPC")

	def setUp(self):
		frappe.db.delete("PSAK ID Account Mapping", {"company": CASH_FLOW_COMPANY})
		apply_template(SERVICES_1_1, CASH_FLOW_COMPANY, "2027-01-01")

	def mappings(self, account_name):
		return frappe.get_all(
			"PSAK ID Account Mapping",
			filters={"account": get_account(CASH_FLOW_COMPANY, account_name)},
			fields=["name", "report_line", "valid_from", "cash_flow_line", "cash_flow_line_decrease"],
			order_by="valid_from",
		)

	def test_mapped_accounts_get_a_new_dated_mapping_with_the_cash_flow_lines(self):
		# Without the option, mapped accounts are skipped as before
		result = apply_template(SERVICES_1_2, CASH_FLOW_COMPANY, "2027-04-01")
		self.assertEqual((result.created, result.completed), ([], []))

		result = apply_template(SERVICES_1_2, CASH_FLOW_COMPANY, "2027-04-01", complete_cash_flow=1)
		self.assertEqual(result.failed, [])
		self.assertEqual(result.created, [])
		self.assertTrue(result.completed)

		debtors = self.mappings("Debtors")
		self.assertEqual(
			[m.valid_from for m in debtors], [datetime.date(2027, 1, 1), datetime.date(2027, 4, 1)]
		)
		# The mapping in force before keeps its classification; the new one copies its line
		self.assertFalse(debtors[0].cash_flow_line)
		self.assertEqual((debtors[1].report_line, debtors[1].cash_flow_line), ("FP-CA-AR", "CF-OP-WC-AR"))

		depreciation = self.mappings("Accumulated Depreciation")[-1]
		self.assertEqual(
			(depreciation.cash_flow_line, depreciation.cash_flow_line_decrease),
			("CF-INV-PPE-SELL", "CF-OP-DEP"),
		)
		# Cash, and income and expense accounts the template gives no line, keep their one mapping
		self.assertEqual(len(self.mappings("Cash")), 1)
		self.assertEqual(len(self.mappings("Salary")), 1)

		# Applying again finds nothing left to complete
		result = apply_template(SERVICES_1_2, CASH_FLOW_COMPANY, "2027-05-01", complete_cash_flow=1)
		self.assertEqual((result.completed, result.failed), ([], []))

	def test_a_mapping_starting_on_or_after_the_date_is_completed_in_place(self):
		debtors = self.mappings("Debtors")[0]
		frappe.db.set_value("PSAK ID Account Mapping", debtors.name, "valid_from", "2027-07-01")

		apply_template(SERVICES_1_2, CASH_FLOW_COMPANY, "2027-04-01", complete_cash_flow=1)
		self.assertEqual(
			[(m.name, m.valid_from, m.cash_flow_line) for m in self.mappings("Debtors")],
			[(debtors.name, datetime.date(2027, 7, 1), "CF-OP-WC-AR")],
		)

	def test_income_outside_operating_profit_gets_the_default_line_of_its_activity(self):
		sales = self.mappings("Sales")[0]
		conditional = frappe.copy_doc(frappe.get_doc("PSAK ID Account Mapping", sales.name))
		conditional.update(
			{
				"report_line": "PL-INV-INC",
				"condition_type": "Cost Center",
				"condition_doctype": "Cost Center",
				"condition_value": make_cost_center(CASH_FLOW_COMPANY, "Investment Property"),
				"priority": 5,
			}
		)
		conditional.insert()

		result = apply_template(SERVICES_1_2, CASH_FLOW_COMPANY, "2027-04-01", complete_cash_flow=1)
		self.assertEqual(result.failed, [])
		# The template's sales row has no cash flow line: revenue is part of operating profit and
		# keeps its one mapping, the rent of the investment property moves to investing activities
		self.assertEqual(
			sorted((m.valid_from, m.report_line, m.cash_flow_line or "") for m in self.mappings("Sales")),
			[
				(datetime.date(2027, 1, 1), "PL-INV-INC", ""),
				(datetime.date(2027, 1, 1), "PL-OP-REV", ""),
				(datetime.date(2027, 4, 1), "PL-INV-INC", "CF-INV-OTH"),
			],
		)

	def test_new_accounts_are_mapped_with_the_cash_flow_lines(self):
		frappe.db.delete("PSAK ID Account Mapping", {"company": CASH_FLOW_COMPANY})
		result = apply_template(SERVICES_1_2, CASH_FLOW_COMPANY, "2027-01-01")
		self.assertEqual(result.failed, [])
		loan = self.mappings("Secured Loans")[0]
		self.assertEqual(
			(loan.cash_flow_line, loan.cash_flow_line_decrease), ("CF-FIN-BORR-IN", "CF-FIN-BORR-OUT")
		)
		self.assertFalse(self.mappings("Cash")[0].cash_flow_line)
