# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

"""Excel and structured data exports of a PSAK ID Financial Statement (FR-10, BR-14).

The Excel workbook follows the Export Layout Standard: the same title block and wording as the
PDF, amounts stored in full with the unit applied by the number format, and subtotals written as
formulas over the cells of the lines they add up, so the workbook still adds up when an auditor
changes a line. The structured data is one row per line with fixed English column names: the
contract later releases map to XBRL.
"""

import csv
import io

import frappe
from frappe.utils import flt, getdate, now_datetime
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

from frappe_psak_id.psak_id.print_statement import DOCTYPE, file_name, get_print_context
from frappe_psak_id.psak_id.report.psak_118_profit_or_loss.psak_118_profit_or_loss import CATEGORY_LABELS
from frappe_psak_id.psak_id.report_lines import parse_subtotal_formula
from frappe_psak_id.psak_id.statement import PROFIT_OR_LOSS_LINE

# Amounts are stored in full; thousands and millions are shown by scaling in the number format
NUMBER_FORMATS = {
	"Full": '#,##0;(#,##0);"-"',
	"Thousands": '#,##0,;(#,##0,);"-"',
	"Millions": '#,##0,,;(#,##0,,);"-"',
}
STRUCTURED_COLUMNS = (
	"line_code",
	"label_id",
	"label_en",
	"category",
	"line_type",
	"period_from",
	"period_to",
	"amount",
	"comparative_amount",
	"psak201_amount",
	"unit",
	"currency",
	"company",
	"statement_name",
	"status",
)
LABEL_WIDTH, NOTE_WIDTH, AMOUNT_WIDTH = 48, 10, 18
A4 = 9  # openpyxl paper size code

BOLD = Font(bold=True)
ITALIC = Font(italic=True)
THIN = Side(style="thin")
TOP_LINE = Border(top=THIN)
PROFIT_OR_LOSS_LINES = Border(top=THIN, bottom=Side(style="double"))


@frappe.whitelist()
def export_excel(name: str) -> None:
	"""The statement as an Excel workbook: Profit or Loss, Expenses by Nature and Transition
	Reconciliation when the statement has them, and an Info sheet."""
	doc = _get_statement(name)
	context = get_print_context(doc)
	number_format = NUMBER_FORMATS.get(doc.unit, NUMBER_FORMATS["Full"])

	workbook = Workbook()
	_profit_or_loss_sheet(workbook.active, doc, context, number_format)
	if doc.nature_lines:
		_nature_sheet(workbook.create_sheet(), doc, context, number_format)
	if doc.is_transition:
		_transition_sheet(workbook.create_sheet(), doc, context, number_format)
	_info_sheet(workbook.create_sheet(), doc, context)

	output = io.BytesIO()
	workbook.save(output)
	_respond(file_name(doc, "xlsx"), output.getvalue())


@frappe.whitelist()
def export_structured(name: str, fmt: str = "xlsx") -> None:
	"""One row per line of the statement, amounts in full (BR-14)."""
	if fmt not in ("xlsx", "csv"):
		frappe.throw(frappe._("Choose Excel or CSV."))
	doc = _get_statement(name)
	rows = [[row[column] for column in STRUCTURED_COLUMNS] for row in get_structured_rows(doc)]
	base = file_name(doc, fmt).rsplit(".", 1)[0]

	if fmt == "csv":
		output = io.StringIO()
		writer = csv.writer(output, lineterminator="\n")
		writer.writerow(STRUCTURED_COLUMNS)
		writer.writerows(rows)
		_respond(f"{base}_data.csv", output.getvalue().encode("utf-8"))
		return

	workbook = Workbook()
	sheet = workbook.active
	sheet.title = "Data"
	sheet.append(STRUCTURED_COLUMNS)
	for cell in sheet[1]:
		cell.font = BOLD
	for row in rows:
		sheet.append(row)
	sheet.freeze_panes = "A2"
	sheet.auto_filter.ref = f"A1:{get_column_letter(len(STRUCTURED_COLUMNS))}{len(rows) + 1}"
	output = io.BytesIO()
	workbook.save(output)
	_respond(f"{base}_data.xlsx", output.getvalue())


