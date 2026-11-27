import csv
import io

import frappe
from frappe.model.workflow import apply_workflow
from openpyxl import load_workbook

from frappe_psak_id.psak_id.doctype.psak_id_financial_statement.psak_id_financial_statement import (
	StatementNotReady,
	statement_lines,
)
from frappe_psak_id.psak_id.export_statement import export_excel, export_structured
from frappe_psak_id.psak_id.print_statement import PRINT_FORMAT
from frappe_psak_id.tests.test_export_statement import assert_sheet_adds_up, evaluate
from frappe_psak_id.tests.test_financial_statement import make_mapping, make_policy, make_statement
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	get_account,
	make_account,
	make_company,
	make_fiscal_year,
	make_journal_entry,
)

COMPANY = "_Test PSAK Package Company"


def amounts(doc, statement, field="amount"):
	return {row.report_line: row.get(field) for row in statement_lines(doc, statement)}


class TestStatementPackage(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COMPANY, "_TPK")
		make_fiscal_year(2035)
		make_fiscal_year(2036)
		make_policy(COMPANY, "2035-01-01", other_items_threshold_percent=0, other_items_threshold_amount=0)
		cash = get_account(COMPANY, "Cash")
		sales = get_account(COMPANY, "Sales")
		capital = make_account(COMPANY, "Package Capital", "Equity")
		building = make_account(COMPANY, "Package Building", "Fixed Assets")
		reserve = make_account(COMPANY, "Package Revaluation Reserve", "Equity")
		cls.deposit = make_account(COMPANY, "Package Deposit", "Current Assets")

		frappe.db.delete("PSAK ID Account Mapping", {"company": COMPANY})
		for account, line, extra in (
			(cash, "FP-CA-CASH", {}),
			(building, "FP-NCA-PPE", {}),
			(capital, "FP-EQ-CAP", {}),
			(reserve, "FP-EQ-OCI", {"oci_line": "OCI-NR-REV"}),
			(sales, "PL-OP-REV", {}),
		):
			make_mapping(COMPANY, account, line, valid_from="2035-01-01", **extra)

		for posting_date, account, amount, against in (
			("2035-01-05", cash, 1_000_000, capital),
			("2035-06-10", cash, 300_000, sales),
			("2036-02-10", cash, 200_000, sales),
			("2036-03-01", building, 400_000, cash),
			("2036-03-15", building, 50_000, reserve),
		):
			make_journal_entry(COMPANY, posting_date, account, amount, against)

	def test_package_holds_financial_position_profit_or_loss_and_oci(self):
		doc = make_statement(
			COMPANY, "2036-03-01", "2036-03-31", comparative="Same Period Last Year"
		).insert()
		self.assertEqual(doc.erpnext_bs_difference, 0)
		self.assertEqual(doc.blocking_issues, 0)

		position = amounts(doc, "Financial Position")
		self.assertEqual(position["FP-CA-CASH"], 1_100_000)
		self.assertEqual(position["FP-NCA-PPE"], 450_000)
		# BR-32: the profit of the fiscal year so far, not only of the month, is in retained earnings
		self.assertEqual(position["FP-EQ-RE"], 500_000)
		self.assertEqual(position["FP-EQ-OCI"], 50_000)
		self.assertEqual(position["FP-SUB-TA"], 1_550_000)
		self.assertEqual(position["FP-SUB-TLE"], 1_550_000)
		# The comparative of a position is the end of the prior fiscal year
		prior = amounts(doc, "Financial Position", "comparative_amount")
		self.assertEqual((prior["FP-CA-CASH"], prior["FP-EQ-RE"]), (1_300_000, 300_000))

		self.assertEqual(amounts(doc, "Profit or Loss")["PL-SUB-PL"], 0)
		oci = amounts(doc, "Other Comprehensive Income")
		self.assertEqual((oci["OCI-NR-REV"], oci["OCI-SUB-TCI"]), (50_000, 50_000))

		statements = [row.statement for row in doc.lines]
		self.assertEqual(
			list(dict.fromkeys(statements)),
			["Financial Position", "Profit or Loss", "Other Comprehensive Income"],
		)

	def test_unmapped_balance_sheet_account_blocks_review(self):
		make_journal_entry(COMPANY, "2036-04-10", self.deposit, 70_000, get_account(COMPANY, "Cash"))
		doc = make_statement(COMPANY, "2036-04-01", "2036-04-30").insert()
		# BR-30 and BR-31: the deposit is on no line, so total assets fall short of ERPNext's
		self.assertEqual(doc.unmapped_count, 1)
		self.assertEqual(doc.erpnext_bs_difference, -70_000)
		self.assertEqual(doc.blocking_issues, 2)
		self.assertIn("Balance Sheet", doc.check_messages)
		with self.assertRaises(StatementNotReady):
			apply_workflow(doc, "Submit for Review")

		make_mapping(COMPANY, self.deposit, "FP-CA-FIN", valid_from="2036-04-01")
		doc.reload()
		doc = apply_workflow(doc, "Submit for Review")
		self.assertEqual(
			(doc.workflow_state, doc.blocking_issues, doc.erpnext_bs_difference), ("Under Review", 0, 0)
		)
		self.assertEqual(amounts(doc, "Financial Position")["FP-CA-FIN"], 70_000)

	def test_exports_present_every_statement_of_the_package(self):
		# A quarter: the test of the package itself has the statement of March
		doc = make_statement(
			COMPANY, "2036-01-01", "2036-03-31", "Quarterly", comparative="Same Period Last Year"
		).insert()

		context = doc.get_print_context()
		self.assertEqual(context.title[0], "Laporan Laba Rugi dan Penghasilan Komprehensif Lain")
		lines = {row.label_en: row for row in context.lines}
		self.assertEqual(lines["Other Comprehensive Income"].kind, "Heading")
		self.assertTrue(lines["Total comprehensive income"].total)
		self.assertEqual(
			context.position.columns,
			[("31 Maret 2036", "31 March 2036"), ("31 Desember 2035", "31 December 2035")],
		)
		frappe.db.set_value("PSAK ID Company Policy", COMPANY, "show_category_headings", 1)
		headings = [row.label_en for row in doc.get_print_context().position.lines if row.kind == "Heading"]
		# The company has no liabilities: their nil lines and headings are left off
		self.assertEqual(headings, ["Non-current Assets", "Current Assets", "Equity"])
		html = frappe.get_print(doc.doctype, doc.name, print_format=PRINT_FORMAT, doc=doc)
		self.assertLess(
			html.index("Laporan Posisi Keuangan"),
			html.index("Laporan Laba Rugi dan Penghasilan Komprehensif Lain"),
		)

		export_excel(doc.name)
		workbook = load_workbook(io.BytesIO(frappe.local.response.filecontent))
		self.assertEqual(workbook.sheetnames, ["Posisi Keuangan", "Laba Rugi dan PKL", "Arus Kas", "Info"])
		sheet = workbook["Posisi Keuangan"]
		self.assertEqual(sheet["A4"].value, "Pada 31 Maret 2036")
		assert_sheet_adds_up(self, sheet, statement_lines(doc, "Financial Position"))
		rows = {sheet.cell(row, 2).value: row for row in range(1, sheet.max_row + 1)}
		# Current assets add up the current lines only (+CAT:Asset/Current)
		self.assertEqual(evaluate(sheet, sheet.cell(rows["Total current assets"], 4).value), 1_100_000)

		sheet = workbook["Laba Rugi dan PKL"]
		assert_sheet_adds_up(
			self,
			sheet,
			statement_lines(doc, "Profit or Loss") + statement_lines(doc, "Other Comprehensive Income"),
		)
		rows = {sheet.cell(row, 2).value: row for row in range(1, sheet.max_row + 1)}
		# Total comprehensive income adds profit or loss and other comprehensive income on the sheet
		total = sheet.cell(rows["Total comprehensive income"], 4).value
		self.assertTrue(total.startswith("="))
		self.assertEqual(evaluate(sheet, total), 250_000)

		export_structured(doc.name, "csv")
		rows = list(csv.DictReader(io.StringIO(frappe.local.response.filecontent.decode("utf-8"))))
		# A quarterly package also presents the cash flows (BR-42)
		self.assertEqual(
			list(dict.fromkeys(row["statement"] for row in rows)),
			["Financial Position", "Profit or Loss", "Other Comprehensive Income", "Cash Flow"],
		)
