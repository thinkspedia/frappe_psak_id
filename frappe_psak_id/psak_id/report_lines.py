"""Report line rules shared by the Report Line doctype, the installer and (later) the statement engine.

Kept free of DocType code so the formula grammar can be tested without a database.
"""

import re
from typing import NamedTuple

import frappe
from frappe import _

CATEGORIES = ("Operating", "Investing", "Financing", "Income Tax", "Discontinued Operations")
CATEGORY_PREFIX = "CAT:"

# Equity-accounted investees are always Investing, even for an entity whose main business is
# investing, so this line may never be presented in Operating.
NEVER_OPERATING_LINES = frozenset({"PL-INV-ASSOC"})

# A new term starts at a + or - that follows whitespace, so hyphens inside line codes are safe
_TERM_SPLIT = re.compile(r"\s+(?=[+-])")


class FormulaTerm(NamedTuple):
	sign: int
	kind: str  # "category" or "line"
	ref: str


class FormulaError(frappe.ValidationError):
	pass


def parse_subtotal_formula(formula: str) -> list[FormulaTerm]:
	"""Parse ``+PL-OP-REV -PL-OP-COS +CAT:Operating`` into terms.

	Every term starts with + or -. A term is a line code or ``CAT:`` followed by a category.
	"""
	text = (formula or "").strip()
	if not text:
		raise FormulaError(_("The subtotal formula is empty."))

	terms = []
	for raw in _TERM_SPLIT.split(text):
		raw = raw.strip()
		if raw[0] not in "+-" or len(raw) < 2:
			raise FormulaError(
				_(
					"Start each part of the subtotal formula with + or -, for example +PL-OP-REV. Found: {0}"
				).format(raw)
			)
		sign = 1 if raw[0] == "+" else -1
		ref = raw[1:].strip()
		if ref.upper().startswith(CATEGORY_PREFIX):
			category = ref[len(CATEGORY_PREFIX) :].strip()
			if category not in CATEGORIES:
				raise FormulaError(
					_("Unknown category {0} in the subtotal formula. Use one of: {1}.").format(
						category, ", ".join(CATEGORIES)
					)
				)
			terms.append(FormulaTerm(sign, "category", category))
		else:
			if " " in ref:
				raise FormulaError(
					_(
						"Separate each line code in the subtotal formula with a space and a sign. Found: {0}"
					).format(raw)
				)
			terms.append(FormulaTerm(sign, "line", ref))
	return terms


def find_cycle(formulas: dict[str, list[FormulaTerm]]) -> list[str] | None:
	"""Return the subtotal codes forming a loop, or None.

	``formulas`` maps each subtotal code to its parsed terms; only references to other subtotals
	can form a loop.
	"""
	visiting, done = set(), set()

	def visit(code, path):
		if code in done:
			return None
		if code in visiting:
			return [*path[path.index(code) :], code]
		visiting.add(code)
		for term in formulas.get(code, []):
			if term.kind == "line" and term.ref in formulas:
				cycle = visit(term.ref, [*path, code])
				if cycle:
					return cycle
		visiting.discard(code)
		done.add(code)
		return None

	for code in formulas:
		cycle = visit(code, [])
		if cycle:
			return cycle
	return None


