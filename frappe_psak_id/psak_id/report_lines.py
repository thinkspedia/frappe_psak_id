"""Report line rules shared by the Report Line doctype, the installer and (later) the statement engine.

Kept free of DocType code so the formula grammar can be tested without a database.
"""

import re
from typing import NamedTuple

import frappe
from frappe import _

PROFIT_OR_LOSS = "Profit or Loss"
FINANCIAL_POSITION = "Financial Position"
OTHER_COMPREHENSIVE_INCOME = "Other Comprehensive Income"
CASH_FLOW = "Cash Flow"
CHANGES_IN_EQUITY = "Changes in Equity"

# The categories a line of each statement belongs to. Other comprehensive income lines have no
# category; they are split by whether they may be reclassified to profit or loss. Lines of the
# statement of changes in equity are movements, presented for every component of equity.
STATEMENT_CATEGORIES = {
	PROFIT_OR_LOSS: ("Operating", "Investing", "Financing", "Income Tax", "Discontinued Operations"),
	FINANCIAL_POSITION: ("Asset", "Liability", "Equity"),
	OTHER_COMPREHENSIVE_INCOME: (),
	CASH_FLOW: ("Operating", "Investing", "Financing"),
	CHANGES_IN_EQUITY: (),
}
CATEGORIES = tuple(
	dict.fromkeys(category for categories in STATEMENT_CATEGORIES.values() for category in categories)
)

# Cash flow lines outside the three activities, such as the opening balance and the effect of
# exchange rates on cash, have no category
OPTIONAL_CATEGORY_STATEMENTS = frozenset({CASH_FLOW})
CATEGORY_PREFIX = "CAT:"

# Assets and liabilities are split into current and non-current; equity is not
CLASSIFIED_CATEGORIES = ("Asset", "Liability")
CLASSIFICATIONS = ("Current", "Non-current")

# Equity-accounted investees are always Investing, even for an entity whose main business is
# investing, so this line may never be presented in Operating.
NEVER_OPERATING_LINES = frozenset({"PL-INV-ASSOC"})

# A new term starts at a + or - that follows whitespace, so hyphens inside line codes are safe
_TERM_SPLIT = re.compile(r"\s+(?=[+-])")


class FormulaTerm(NamedTuple):
	sign: int
	kind: str  # "category" or "line"
	ref: str
	classification: str | None = None  # only for an asset or liability category


class FormulaError(frappe.ValidationError):
	pass


