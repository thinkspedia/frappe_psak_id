# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

"""What the PDF of a PSAK ID Financial Statement shows (FR-10, Export Layout Standard).

The Print Format ``PSAK 118 Financial Statement`` renders the template
``templates/print_formats/psak_118_financial_statement.html`` from this context. The PDF is
bilingual by design, Indonesian with English below, whatever the reader's interface language:
the wording follows PSAK, so it is fixed here instead of translated. Amounts are scaled to the
statement's unit and rounded for display only (BR-22).
"""

import io

import frappe
from frappe import _
from frappe.utils import flt, format_datetime, get_fullname, getdate, now_datetime
from frappe.utils.pdf import get_pdf
from pypdf import PdfReader, PdfWriter

from frappe_psak_id.psak_id.doctype.psak_id_financial_statement.psak_id_financial_statement import (
	strip_text,
)
from frappe_psak_id.psak_id.report.psak_118_profit_or_loss.psak_118_profit_or_loss import (
	CATEGORY_LABELS,
	UNITS,
)
from frappe_psak_id.psak_id.statement import PROFIT_OR_LOSS_LINE

DOCTYPE = "PSAK ID Financial Statement"
PRINT_FORMAT = "PSAK 118 Financial Statement"
# wkhtmltopdf fills in [page] and [topage] itself: Frappe renders with JavaScript off
PAGE_FOOTER = {
	"footer-right": "Halaman [page] dari [topage] / Page [page] of [topage]",
	"footer-font-name": "DejaVu Sans",
	"footer-font-size": "7",
	"footer-spacing": "8",
}
PRINT_EVERY_STATUS = {"allow_print_for_draft": 1, "allow_print_for_cancelled": 1}
# Stamped on the pages after rendering. wkhtmltopdf cannot leave its header off page 1 with
# JavaScript off, reloads a header page (and the site's stylesheet) for every page, and places a
# fixed element on one page only.
# Read by Frappe from the page's .print-format style, which overrides margins passed in options
OVERLAY_PAGE = (
	"<style>.print-format { margin-top: 0; margin-bottom: 0; margin-left: 0; margin-right: 0; "
	"page-size: A4; }</style>"
)
RUNNING_HEADER_HTML = """<div style="position: absolute; top: 12mm; left: 20mm; width: 170mm;
	font-family: 'DejaVu Sans', sans-serif; font-size: 9pt; border-bottom: 1px solid #000;
	padding-bottom: 1mm;"><b>{company}</b><br>Laporan Laba Rugi (lanjutan) /
	<i>Statement of Profit or Loss (continued)</i></div>"""
WATERMARK_HTML = """<div style="position: absolute; top: 110mm; left: 0; width: 210mm; text-align: center;
	font-family: 'DejaVu Sans', sans-serif; font-size: {size}pt; font-weight: bold;
	color: rgba(190, 0, 0, 0.12); -webkit-transform: rotate(-35deg);">{text}</div>"""

MONTHS_ID = (
	"Januari",
	"Februari",
	"Maret",
	"April",
	"Mei",
	"Juni",
	"Juli",
	"Agustus",
	"September",
	"Oktober",
	"November",
	"Desember",
)
MONTHS_EN = (
	"January",
	"February",
	"March",
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
)
# Who signs each step of the workflow, in the words of the Approval Sheet (BR-15)
APPROVAL_STEPS = (
	("prepared_by", "prepared_on", ("Disusun oleh", "Prepared by"), ("Akuntansi", "Accounting")),
	(
		"reviewed_by",
		"reviewed_on",
		("Direviu oleh", "Reviewed by"),
		("Kepala Akuntansi", "Head of Accounting"),
	),
	("approved_by", "approved_on", ("Disetujui oleh", "Approved by"), ("CFO", "CFO")),
)


@frappe.whitelist()
def download_pdf(name: str) -> None:
	"""The statement as a PDF: letter head on page 1, running header and page numbers on every
	page after it (Export Layout Standard)."""
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("print")
	# Frappe renders the letter head into the print context; empty uses the default letter head
	letter_head = frappe.db.get_value("PSAK ID Company Policy", doc.company, "letter_head")
	# Every version prints, with its DRAFT or CANCELLED watermark, whatever Print Settings allow
	# for other documents. Frappe's print view reads these overrides from the request.
	frappe.local.form_dict.settings = PRINT_EVERY_STATUS
	html = frappe.get_print(DOCTYPE, name, print_format=PRINT_FORMAT, doc=doc, letterhead=letter_head)
	pages = PdfReader(io.BytesIO(get_pdf(html, dict(PAGE_FOOTER)))).pages

	watermark = _watermark(doc)
	watermark = (
		WATERMARK_HTML.format(size=90 if len(watermark) < 10 else 48, text=watermark) if watermark else ""
	)
	running_header = RUNNING_HEADER_HTML.format(company=frappe.utils.escape_html(doc.company))
	# Page 1 carries the letter head instead of the running header
	overlays = [_overlay(watermark) if watermark else None, _overlay(running_header + watermark)]

	writer = PdfWriter()
	for index, page in enumerate(pages):
		overlay = overlays[min(index, 1)]
		if overlay:
			# Over the content: wkhtmltopdf paints each page white, which would hide it underneath
			page.merge_page(PdfReader(io.BytesIO(overlay)).pages[0])
		writer.add_page(page)
	output = io.BytesIO()
	writer.write(output)

	frappe.local.response.filename = file_name(doc, "pdf")
	frappe.local.response.filecontent = output.getvalue()
	frappe.local.response.type = "pdf"