# Standard PSAK 118 statement of profit or loss (PRD-001 Appendix A). Amounts are signed:
# income positive, expenses negative, so subtotals only add.
STANDARD_PROFIT_OR_LOSS_LINES = (
	{
		"line_code": "PL-OP-REV",
		"label_id": "Pendapatan",
		"label_en": "Revenue",
		"line_type": "Line",
		"category": "Operating",
		"psak201_line": "Pendapatan",
	},
	{
		"line_code": "PL-OP-COS",
		"label_id": "Beban pokok penjualan",
		"label_en": "Cost of sales",
		"line_type": "Line",
		"category": "Operating",
		"psak201_line": "Beban pokok pendapatan",
	},
	{
		"line_code": "PL-SUB-GP",
		"label_id": "Laba bruto",
		"label_en": "Gross profit",
		"line_type": "Subtotal",
		"subtotal_formula": "+PL-OP-REV +PL-OP-COS",
	},
	{
		"line_code": "PL-OP-SELL",
		"label_id": "Beban penjualan",
		"label_en": "Selling expenses",
		"line_type": "Line",
		"category": "Operating",
		"psak201_line": "Beban penjualan",
	},
	{
		"line_code": "PL-OP-GA",
		"label_id": "Beban umum dan administrasi",
		"label_en": "General and administrative expenses",
		"line_type": "Line",
		"category": "Operating",
		"psak201_line": "Beban umum dan administrasi",
	},
	{
		"line_code": "PL-OP-FTAX",
		"label_id": "Beban pajak final",
		"label_en": "Final tax expense",
		"line_type": "Line",
		"category": "Operating",
		"psak201_line": "Beban pajak final",
	},
	{
		"line_code": "PL-OP-OTH",
		"label_id": "Pendapatan (beban) operasi lain-lain",
		"label_en": "Other operating income (expenses)",
		"line_type": "Line",
		"category": "Operating",
		"is_other_items": 1,
		"psak201_line": "Pendapatan (beban) lain-lain",
	},
	{
		"line_code": "PL-SUB-OP",
		"label_id": "Laba (Rugi) Operasi",
		"label_en": "Operating profit or loss",
		"line_type": "Subtotal",
		"subtotal_formula": "+CAT:Operating",
		"mandatory": 1,
	},
	{
		"line_code": "PL-INV-ASSOC",
		"label_id": "Bagian laba entitas asosiasi dan ventura bersama",
		"label_en": "Share of profit of associates and joint ventures",
		"line_type": "Line",
		"category": "Investing",
		"psak201_line": "Bagian laba entitas asosiasi dan ventura bersama",
	},
	{
		"line_code": "PL-INV-INC",
		"label_id": "Pendapatan dari investasi",
		"label_en": "Income from investments",
		"line_type": "Line",
		"category": "Investing",
		"follows_operating": 1,
		"psak201_line": "Pendapatan keuangan",
	},
	{
		"line_code": "PL-SUB-PBFT",
		"label_id": "Laba (Rugi) sebelum Pendanaan dan Pajak Penghasilan",
		"label_en": "Profit or loss before financing and income taxes",
		"line_type": "Subtotal",
		"subtotal_formula": "+PL-SUB-OP +CAT:Investing",
		"mandatory": 1,
	},
	{
		"line_code": "PL-FIN-INT",
		"label_id": "Beban bunga pinjaman",
		"label_en": "Interest expense on borrowings",
		"line_type": "Line",
		"category": "Financing",
		"follows_operating": 1,
		"psak201_line": "Biaya keuangan",
	},
	{
		"line_code": "PL-FIN-LEASE",
		"label_id": "Beban bunga liabilitas sewa",
		"label_en": "Interest expense on lease liabilities",
		"line_type": "Line",
		"category": "Financing",
		"psak201_line": "Biaya keuangan",
	},
	{
		"line_code": "PL-FIN-OLIAB",
		"label_id": "Beban bunga atas liabilitas lain (imbalan kerja, provisi)",
		"label_en": "Interest expense on other liabilities (employee benefits, provisions)",
		"line_type": "Line",
		"category": "Financing",
		"psak201_line": "Biaya keuangan",
	},
	{
		"line_code": "PL-FIN-OTH",
		"label_id": "Beban pendanaan lain",
		"label_en": "Other financing expenses",
		"line_type": "Line",
		"category": "Financing",
		"is_other_items": 1,
		"psak201_line": "Biaya keuangan",
	},
	{
		"line_code": "PL-SUB-PBT",
		"label_id": "Laba (Rugi) sebelum Pajak Penghasilan",
		"label_en": "Profit or loss before income taxes",
		"line_type": "Subtotal",
		"subtotal_formula": "+PL-SUB-PBFT +CAT:Financing",
	},
	{
		"line_code": "PL-TAX",
		"label_id": "Beban pajak penghasilan",
		"label_en": "Income tax expense",
		"line_type": "Line",
		"category": "Income Tax",
		"psak201_line": "Beban pajak penghasilan",
	},
	{
		"line_code": "PL-SUB-CONT",
		"label_id": "Laba (Rugi) dari operasi yang dilanjutkan",
		"label_en": "Profit or loss from continuing operations",
		"line_type": "Subtotal",
		"subtotal_formula": "+PL-SUB-PBT +CAT:Income Tax",
	},
	{
		"line_code": "PL-DISC",
		"label_id": "Laba (Rugi) dari operasi yang dihentikan, setelah pajak",
		"label_en": "Profit or loss from discontinued operations, net of tax",
		"line_type": "Line",
		"category": "Discontinued Operations",
		"psak201_line": "Laba (rugi) dari operasi yang dihentikan",
	},
	{
		"line_code": "PL-SUB-PL",
		"label_id": "Laba (Rugi)",
		"label_en": "Profit or loss",
		"line_type": "Subtotal",
		"subtotal_formula": "+PL-SUB-CONT +CAT:Discontinued Operations",
		"mandatory": 1,
	},
)


def ensure_standard_report_lines():
	"""Insert standard lines that are missing; never overwrite a line the user has changed."""
	frappe.flags.psak_id_installing_standard_lines = True
	try:
		for sequence, line in enumerate(STANDARD_PROFIT_OR_LOSS_LINES, start=1):
			if frappe.db.exists("PSAK ID Report Line", line["line_code"]):
				continue
			frappe.get_doc(
				{
					"doctype": "PSAK ID Report Line",
					"statement": "Profit or Loss",
					"sequence": sequence * 10,
					**line,
				}
			).insert(ignore_permissions=True)
	finally:
		frappe.flags.psak_id_installing_standard_lines = False