def parse_subtotal_formula(formula: str) -> list[FormulaTerm]:
	"""Parse ``+PL-OP-REV -PL-OP-COS +CAT:Operating`` into terms.

	Every term starts with + or -. A term is a line code or ``CAT:`` followed by a category; an
	asset or liability category may name a classification, as in ``+CAT:Asset/Current``.
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
			category, _slash, classification = ref[len(CATEGORY_PREFIX) :].partition("/")
			category, classification = category.strip(), classification.strip() or None
			if category not in CATEGORIES:
				raise FormulaError(
					_("Unknown category {0} in the subtotal formula. Use one of: {1}.").format(
						category, ", ".join(CATEGORIES)
					)
				)
			if classification and (
				category not in CLASSIFIED_CATEGORIES or classification not in CLASSIFICATIONS
			):
				raise FormulaError(
					_(
						"Only assets and liabilities are split into {0} in the subtotal formula. Found: {1}"
					).format(" / ".join(CLASSIFICATIONS), raw)
				)
			terms.append(FormulaTerm(sign, "category", category, classification))
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


def _subtotal(code: str, label_id: str, label_en: str, formula: str, mandatory: int = 0) -> dict:
	return {
		"line_code": code,
		"label_id": label_id,
		"label_en": label_en,
		"line_type": "Subtotal",
		"subtotal_formula": formula,
		"mandatory": mandatory,
	}


def _fp_line(code, label_id, label_en, category, classification, is_other_items) -> dict:
	return {
		"line_code": code,
		"label_id": label_id,
		"label_en": label_en,
		"line_type": "Line",
		"category": category,
		"classification": classification,
		"is_other_items": is_other_items,
	}


def _oci_line(code, label_id, label_en, reclassifiable) -> dict:
	return {
		"line_code": code,
		"label_id": label_id,
		"label_en": label_en,
		"line_type": "Line",
		"reclassifiable": reclassifiable,
	}


def _cf_line(code, label_id, label_en, category, is_other_items=0, source_line=None) -> dict:
	return {
		"line_code": code,
		"label_id": label_id,
		"label_en": label_en,
		"line_type": "Line",
		"category": category,
		"is_other_items": is_other_items,
		"source_line": source_line,
	}


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


# Standard PSAK 118 statement of financial position (PRD-002 Appendix B). Assets, liabilities and
# equity are presented positive; treasury shares carry their debit balance as a negative amount.
STANDARD_FINANCIAL_POSITION_LINES = (
	*(
		_fp_line(code, label_id, label_en, "Asset", "Non-current", other)
		for code, label_id, label_en, other in (
			("FP-NCA-PPE", "Aset tetap", "Property, plant and equipment", 0),
			("FP-NCA-ROU", "Aset hak guna", "Right-of-use assets", 0),
			("FP-NCA-INVPROP", "Properti investasi", "Investment property", 0),
			("FP-NCA-GW", "Goodwill", "Goodwill", 0),
			(
				"FP-NCA-INTANG",
				"Aset takberwujud selain goodwill",
				"Intangible assets other than goodwill",
				0,
			),
			(
				"FP-NCA-ASSOC",
				"Investasi pada entitas asosiasi dan ventura bersama",
				"Investments in associates and joint ventures",
				0,
			),
			("FP-NCA-FIN", "Aset keuangan tidak lancar lain", "Other non-current financial assets", 0),
			("FP-NCA-DTA", "Aset pajak tangguhan", "Deferred tax assets", 0),
			("FP-NCA-OTH", "Aset tidak lancar lain", "Other non-current assets", 1),
		)
	),
	_subtotal("FP-SUB-NCA", "Jumlah aset tidak lancar", "Total non-current assets", "+CAT:Asset/Non-current"),
	*(
		_fp_line(code, label_id, label_en, "Asset", "Current", other)
		for code, label_id, label_en, other in (
			("FP-CA-INV", "Persediaan", "Inventories", 0),
			("FP-CA-AR", "Piutang usaha dan piutang lain", "Trade and other receivables", 0),
			("FP-CA-TAX", "Pajak dibayar dimuka", "Prepaid taxes", 0),
			("FP-CA-PREP", "Biaya dibayar dimuka dan uang muka", "Prepayments and advances", 0),
			("FP-CA-FIN", "Aset keuangan lancar lain", "Other current financial assets", 0),
			("FP-CA-CASH", "Kas dan setara kas", "Cash and cash equivalents", 0),
			("FP-CA-HFS", "Aset dimiliki untuk dijual", "Assets held for sale", 0),
			("FP-CA-OTH", "Aset lancar lain", "Other current assets", 1),
		)
	),
	_subtotal("FP-SUB-CA", "Jumlah aset lancar", "Total current assets", "+CAT:Asset/Current"),
	_subtotal("FP-SUB-TA", "Jumlah aset", "Total assets", "+FP-SUB-NCA +FP-SUB-CA", mandatory=1),
	*(
		_fp_line(code, label_id, label_en, "Liability", "Current", other)
		for code, label_id, label_en, other in (
			("FP-CL-AP", "Utang usaha dan utang lain", "Trade and other payables", 0),
			(
				"FP-CL-BORR",
				"Pinjaman jangka pendek dan bagian lancar pinjaman jangka panjang",
				"Short-term borrowings and current portion of long-term borrowings",
				0,
			),
			("FP-CL-LEASE", "Liabilitas sewa jangka pendek", "Current lease liabilities", 0),
			("FP-CL-TAX", "Utang pajak", "Taxes payable", 0),
			("FP-CL-ACCR", "Beban akrual", "Accrued expenses", 0),
			(
				"FP-CL-CONTRACT",
				"Liabilitas kontrak dan uang muka pelanggan",
				"Contract liabilities and customer advances",
				0,
			),
			("FP-CL-PROV", "Provisi jangka pendek", "Current provisions", 0),
			(
				"FP-CL-HFS",
				"Liabilitas terkait aset dimiliki untuk dijual",
				"Liabilities associated with assets held for sale",
				0,
			),
			("FP-CL-OTH", "Liabilitas jangka pendek lain", "Other current liabilities", 1),
		)
	),
	_subtotal(
		"FP-SUB-CL",
		"Jumlah liabilitas jangka pendek",
		"Total current liabilities",
		"+CAT:Liability/Current",
	),
	*(
		_fp_line(code, label_id, label_en, "Liability", "Non-current", other)
		for code, label_id, label_en, other in (
			("FP-NCL-BORR", "Pinjaman jangka panjang", "Long-term borrowings", 0),
			("FP-NCL-LEASE", "Liabilitas sewa jangka panjang", "Non-current lease liabilities", 0),
			("FP-NCL-EB", "Liabilitas imbalan kerja", "Employee benefit liabilities", 0),
			("FP-NCL-DTL", "Liabilitas pajak tangguhan", "Deferred tax liabilities", 0),
			("FP-NCL-PROV", "Provisi jangka panjang", "Non-current provisions", 0),
			("FP-NCL-OTH", "Liabilitas jangka panjang lain", "Other non-current liabilities", 1),
		)
	),
	_subtotal(
		"FP-SUB-NCL",
		"Jumlah liabilitas jangka panjang",
		"Total non-current liabilities",
		"+CAT:Liability/Non-current",
	),
	_subtotal("FP-SUB-TL", "Jumlah liabilitas", "Total liabilities", "+FP-SUB-CL +FP-SUB-NCL"),
	*(
		_fp_line(code, label_id, label_en, "Equity", None, 0)
		for code, label_id, label_en in (
			("FP-EQ-CAP", "Modal saham", "Share capital"),
			("FP-EQ-APIC", "Tambahan modal disetor", "Additional paid-in capital"),
			("FP-EQ-TREAS", "Saham treasuri", "Treasury shares"),
			("FP-EQ-OCI", "Penghasilan komprehensif lain", "Other comprehensive income reserves"),
			("FP-EQ-RE", "Saldo laba", "Retained earnings"),
			("FP-EQ-OTH", "Komponen ekuitas lain", "Other equity components"),
		)
	),
	_subtotal("FP-SUB-EQ", "Jumlah ekuitas", "Total equity", "+CAT:Equity", mandatory=1),
	_subtotal(
		"FP-SUB-TLE",
		"Jumlah liabilitas dan ekuitas",
		"Total liabilities and equity",
		"+FP-SUB-TL +FP-SUB-EQ",
		mandatory=1,
	),
)

# Standard other comprehensive income (PRD-002 Appendix E), presented below profit or loss.
# Total comprehensive income adds the profit or loss subtotal of the other statement.
STANDARD_OTHER_COMPREHENSIVE_INCOME_LINES = (
	*(
		_oci_line(code, label_id, label_en, 0)
		for code, label_id, label_en in (
			(
				"OCI-NR-REV",
				"Surplus revaluasi aset tetap",
				"Revaluation surplus on property, plant and equipment",
			),
			(
				"OCI-NR-EB",
				"Pengukuran kembali program imbalan pasti",
				"Remeasurement of defined benefit plans",
			),
			(
				"OCI-NR-FVOCI",
				"Investasi ekuitas pada nilai wajar melalui PKL",
				"Equity investments at fair value through other comprehensive income",
			),
			(
				"OCI-NR-TAX",
				"Pajak penghasilan terkait pos yang tidak akan direklasifikasi",
				"Income tax relating to items that will not be reclassified",
			),
		)
	),
	_subtotal(
		"OCI-SUB-NR",
		"Jumlah pos yang tidak akan direklasifikasi ke laba rugi",
		"Items that will not be reclassified to profit or loss",
		"+OCI-NR-REV +OCI-NR-EB +OCI-NR-FVOCI +OCI-NR-TAX",
	),
	*(
		_oci_line(code, label_id, label_en, 1)
		for code, label_id, label_en in (
			("OCI-R-FX", "Selisih kurs penjabaran", "Exchange differences on translation"),
			("OCI-R-CFH", "Lindung nilai arus kas", "Cash flow hedges"),
			(
				"OCI-R-DEBT",
				"Instrumen utang pada nilai wajar melalui PKL",
				"Debt instruments at fair value through other comprehensive income",
			),
			(
				"OCI-R-TAX",
				"Pajak penghasilan terkait pos yang dapat direklasifikasi",
				"Income tax relating to items that may be reclassified",
			),
		)
	),
	_subtotal(
		"OCI-SUB-R",
		"Jumlah pos yang dapat direklasifikasi ke laba rugi",
		"Items that may be reclassified to profit or loss",
		"+OCI-R-FX +OCI-R-CFH +OCI-R-DEBT +OCI-R-TAX",
	),
	_subtotal(
		"OCI-SUB-OCI",
		"Penghasilan komprehensif lain, setelah pajak",
		"Other comprehensive income, net of tax",
		"+OCI-SUB-NR +OCI-SUB-R",
	),
	_subtotal(
		"OCI-SUB-TCI",
		"Jumlah penghasilan komprehensif",
		"Total comprehensive income",
		"+PL-SUB-PL +OCI-SUB-OCI",
		mandatory=1,
	),
)

# Standard PSAK 118 statement of cash flows, indirect method (PRD-002 Appendix C). Inflows are
# positive and outflows negative. Operating cash flows start from operating profit or loss.
STANDARD_CASH_FLOW_LINES = (
	_cf_line(
		"CF-OP-START", "Laba (Rugi) Operasi", "Operating profit or loss", "Operating", source_line="PL-SUB-OP"
	),
	*(
		_cf_line(code, label_id, label_en, "Operating", other)
		for code, label_id, label_en, other in (
			("CF-OP-DEP", "Penyusutan dan amortisasi", "Depreciation and amortisation", 0),
			("CF-OP-IMP", "Rugi (pemulihan) penurunan nilai", "Impairment losses (reversals)", 0),
			("CF-OP-FX", "Selisih kurs belum direalisasi", "Unrealised exchange differences", 0),
			("CF-OP-ADJ", "Penyesuaian nonkas lain", "Other non-cash adjustments", 1),
			(
				"CF-OP-WC-AR",
				"Perubahan piutang usaha dan piutang lain",
				"Change in trade and other receivables",
				0,
			),
			("CF-OP-WC-INV", "Perubahan persediaan", "Change in inventories", 0),
			("CF-OP-WC-OA", "Perubahan aset lain", "Change in other assets", 0),
			("CF-OP-WC-AP", "Perubahan utang usaha dan utang lain", "Change in trade and other payables", 0),
			("CF-OP-WC-OL", "Perubahan liabilitas lain", "Change in other liabilities", 0),
			("CF-OP-TAX", "Pajak penghasilan dibayar", "Income taxes paid", 0),
		)
	),
	_subtotal(
		"CF-SUB-OP",
		"Arus kas neto dari aktivitas operasi",
		"Net cash from operating activities",
		"+CAT:Operating",
		mandatory=1,
	),
	*(
		_cf_line(code, label_id, label_en, "Investing", other)
		for code, label_id, label_en, other in (
			("CF-INV-PPE-BUY", "Perolehan aset tetap", "Purchase of property, plant and equipment", 0),
			(
				"CF-INV-PPE-SELL",
				"Hasil pelepasan aset tetap",
				"Proceeds from disposal of property, plant and equipment",
				0,
			),
			("CF-INV-INTANG", "Perolehan aset takberwujud", "Purchase of intangible assets", 0),
			("CF-INV-FIN-BUY", "Penempatan investasi", "Purchase of investments", 0),
			("CF-INV-FIN-SELL", "Pencairan investasi", "Proceeds from investments", 0),
			("CF-INV-INT", "Bunga diterima", "Interest received", 0),
			("CF-INV-DIV", "Dividen diterima", "Dividends received", 0),
			("CF-INV-OTH", "Arus kas investasi lain", "Other investing cash flows", 1),
		)
	),
	_subtotal(
		"CF-SUB-INV",
		"Arus kas neto dari aktivitas investasi",
		"Net cash from investing activities",
		"+CAT:Investing",
		mandatory=1,
	),
	*(
		_cf_line(code, label_id, label_en, "Financing", other)
		for code, label_id, label_en, other in (
			("CF-FIN-BORR-IN", "Penerimaan pinjaman", "Proceeds from borrowings", 0),
			("CF-FIN-BORR-OUT", "Pembayaran pinjaman", "Repayment of borrowings", 0),
			("CF-FIN-LEASE", "Pembayaran pokok liabilitas sewa", "Payment of lease liabilities", 0),
			("CF-FIN-INT", "Bunga dibayar", "Interest paid", 0),
			("CF-FIN-DIV", "Dividen dibayar", "Dividends paid", 0),
			("CF-FIN-EQ", "Penerimaan dari penerbitan saham", "Proceeds from issuing shares", 0),
			("CF-FIN-OTH", "Arus kas pendanaan lain", "Other financing cash flows", 1),
		)
	),
	_subtotal(
		"CF-SUB-FIN",
		"Arus kas neto dari aktivitas pendanaan",
		"Net cash from financing activities",
		"+CAT:Financing",
		mandatory=1,
	),
	_subtotal(
		"CF-SUB-NET",
		"Kenaikan (penurunan) neto kas dan setara kas",
		"Net increase (decrease) in cash and cash equivalents",
		"+CF-SUB-OP +CF-SUB-INV +CF-SUB-FIN",
	),
	_cf_line(
		"CF-FX",
		"Efek perubahan kurs atas kas dan setara kas",
		"Effect of exchange rate changes on cash and cash equivalents",
		None,
	),
	_cf_line(
		"CF-OPEN",
		"Kas dan setara kas awal periode",
		"Cash and cash equivalents at the beginning of the period",
		None,
	),
	_subtotal(
		"CF-SUB-CLOSE",
		"Kas dan setara kas akhir periode",
		"Cash and cash equivalents at the end of the period",
		"+CF-SUB-NET +CF-FX +CF-OPEN",
		mandatory=1,
	),
)


def _eq_line(code, label_id, label_en, is_other_items=0, source_line=None, mandatory=0) -> dict:
	return {
		"line_code": code,
		"label_id": label_id,
		"label_en": label_en,
		"line_type": "Line",
		"is_other_items": is_other_items,
		"source_line": source_line,
		"mandatory": mandatory,
	}


# Standard PSAK 118 statement of changes in equity (PRD-002 Appendix D). Each line is presented
# for every component of equity (the equity lines of the statement of financial position);
# increases are positive and decreases negative.
STANDARD_CHANGES_IN_EQUITY_LINES = (
	_eq_line("EQ-OPEN", "Saldo awal", "Balance at the beginning of the period", mandatory=1),
	_eq_line("EQ-PL", "Laba (rugi)", "Profit or loss", source_line="PL-SUB-PL"),
	_eq_line(
		"EQ-OCI", "Penghasilan komprehensif lain", "Other comprehensive income", source_line="OCI-SUB-OCI"
	),
	_subtotal(
		"EQ-SUB-TCI",
		"Jumlah penghasilan komprehensif",
		"Total comprehensive income",
		"+EQ-PL +EQ-OCI",
		mandatory=1,
	),
	_eq_line("EQ-DIV", "Dividen", "Dividends"),
	_eq_line("EQ-ISSUE", "Penerbitan saham", "Issue of shares"),
	_eq_line("EQ-TREAS", "Saham treasuri", "Treasury shares"),
	_eq_line("EQ-TRANSFER", "Transfer antar komponen ekuitas", "Transfers between components of equity"),
	_eq_line("EQ-OTH", "Lainnya", "Other changes", is_other_items=1),
	_subtotal(
		"EQ-CLOSE",
		"Saldo akhir",
		"Balance at the end of the period",
		"+EQ-OPEN +EQ-SUB-TCI +EQ-DIV +EQ-ISSUE +EQ-TREAS +EQ-TRANSFER +EQ-OTH",
		mandatory=1,
	),
)

# Profit or loss first: total comprehensive income, the cash flow starting line and the changes in
# equity refer to it
STANDARD_LINES = {
	PROFIT_OR_LOSS: STANDARD_PROFIT_OR_LOSS_LINES,
	FINANCIAL_POSITION: STANDARD_FINANCIAL_POSITION_LINES,
	OTHER_COMPREHENSIVE_INCOME: STANDARD_OTHER_COMPREHENSIVE_INCOME_LINES,
	CASH_FLOW: STANDARD_CASH_FLOW_LINES,
	CHANGES_IN_EQUITY: STANDARD_CHANGES_IN_EQUITY_LINES,
}


def ensure_standard_report_lines():
	"""Insert standard lines that are missing; never overwrite a line the user has changed."""
	frappe.flags.psak_id_installing_standard_lines = True
	try:
		for statement, lines in STANDARD_LINES.items():
			for sequence, line in enumerate(lines, start=1):
				if frappe.db.exists("PSAK ID Report Line", line["line_code"]):
					continue
				frappe.get_doc(
					{
						"doctype": "PSAK ID Report Line",
						"statement": statement,
						"sequence": sequence * 10,
						**line,
					}
				).insert(ignore_permissions=True)
	finally:
		frappe.flags.psak_id_installing_standard_lines = False