def file_name(doc, extension: str) -> str:
	"""``PSAK118_<company abbr>_<YYYY-MM>_<status>.<extension>``, the same for every export."""
	abbr = frappe.get_cached_value("Company", doc.company, "abbr")
	status = "Final" if doc.docstatus == 1 else ("Cancelled" if doc.docstatus == 2 else "Draft")
	return f"PSAK118_{abbr}_{getdate(doc.to_date).strftime('%Y-%m')}_{status}.{extension}"


def _overlay(html: str) -> bytes:
	return get_pdf(OVERLAY_PAGE + html)


def get_print_context(doc) -> frappe._dict:
	"""Everything the PDF prints, formatted: one section per page group, in the standard's order."""
	policy = (
		frappe.db.get_value(
			"PSAK ID Company Policy",
			doc.company,
			["show_category_headings"],
			as_dict=True,
		)
		or frappe._dict()
	)
	divisor = UNITS.get(doc.unit, 1)
	has_comparative = doc.comparative != "None"
	end = getdate(doc.to_date)

	return frappe._dict(
		company=doc.company,
		watermark=_watermark(doc),
		period=_period_phrase(end, doc.periodicity == "Annual"),
		unit=_unit_phrase(doc.unit, doc.currency),
		rounded=divisor != 1,
		columns=_columns(doc, has_comparative),
		restated_note=bool(doc.is_transition and has_comparative),
		lines=_lines(doc, divisor, has_comparative, policy.show_category_headings),
		natures=_natures(doc, divisor, has_comparative),
		transition=_transition(doc, divisor),
		other_items=_other_items(doc, divisor, has_comparative),
		approvals=_approvals(doc),
		document=doc.name,
		version=_version(doc),
		printed_on=format_datetime(now_datetime(), "dd-MM-yyyy HH:mm"),
	)


def format_amount(value, divisor: int = 1) -> str:
	"""Indonesian number format: dot thousands, negatives in parentheses, zero as a dash."""
	amount = flt(flt(value) / divisor, 0)
	if not amount:
		return "-"
	text = f"{abs(amount):,.0f}".replace(",", ".")
	return f"({text})" if amount < 0 else text


def _watermark(doc) -> str | None:
	if doc.docstatus == 1:
		return None
	return "DIBATALKAN / CANCELLED" if doc.docstatus == 2 else "DRAFT"


def _period_phrase(end, annual: bool) -> tuple[str, str]:
	day_id = f"{end.day} {MONTHS_ID[end.month - 1]} {end.year}"
	day_en = f"{end.day} {MONTHS_EN[end.month - 1]} {end.year}"
	if annual:
		return f"Untuk tahun yang berakhir {day_id}", f"For the year ended {day_en}"
	return f"Untuk periode yang berakhir {day_id}", f"For the period ended {day_en}"


def _unit_phrase(unit: str, currency: str) -> tuple[str, str]:
	name = "Rupiah" if currency == "IDR" else currency
	if unit == "Thousands":
		return (
			f"Dinyatakan dalam ribuan {name}, kecuali dinyatakan lain",
			f"Expressed in thousands of {name}, unless otherwise stated",
		)
	if unit == "Millions":
		return (
			f"Dinyatakan dalam jutaan {name}, kecuali dinyatakan lain",
			f"Expressed in millions of {name}, unless otherwise stated",
		)
	return f"Dinyatakan dalam {name}", f"Expressed in {name}"


def _period_label(start, end) -> tuple[str, str]:
	if (start.month, end.month) == (1, 12):
		return str(end.year), str(end.year)
	if start.month == end.month:
		return f"{MONTHS_ID[end.month - 1]} {end.year}", f"{MONTHS_EN[end.month - 1]} {end.year}"
	return (
		f"{MONTHS_ID[start.month - 1]} \u2013 {MONTHS_ID[end.month - 1]} {end.year}",
		f"{MONTHS_EN[start.month - 1]} \u2013 {MONTHS_EN[end.month - 1]} {end.year}",
	)