def get_structured_rows(doc) -> list[dict]:
	"""Every line with an amount; the PSAK 201 amount only in the transition year, from the
	transition reconciliation."""
	psak201 = {}
	for row in doc.transition_lines if doc.is_transition else ():
		if row.report_line:
			psak201[row.report_line] = flt(psak201.get(row.report_line)) + flt(row.amount)
	has_comparative = doc.comparative != "None"
	return [
		{
			"line_code": line.report_line,
			"label_id": line.label_id or "",
			"label_en": line.label_en or "",
			"category": line.category or "",
			"line_type": line.line_type,
			"period_from": str(getdate(doc.from_date)),
			"period_to": str(getdate(doc.to_date)),
			"amount": flt(line.amount, 2),
			"comparative_amount": flt(line.comparative_amount, 2) if has_comparative else None,
			"psak201_amount": flt(psak201.get(line.report_line), 2) if doc.is_transition else None,
			"unit": doc.unit,
			"currency": doc.currency,
			"company": doc.company,
			"statement_name": doc.name,
			"status": doc.workflow_state,
		}
		for line in doc.lines
		if line.line_type != "Heading"
	]


def subtotal_terms(doc, line_codes: set, formulas: dict, code: str) -> list[tuple[int, str]]:
	"""The lines of the statement a subtotal adds up, with their signs.

	A subtotal left off the statement (hidden, BR-20) is replaced by its own terms, a category by
	its lines, and a line not on the statement counts as zero.
	"""
	terms = []
	for term in parse_subtotal_formula(formulas[code]):
		if term.kind == "category":
			terms.extend(
				(term.sign, line.report_line)
				for line in doc.lines
				if line.line_type == "Line" and line.category == term.ref
			)
		elif term.ref in line_codes:
			terms.append((term.sign, term.ref))
		elif formulas.get(term.ref):
			terms.extend(
				(term.sign * sign, ref) for sign, ref in subtotal_terms(doc, line_codes, formulas, term.ref)
			)
	return terms


def _get_statement(name: str):
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("export")
	return doc


def _respond(filename: str, content: bytes) -> None:
	frappe.local.response.filename = filename
	frappe.local.response.filecontent = content
	frappe.local.response.type = "binary"


def _profit_or_loss_sheet(sheet, doc, context, number_format):
	sheet.title = "Laba Rugi"
	amount_fields = _amount_columns(doc)
	width = 3 + len(amount_fields)
	header = _title_block(sheet, context, ("Laporan Laba Rugi", "Statement of Profit or Loss"), width)
	_header_row(sheet, header, ("Pos", "Line item", "Catatan / Notes"), context.columns)
	_layout(sheet, header, [LABEL_WIDTH, LABEL_WIDTH, NOTE_WIDTH] + [AMOUNT_WIDTH] * len(amount_fields))

	show_headings = frappe.db.get_value("PSAK ID Company Policy", doc.company, "show_category_headings")
	formulas = dict(
		frappe.get_all(
			"PSAK ID Report Line",
			filters={"line_type": "Subtotal"},
			fields=["name", "subtotal_formula"],
			as_list=True,
		)
	)
	lines = [line for line in doc.lines if line.line_type != "Heading"]
	line_codes = {line.report_line for line in lines}
	row_of, rows, heading = {}, [], None
	for line in doc.lines:
		if show_headings and line.line_type == "Line" and line.category != heading:
			heading = line.category
			rows.append(("Heading", CATEGORY_LABELS.get(heading, (heading, heading)), None))
		rows.append((line.line_type, (line.label_id or line.label_en, line.label_en or line.label_id), line))

	row_number = header
	for kind, labels, line in rows:
		row_number += 1
		_labels(sheet, row_number, labels, indented=bool(show_headings and kind == "Line"))
		if kind == "Heading" or line.line_type == "Heading":
			sheet.cell(row_number, 1).font = BOLD
			continue
		row_of[line.report_line] = row_number
		sheet.cell(row_number, 3, line.note_no or None)

	amounts = {field: {line.report_line: flt(line.get(field)) for line in lines} for field in amount_fields}
	for line in lines:
		row_number = row_of[line.report_line]
		terms = (
			subtotal_terms(doc, line_codes, formulas, line.report_line)
			if line.line_type == "Subtotal" and formulas.get(line.report_line)
			else None
		)
		for index, field in enumerate(amount_fields):
			cell = sheet.cell(row_number, 4 + index)
			cell.value = _formula_or_value(terms, flt(line.get(field)), amounts[field], row_of, 4 + index)
			cell.number_format = number_format
			if line.line_type == "Subtotal":
				cell.border = PROFIT_OR_LOSS_LINES if line.report_line == PROFIT_OR_LOSS_LINE else TOP_LINE
		if line.line_type == "Subtotal":
			for column in (1, 2):
				sheet.cell(row_number, column).font = Font(bold=True, italic=column == 2)

	footnotes = []
	if context.restated_note:
		footnotes.append(
			(
				"* Disajikan kembali dengan pemetaan PSAK 118; lihat Rekonsiliasi Transisi.",
				"* Restated with the PSAK 118 mappings; see the Transition Reconciliation.",
			)
		)
	if context.rounded:
		footnotes.append(
			(
				"Selisih penjumlahan dapat timbul karena pembulatan.",
				"Totals may differ from the sum of their parts because of rounding.",
			)
		)
	row_number = sheet.max_row + 1
	# One language per row: a long note spills over the empty cells to its right
	for label_id, label_en in footnotes:
		sheet.cell(row_number + 1, 1, label_id)
		sheet.cell(row_number + 2, 1, label_en).font = ITALIC
		row_number += 2


