import io
import re
import shutil
from unittest.mock import patch

import frappe
from frappe.model.workflow import apply_workflow
from pypdf import PdfReader, PdfWriter

from frappe_psak_id.psak_id.doctype.psak_id_financial_statement.psak_id_financial_statement import (
	reopen_statement,
)
from frappe_psak_id.psak_id.print_statement import PRINT_FORMAT, download_pdf, format_amount
from frappe_psak_id.tests.test_financial_statement import (
	close_period,
	make_mapping,
	make_policy,
	make_statement,
)
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	get_account,
	make_account,
	make_company,
	make_fiscal_year,
	make_journal_entry,
)

COMPANY = "_Test PSAK Print Company"


class TestPrintStatement(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COMPANY, "_TPP")
		make_fiscal_year(2025)
		make_fiscal_year(2026)
		make_policy(
			COMPANY,
			"2026-01-01",
			expense_presentation="By Function",
			other_items_threshold_percent=0,
			other_items_threshold_amount=10_000,
		)
		cash = get_account(COMPANY, "Cash")
		sales = get_account(COMPANY, "Sales")
		salary = get_account(COMPANY, "Salary")
		sundry = make_account(COMPANY, "Print Sundry", "Indirect Expenses")
		frappe.db.delete("PSAK ID Account Mapping", {"company": COMPANY})
		make_mapping(COMPANY, cash, "FP-CA-CASH")
		make_mapping(COMPANY, sales, "PL-OP-REV")
		make_mapping(COMPANY, salary, "PL-OP-GA", expense_nature="Employee Benefits")
		make_mapping(COMPANY, sundry, "PL-OP-OTH", expense_nature="Other")
		for posting_date, account, amount in (
			("2025-06-10", sales, -800_000),
			("2026-06-10", sales, -1_234_567),
			("2026-06-11", salary, 300_400),
			("2026-06-12", sundry, 25_000),
			("2025-07-10", sales, -400_000),
			("2026-07-10", sales, -500_000),
		):
			make_journal_entry(COMPANY, posting_date, account, amount, cash)

	def make_statement(self, from_date, to_date):
		return make_statement(
			COMPANY,
			from_date,
			to_date,
			comparative="Restated Prior Year",
			unit="Thousands",
			other_items_note="<p>Bank charges and stamp duty.</p>",
		).insert()

	def test_amounts_in_indonesian_format(self):
		self.assertEqual(format_amount(1_234_567), "1.234.567")
		self.assertEqual(format_amount(-1_600, 1_000), "(2)")
		self.assertEqual(format_amount(400, 1_000), "-")
		self.assertEqual(format_amount(None), "-")

	def test_draft_prints_every_section_with_a_watermark(self):
		doc = self.make_statement("2026-06-01", "2026-06-30")
		context = doc.get_print_context()
		self.assertEqual(context.watermark, "DRAFT")
		self.assertEqual(
			context.columns,
			[("Juni 2026", "June 2026"), ("Juni 2025 (Disajikan kembali*)", "June 2025 (Restated*)")],
		)
		self.assertTrue(context.restated_note)
		self.assertEqual(
			context.period, ("Untuk periode yang berakhir 30 Juni 2026", "For the period ended 30 June 2026")
		)
		lines = {row.label_en: row for row in context.lines}
		self.assertEqual(lines["Revenue"].amounts, ["1.235", "800"])
		self.assertEqual(lines["General and administrative expenses"].amounts, ["(300)", "-"])
		self.assertTrue(lines["Profit or loss"].total)
		self.assertEqual(context.title, ("Laporan Laba Rugi", "Statement of Profit or Loss"))
		# The financial position comes first, on the end date and the prior fiscal year end
		self.assertEqual(context.position.period, ("Pada 30 Juni 2026", "As at 30 June 2026"))
		self.assertEqual(
			context.position.columns,
			[
				("30 Juni 2026", "30 June 2026"),
				("31 Desember 2025 (Disajikan kembali*)", "31 December 2025 (Restated*)"),
			],
		)
		position = {row.label_en: row for row in context.position.lines}
		self.assertEqual(position["Cash and cash equivalents"].amounts, ["2.109", "1.200"])
		self.assertTrue(position["Total assets"].total)
		# Nil line items PSAK 118 does not require are left off, with the headings of nothing
		self.assertNotIn("Property, plant and equipment", position)
		self.assertNotIn("Non-current assets", position)
		self.assertIn("Total equity", position)
		self.assertEqual(
			[(group.label_en, group.amounts) for group in context.natures.groups],
			[("Employee Benefits", ["(300)", "-"]), ("Other", ["(25)", "-"])],
		)
		self.assertEqual((context.transition.psak201, context.transition.restated), ("800", "800"))
		self.assertIn("Other operating income (expenses)", [row.label_en for row in context.other_items.rows])
		self.assertEqual([approval.name for approval in context.approvals], ["", "", ""])
		self.assertEqual(context.version, 1)

		html = frappe.get_print(doc.doctype, doc.name, print_format=PRINT_FORMAT, doc=doc)
		for text in (
			"Tidak diaudit",
			"Laporan Posisi Keuangan",
			"Pada 30 Juni 2026",
			"Laporan Laba Rugi",
			"Beban Operasi menurut Sifat",
			"Rekonsiliasi Transisi PSAK 201 ke PSAK 118",
			"Rincian Pos Lain-lain",
			"Bank charges and stamp duty.",
			"Lembar Persetujuan",
			'id="footer-html"',
		):
			self.assertIn(text, html)
		self.assertNotIn("Disetujui secara elektronik", html)
		# A page break never leaves a subtotal alone: it shares a kept cell with the line above it
		kept_rows = [
			re.findall(r'<tr class="([^"]*)"', cell)
			for cell in re.findall(r'<td class="psak-keep"[^>]*><table><tbody>(.*?)</tbody>', html, re.S)
		]
		pairs = [rows for rows in kept_rows if not any("psak-total" in row for row in rows)]
		self.assertTrue(pairs)
		self.assertTrue(all(len(rows) > 1 and "psak-subtotal" in rows[-1] for rows in pairs))
		# FR-30: financial position, profit or loss, then the notes in their order
		order = [
			html.index(text)
			for text in (
				"Laporan Posisi Keuangan",
				"Statement of Profit or Loss",
				"Beban Operasi menurut Sifat",
				"Rincian Pos Lain-lain",
				"Rekonsiliasi Transisi PSAK 201 ke PSAK 118",
				"Lembar Persetujuan",
			)
		]
		self.assertEqual(order, sorted(order))

	def test_final_statement_prints_who_approved_it(self):
		# Each test has its own month: the statements of a test class stay until it ends
		doc = self.make_statement("2026-07-01", "2026-07-31")
		doc = apply_workflow(doc, "Submit for Review")
		doc = apply_workflow(doc, "Send to CFO")
		close_period(COMPANY, "2026-07-01", "2026-07-31")
		doc = apply_workflow(doc, "Approve")

		context = doc.get_print_context()
		self.assertIsNone(context.watermark)
		self.assertTrue(doc.prepared_on and doc.reviewed_on)
		self.assertEqual([approval.name for approval in context.approvals], ["Administrator"] * 3)
		self.assertTrue(all(approval.on for approval in context.approvals))
		html = frappe.get_print(doc.doctype, doc.name, print_format=PRINT_FORMAT, doc=doc)
		self.assertIn("Disetujui secara elektronik melalui ERPNext.", html)

		# CI has no wkhtmltopdf; the Dev bench renders the PDF
		if shutil.which("wkhtmltopdf"):
			self.assert_pdf(doc)

		amended = frappe.get_doc(doc.doctype, reopen_statement(doc.name, "Audit adjustment"))
		context = amended.get_print_context()
		self.assertEqual((context.version, context.watermark), (2, "DRAFT"))
		doc.reload()
		self.assertEqual(doc.get_print_context().watermark, "DIBATALKAN / CANCELLED")
		self.assert_cancelled_version_prints(doc)

	def assert_cancelled_version_prints(self, doc):
		"""The cancelled version prints with its watermark even where Print Settings keep
		cancelled documents from printing, as they do by default."""
		allowed = frappe.db.get_single_value("Print Settings", "allow_print_for_cancelled")
		frappe.db.set_single_value("Print Settings", "allow_print_for_cancelled", 0)
		self.addCleanup(frappe.db.set_single_value, "Print Settings", "allow_print_for_cancelled", allowed)
		blank = io.BytesIO()
		writer = PdfWriter()
		writer.add_blank_page(width=595, height=842)
		writer.write(blank)
		# CI has no wkhtmltopdf: render the pages blank and check the print view lets it through
		with patch("frappe_psak_id.psak_id.print_statement.get_pdf", return_value=blank.getvalue()):
			download_pdf(doc.name)
		self.assertEqual(frappe.local.response.filename, "PSAK118__TPP_2026-07_Cancelled.pdf")

	def assert_pdf(self, doc):
		download_pdf(doc.name)
		response = frappe.local.response
		self.assertEqual((response.type, response.filename), ("pdf", "PSAK118__TPP_2026-07_Final.pdf"))
		pages = [page.extract_text() for page in PdfReader(io.BytesIO(response.filecontent)).pages]
		self.assertGreaterEqual(len(pages), 6)
		# The letter head opens page 1; the running header and page numbers come after
		self.assertIn("Laporan Posisi Keuangan", pages[0])
		self.assertNotIn("(lanjutan)", pages[0])
		self.assertIn(f"Halaman 1 dari {len(pages)}", pages[0])
		self.assertIn("(lanjutan)", pages[1])
		self.assertIn("Lembar Persetujuan", pages[-1])
		self.assertNotIn("DRAFT", "".join(pages))