def _columns(doc, has_comparative: bool) -> list[tuple[str, str]]:
	start, end = getdate(doc.from_date), getdate(doc.to_date)
	columns = [_period_label(start, end)]
	if has_comparative:
		label_id, label_en = _period_label(start.replace(year=start.year - 1), end.replace(year=end.year - 1))
		if doc.comparative == "Restated Prior Year":
			# The asterisk points to the transition reconciliation, printed only in the first year
			mark = "*" if doc.is_transition else ""
			label_id, label_en = f"{label_id} (Disajikan kembali{mark})", f"{label_en} (Restated{mark})"
		columns.append((label_id, label_en))
	return columns


def _amounts(row, divisor: int, has_comparative: bool) -> list[str]:
	amounts = [format_amount(row.amount, divisor)]
	if has_comparative:
		amounts.append(format_amount(row.comparative_amount, divisor))
	return amounts


def _lines(doc, divisor: int, has_comparative: bool, show_headings) -> list[frappe._dict]:
	rows, heading = [], None
	for line in doc.lines:
		if show_headings and line.line_type == "Line" and line.category != heading:
			heading = line.category
			label_id, label_en = CATEGORY_LABELS.get(heading, (heading, heading))
			rows.append(frappe._dict(label_id=label_id, label_en=label_en, kind="Heading", amounts=[]))
		rows.append(
			frappe._dict(
				label_id=line.label_id or line.label_en,
				label_en=line.label_en or line.label_id,
				note=line.note_no or "",
				kind=line.line_type,
				indented=bool(show_headings and line.line_type == "Line"),
				profit_or_loss=line.report_line == PROFIT_OR_LOSS_LINE,
				amounts=[] if line.line_type == "Heading" else _amounts(line, divisor, has_comparative),
			)
		)
	return rows


def _natures(doc, divisor: int, has_comparative: bool) -> frappe._dict | None:
	"""Each nature with the function lines it is included in (BR-05, R-06)."""
	groups = {}
	for row in doc.nature_lines:
		group = groups.setdefault(
			row.expense_nature,
			frappe._dict(
				label_id=_(row.expense_nature, lang="id"),
				label_en=row.expense_nature,
				amount=0.0,
				comparative_amount=0.0,
				rows=[],
			),
		)
		group.amount += flt(row.amount)
		group.comparative_amount += flt(row.comparative_amount)
		group.rows.append(
			frappe._dict(
				label_id=row.label_id or row.label_en,
				label_en=row.label_en or row.label_id,
				amounts=_amounts(row, divisor, has_comparative),
			)
		)
	if not groups:
		return None
	total = frappe._dict(
		amount=sum(group.amount for group in groups.values()),
		comparative_amount=sum(group.comparative_amount for group in groups.values()),
	)
	for group in groups.values():
		group.amounts = _amounts(group, divisor, has_comparative)
	return frappe._dict(groups=list(groups.values()), total=_amounts(total, divisor, has_comparative))


def _transition(doc, divisor: int) -> frappe._dict | None:
	"""The prior year from PSAK 201 lines to PSAK 118 lines (BR-11), first year only."""
	if not doc.is_transition:
		return None
	groups = {}
	for row in doc.transition_lines:
		group = groups.setdefault(row.psak201_line, frappe._dict(label=row.psak201_line, amount=0.0, rows=[]))
		group.amount += flt(row.amount)
		if row.report_line:
			group.rows.append(
				frappe._dict(
					label_id=row.label_id or row.label_en,
					label_en=row.label_en or row.label_id,
					amount=format_amount(row.amount, divisor),
				)
			)
	for group in groups.values():
		group.amount = format_amount(group.amount, divisor)
	start, end = getdate(doc.from_date), getdate(doc.to_date)
	return frappe._dict(
		column=_period_label(start.replace(year=start.year - 1), end.replace(year=end.year - 1)),
		groups=list(groups.values()),
		psak201=format_amount(doc.psak201_profit_or_loss, divisor),
		restated=format_amount(doc.restated_profit_or_loss, divisor),
	)


def _other_items(doc, divisor: int, has_comparative: bool) -> frappe._dict | None:
	if not strip_text(doc.other_items_note):
		return None
	rows = [
		frappe._dict(
			label_id=line.label_id or line.label_en,
			label_en=line.label_en or line.label_id,
			amounts=_amounts(line, divisor, has_comparative),
		)
		for line in doc.lines
		if line.is_other_items
	]
	# Text Editor content is sanitised by Frappe when the statement is saved
	return frappe._dict(rows=rows, note=doc.other_items_note)


def _approvals(doc) -> list[frappe._dict]:
	return [
		frappe._dict(
			step=step,
			function=function,
			name=get_fullname(doc.get(user_field)) if doc.get(user_field) else "",
			on=format_datetime(doc.get(time_field), "dd-MM-yyyy HH:mm") if doc.get(time_field) else "",
		)
		for user_field, time_field, step, function in APPROVAL_STEPS
	]


def _version(doc) -> int:
	"""1 for the first statement of the period, plus one for each reopening (BR-08)."""
	version, amended_from = 1, doc.amended_from
	while amended_from:
		version += 1
		amended_from = frappe.db.get_value(doc.doctype, amended_from, "amended_from")
	return version