def _nature_sheet(sheet, doc, context, number_format):
	sheet.title = "Beban per Sifat"
	columns = _amount_columns(doc)
	header = _title_block(
		sheet, context, ("Beban Operasi menurut Sifat", "Operating Expenses by Nature"), 2 + len(columns)
	)
	_header_row(sheet, header, ("Sifat / pos fungsi", "Nature / function line"), context.columns)
	_layout(sheet, header, [LABEL_WIDTH, LABEL_WIDTH] + [AMOUNT_WIDTH] * len(columns))

	group_rows, row_number = [], header
	for group in context.natures.groups:
		row_number += 1
		group_row = row_number
		group_rows.append(group_row)
		_labels(sheet, group_row, (group.label_id, group.label_en), bold=True)
		details = [row for row in doc.nature_lines if row.expense_nature == group.label_en]
		for row in details:
			row_number += 1
			_labels(
				sheet, row_number, (row.label_id or row.label_en, row.label_en or row.label_id), indented=True
			)
			for index, field in enumerate(columns):
				cell = sheet.cell(row_number, 3 + index, flt(row.get(field), 2))
				cell.number_format = number_format
		for index in range(len(columns)):
			letter = get_column_letter(3 + index)
			cell = sheet.cell(group_row, 3 + index, f"=SUM({letter}{group_row + 1}:{letter}{row_number})")
			cell.number_format = number_format
			cell.font = BOLD

	row_number += 1
	_labels(
		sheet,
		row_number,
		("Jumlah beban operasi menurut sifat", "Total operating expenses by nature"),
		bold=True,
	)
	for index in range(len(columns)):
		letter = get_column_letter(3 + index)
		cell = sheet.cell(row_number, 3 + index, "=" + "+".join(f"{letter}{row}" for row in group_rows))
		cell.number_format = number_format
		cell.font = BOLD
		cell.border = PROFIT_OR_LOSS_LINES


def _transition_sheet(sheet, doc, context, number_format):
	sheet.title = "Rekonsiliasi Transisi"
	title = (
		"Rekonsiliasi Transisi PSAK 201 ke PSAK 118",
		"Transition Reconciliation from PSAK 201 to PSAK 118",
	)
	header = _title_block(sheet, context, title, 3)
	_header_row(
		sheet,
		header,
		("Pos PSAK 201 / pos PSAK 118", "PSAK 201 line / PSAK 118 line"),
		[context.transition.column],
	)
	_layout(sheet, header, [LABEL_WIDTH, LABEL_WIDTH, AMOUNT_WIDTH])

	groups = {}
	for row in doc.transition_lines:
		groups.setdefault(row.psak201_line, []).append(row)
	group_rows, detail_rows, row_number = [], [], header
	for psak201_line, rows in groups.items():
		row_number += 1
		group_row = row_number
		group_rows.append(group_row)
		_labels(sheet, group_row, (psak201_line, None), bold=True)
		details = [row for row in rows if row.report_line]
		for row in details:
			row_number += 1
			detail_rows.append(row_number)
			_labels(
				sheet, row_number, (row.label_id or row.label_en, row.label_en or row.label_id), indented=True
			)
			sheet.cell(row_number, 3, flt(row.amount, 2)).number_format = number_format
		# An account without a mapping has no PSAK 118 line to list: its group shows the amount
		value = (
			f"=SUM(C{group_row + 1}:C{row_number})"
			if len(details) == len(rows)
			else flt(sum(flt(row.amount) for row in rows), 2)
		)
		cell = sheet.cell(group_row, 3, value)
		cell.number_format = number_format
		cell.font = BOLD

	totals = (
		(("Laba (rugi) menurut PSAK 201", "Profit (loss) under PSAK 201"), group_rows, TOP_LINE),
		(
			("Laba (rugi) disajikan kembali menurut PSAK 118", "Profit (loss) restated under PSAK 118"),
			detail_rows,
			PROFIT_OR_LOSS_LINES,
		),
	)
	for labels, rows, border in totals:
		row_number += 1
		_labels(sheet, row_number, labels, bold=True)
		cell = sheet.cell(row_number, 3, "=" + "+".join(f"C{row}" for row in rows) if rows else 0)
		cell.number_format = number_format
		cell.font = BOLD
		cell.border = border


