import csv
import io
import re

import frappe
from frappe.utils import flt
from openpyxl import load_workbook

from frappe_psak_id.psak_id.export_statement import (
	STRUCTURED_COLUMNS,
	export_excel,
	export_structured,
	subtotal_terms,
)
from frappe_psak_id.tests.test_financial_statement import make_mapping, make_policy, make_statement
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	get_account,
	make_account,
	make_company,
	make_fiscal_year,
	make_journal_entry,
)

COMPANY = "_Test PSAK Export Company"
CELL = re.compile(r"([+-]?)([A-Z]+)(\d+)")


class TestExportStatement(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COMPANY, "_TPX")
		make_fiscal_year(2025)
		make_fiscal_year(2026)
		make_policy(COMPANY, "2026-01-01", expense_presentation="By Function")
		cash = get_account(COMPANY, "Cash")
		sales = get_account(COMPANY, "Sales")
		salary = get_account(COMPANY, "Salary")
		rent = make_account(COMPANY, "Export Rent", "Indirect Expenses")
		frappe.db.delete("PSAK ID Account Mapping", {"company": COMPANY})
		make_mapping(COMPANY, sales, "PL-OP-REV")
		make_mapping(COMPANY, salary, "PL-OP-GA", expense_nature="Employee Benefits")
		make_mapping(COMPANY, rent, "PL-OP-GA", expense_nature="Other")
		for posting_date, account, amount in (
			("2025-06-10", sales, -800_000),
			("2025-06-11", salary, 120_000),
			("2026-06-10", sales, -1_234_567),
			("2026-06-11", salary, 300_400),
			("2026-06-12", rent, 25_000),
		):
			make_journal_entry(COMPANY, posting_date, account, amount, cash)

		cls.statement = make_statement(
			COMPANY, "2026-06-01", "2026-06-30", comparative="Restated Prior Year", unit="Thousands"
		).insert()

	def test_excel_subtotals_are_formulas_that_give_the_statement_amounts(self):
		doc = self.statement
		export_excel(doc.name)
		response = frappe.local.response
		self.assertEqual(response.filename, "PSAK118__TPX_2026-06_Draft.xlsx")
		workbook = load_workbook(io.BytesIO(response.filecontent))
		self.assertEqual(
			workbook.sheetnames, ["Laba Rugi", "Beban per Sifat", "Rekonsiliasi Transisi", "Info"]
		)

		sheet = workbook["Laba Rugi"]
		self.assertEqual(sheet["A1"].value, COMPANY)
		self.assertEqual(sheet["A1"].alignment.horizontal, "centerContinuous")
		self.assertFalse(sheet.merged_cells.ranges)
		self.assertIn("DRAFT", [sheet.cell(row, 1).value for row in range(1, 12)])
		rows = {sheet.cell(row, 2).value: row for row in range(1, sheet.max_row + 1)}
		subtotals = 0
		for line in doc.lines:
			row = rows[line.label_en]
			for column, field in ((4, "amount"), (5, "comparative_amount")):
				cell = sheet.cell(row, column)
				self.assertEqual(cell.number_format, '#,##0,;(#,##0,);"-"')
				if line.line_type == "Subtotal":
					subtotals += 1
					self.assertTrue(str(cell.value).startswith("="), line.report_line)
				self.assertAlmostEqual(evaluate(sheet, cell.value), flt(line.get(field)), places=2)
		self.assertTrue(subtotals)
		self.assertEqual(flt(sheet.cell(rows["Revenue"], 4).value), 1_234_567)

		sheet = workbook["Beban per Sifat"]
		total = sheet.cell(sheet.max_row, 3).value
		self.assertTrue(total.startswith("="))
		self.assertAlmostEqual(evaluate(sheet, total), -325_400)

		sheet = workbook["Rekonsiliasi Transisi"]
		self.assertAlmostEqual(
			evaluate(sheet, sheet.cell(sheet.max_row - 1, 3).value), doc.psak201_profit_or_loss
		)
		self.assertAlmostEqual(
			evaluate(sheet, sheet.cell(sheet.max_row, 3).value), doc.restated_profit_or_loss
		)

		info = {row[0].value: row[2].value for row in workbook["Info"].iter_rows()}
		self.assertEqual((info["Perusahaan"], info["Status"], info["Versi"]), (COMPANY, "Draft", 1))

	def test_structured_data_has_one_row_per_line(self):
		doc = self.statement
		lines = [line for line in doc.lines if line.line_type != "Heading"]

		export_structured(doc.name, "csv")
		response = frappe.local.response
		self.assertEqual(response.filename, "PSAK118__TPX_2026-06_Draft_data.csv")
		rows = list(csv.DictReader(io.StringIO(response.filecontent.decode("utf-8"))))
		self.assertEqual(tuple(rows[0]), STRUCTURED_COLUMNS)
		self.assertEqual(len(rows), len(lines))
		revenue = next(row for row in rows if row["line_code"] == "PL-OP-REV")
		self.assertEqual(
			(revenue["amount"], revenue["comparative_amount"], revenue["psak201_amount"]),
			("1234567.0", "800000.0", "800000.0"),
		)
		self.assertEqual((revenue["period_from"], revenue["period_to"]), ("2026-06-01", "2026-06-30"))

		export_structured(doc.name, "xlsx")
		sheet = load_workbook(io.BytesIO(frappe.local.response.filecontent)).active
		self.assertEqual(tuple(cell.value for cell in sheet[1]), STRUCTURED_COLUMNS)
		self.assertEqual(sheet.max_row, len(lines) + 1)

	def test_a_hidden_subtotal_is_replaced_by_its_own_terms(self):
		doc = frappe._dict(
			lines=[
				frappe._dict(report_line="REV", line_type="Line", category="Operating"),
				frappe._dict(report_line="FIN", line_type="Line", category="Financing"),
			]
		)
		formulas = {"PBT": "+HIDDEN +CAT:Financing", "HIDDEN": "+CAT:Operating -GONE"}
		self.assertEqual(
			subtotal_terms(doc, {"REV", "FIN", "PBT"}, formulas, "PBT"), [(1, "REV"), (1, "FIN")]
		)


def evaluate(sheet, value) -> float:
	"""The result of a cell written by the export: a number, ``=C5-C7`` or ``=SUM(C5:C7)``."""
	if not isinstance(value, str):
		return flt(value)
	text = value.removeprefix("=")
	match = re.fullmatch(r"SUM\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)", text)
	if match:
		column = match.group(1)
		return sum(
			evaluate(sheet, sheet[f"{column}{row}"].value)
			for row in range(int(match.group(2)), int(match.group(4)) + 1)
		)
	total = 0.0
	for sign, column, row in CELL.findall(text):
		total += (-1 if sign == "-" else 1) * evaluate(sheet, sheet[f"{column}{row}"].value)
	return total