def _info_sheet(sheet, doc, context):
	sheet.title = "Info"
	approvals = [
		(approval.step, " ".join(part for part in (approval.name, approval.on) if part))
		for approval in context.approvals
	]
	rows = [
		(("Perusahaan", "Company"), doc.company),
		(("Periode", "Period"), f"{getdate(doc.from_date)} - {getdate(doc.to_date)}"),
		(("Buku keuangan", "Finance book"), doc.finance_book or ""),
		(("Status", "Status"), doc.workflow_state),
		(("Dokumen", "Document"), doc.name),
		(("Versi", "Version"), context.version),
		*approvals,
		(("Waktu ekspor", "Exported on"), now_datetime().strftime("%Y-%m-%d %H:%M")),
	]
	for row_number, ((label_id, label_en), value) in enumerate(rows, start=1):
		sheet.cell(row_number, 1, label_id).font = BOLD
		sheet.cell(row_number, 2, label_en).font = ITALIC
		sheet.cell(row_number, 3, value)
	_layout(sheet, None, [24, 24, LABEL_WIDTH])


def _title_block(sheet, context, title, width) -> int:
	"""Company, title, period, unit and status, each centred across the table; returns the row
	of the column headers."""
	lines = [
		(context.company, BOLD),
		(title[0], BOLD),
		(title[1], Font(bold=True, italic=True)),
		(context.period[0], None),
		(context.period[1], ITALIC),
		(context.unit[0], None),
		(context.unit[1], ITALIC),
		("Tidak diaudit / Unaudited", ITALIC),
	]
	if context.watermark:
		lines.append((context.watermark, Font(bold=True, color="BE0000")))
	for row_number, (text, font) in enumerate(lines, start=1):
		sheet.cell(row_number, 1, text)
		if font:
			sheet.cell(row_number, 1).font = font
		# Centre across selection instead of merged cells, which break sorting and copying
		for column in range(1, width + 1):
			sheet.cell(row_number, column).alignment = Alignment(horizontal="centerContinuous")
	return len(lines) + 2


def _header_row(sheet, row_number, labels, columns):
	for column, label in enumerate(
		[*labels, *(f"{label_id}\n{label_en}" for label_id, label_en in columns)], 1
	):
		cell = sheet.cell(row_number, column, label)
		cell.font = BOLD
		cell.border = Border(bottom=THIN)
		cell.alignment = Alignment(
			wrap_text=True, vertical="bottom", horizontal="right" if column > len(labels) else None
		)


def _layout(sheet, header, widths):
	for column, width in enumerate(widths, 1):
		sheet.column_dimensions[get_column_letter(column)].width = width
	sheet.page_setup.paperSize = A4
	sheet.page_setup.orientation = "portrait"
	sheet.page_setup.fitToWidth = 1
	sheet.page_setup.fitToHeight = 0
	sheet.sheet_properties.pageSetUpPr.fitToPage = True
	sheet.oddFooter.right.text = "Halaman &P dari &N / Page &P of &N"
	if header:
		sheet.freeze_panes = sheet.cell(header + 1, 1)
		sheet.print_title_rows = f"{header}:{header}"


def _labels(sheet, row_number, labels, indented=False, bold=False):
	label_id, label_en = labels
	cell = sheet.cell(row_number, 1, label_id)
	cell.font = Font(bold=bold)
	if indented:
		cell.alignment = Alignment(indent=1)
	if label_en:
		cell = sheet.cell(row_number, 2, label_en)
		cell.font = Font(bold=bold, italic=True)
		if indented:
			cell.alignment = Alignment(indent=1)


def _amount_columns(doc) -> list[str]:
	return ["amount", "comparative_amount"] if doc.comparative != "None" else ["amount"]


def _formula_or_value(terms, amount: float, amounts: dict, row_of: dict, column: int):
	"""A formula over the cells of the subtotal's lines, or the stored amount when there is no
	formula or it does not give the stored amount (the report line's formula changed after the
	statement was computed)."""
	if terms is None:
		return flt(amount, 2)
	if flt(sum(sign * amounts.get(code, 0.0) for sign, code in terms) - amount, 2):
		return flt(amount, 2)
	if not terms:
		return 0
	letter = get_column_letter(column)
	formula = "".join(f"{'+' if sign > 0 else '-'}{letter}{row_of[code]}" for sign, code in terms)
	return "=" + formula.removeprefix("+")
