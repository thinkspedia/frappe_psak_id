"""Standard mapping templates, one per industry, installed with the app.

Each template is an ordered list of account name patterns (English names of ERPNext's standard
chart and common Indonesian names) and the PSAK 118 line they map to. The first matching row wins,
so specific patterns come first: final tax before income tax, lease interest before other
interest, project costs before general rent and travel, and the catch-all "other" rows last.
Accounts no row matches stay unmapped and show in the Mapping Control report; a template is a
starting point the accountant reviews, not a classification the app decides on its own.
"""

import frappe

STANDARD_TEMPLATE_VERSION = "1.0"

INCOME, EXPENSE = "Income", "Expense"
RAW_MATERIALS = "Raw Materials and Goods"
EMPLOYEE_BENEFITS = "Employee Benefits"
DEPRECIATION = "Depreciation"
AMORTISATION = "Amortisation"
IMPAIRMENT = "Impairment Losses (Reversals)"
INVENTORY_WRITE_DOWNS = "Inventory Write-downs (Reversals)"
OTHER = "Other"


def _rows(root_type, patterns, report_line, expense_nature=None, is_final_tax=0) -> list[dict]:
	return [
		{
			"root_type": root_type,
			"match_on": "Name",
			"account_pattern": pattern,
			"report_line": report_line,
			"expense_nature": expense_nature,
			"is_final_tax": is_final_tax,
		}
		for pattern in patterns
	]


# PPh final is not income tax (PSAK 212): it follows the income it is levied on (BR-21)
FINAL_TAX = [
	*_rows(
		EXPENSE,
		("*final*bunga*", "*bunga*final*", "*final*deposit*", "*final*interest*"),
		"PL-INV-INC",
		is_final_tax=1,
	),
	*_rows(
		EXPENSE,
		("*pph final*", "*pajak*final*", "*penghasilan*final*", "*final tax*", "*pph pasal 4*"),
		"PL-OP-FTAX",
		OTHER,
		is_final_tax=1,
	),
]

INCOME_TAX = [
	# Taxes that are not on income stay operating expenses
	*_rows(EXPENSE, ("*pajak bumi*", "*property tax*", "*pbb*"), "PL-OP-GA", OTHER),
	*_rows(
		EXPENSE,
		(
			"*income tax*",
			"*pajak penghasilan*",
			"*pph badan*",
			"*pph pasal 25*",
			"*pph pasal 29*",
			"*corporate tax*",
			"*deferred tax*",
			"*pajak tangguhan*",
			"*tax expense*",
		),
		"PL-TAX",
	),
]

FINANCING = [
	*_rows(
		EXPENSE,
		("*interest*lease*", "*lease*interest*", "*bunga*sewa*", "*bunga*liabilitas sewa*"),
		"PL-FIN-LEASE",
	),
	*_rows(
		EXPENSE,
		(
			"*interest*employee benefit*",
			"*bunga*imbalan*",
			"*interest cost*",
			"*unwinding*",
			"*bunga*provisi*",
		),
		"PL-FIN-OLIAB",
	),
	*_rows(
		EXPENSE,
		("*interest expense*", "*beban bunga*", "*bunga pinjaman*", "*loan interest*", "*interest on loan*"),
		"PL-FIN-INT",
	),
	*_rows(EXPENSE, ("*loan*fee*", "*provisi pinjaman*"), "PL-FIN-OTH"),
]

INVESTING_INCOME = [
	*_rows(
		INCOME,
		(
			"*share of*associate*",
			"*share of*joint venture*",
			"*bagian laba*asosiasi*",
			"*bagian laba*ventura*",
			"*equity method*",
		),
		"PL-INV-ASSOC",
	),
	*_rows(
		INCOME,
		(
			"*interest income*",
			"*interest*deposit*",
			"*bank interest*",
			"*pendapatan bunga*",
			"*bunga deposito*",
			"*jasa giro*",
			"*dividend*",
			"*dividen*",
			"*gain*investment*",
			"*laba*investasi*",
		),
		"PL-INV-INC",
	),
]

# Exchange differences on trade receivables and payables, disposals of operating assets and
# rounding are operating; review exchange differences on borrowings (Financing, BR-18)
OTHER_OPERATING = _rows(
	None,
	(
		"*exchange*",
		"*selisih kurs*",
		"*laba*kurs*",
		"*rugi*kurs*",
		"*forex*",
		"*disposal*",
		"*pelepasan aset*",
		"*penjualan aset*",
		"round off",
		"*pembulatan*",
		"write off",
	),
	"PL-OP-OTH",
	OTHER,
)

SELLING = _rows(
	EXPENSE,
	(
		"*commission*",
		"*komisi*",
		"*marketing*",
		"*pemasaran*",
		"*advertis*",
		"*iklan*",
		"*promosi*",
		"*promotion*",
		"*sales expense*",
		"*beban penjualan*",
		"*selling*",
		"*freight*",
		"*forwarding*",
		"*pengiriman*",
		"*ongkos kirim*",
	),
	"PL-OP-SELL",
	OTHER,
)

GENERAL_AND_ADMINISTRATIVE = [
	*_rows(EXPENSE, ("*depreciation*", "*penyusutan*"), "PL-OP-GA", DEPRECIATION),
	*_rows(EXPENSE, ("*amorti*",), "PL-OP-GA", AMORTISATION),
	*_rows(
		EXPENSE,
		(
			"*impairment*",
			"*penurunan nilai*",
			"*bad debt*",
			"*doubtful*",
			"*piutang tak tertagih*",
			"*kerugian kredit*",
			"*expected credit loss*",
		),
		"PL-OP-GA",
		IMPAIRMENT,
	),
	*_rows(
		EXPENSE,
		(
			"salary",
			"*salaries*",
			"*gaji*",
			"*wage*",
			"*upah*",
			"*tunjangan*",
			"*allowance*",
			"*bonus*",
			"*bpjs*",
			"*pension*",
			"*pensiun*",
			"*imbalan kerja*",
			"*employee benefit*",
			"*pesangon*",
			"*severance*",
		),
		"PL-OP-GA",
		EMPLOYEE_BENEFITS,
	),
	*_rows(
		EXPENSE,
		(
			"*bank charge*",
			"*biaya bank*",
			"*administrasi bank*",
			"*administrative*",
			"*administrasi*",
			"*office*",
			"*kantor*",
			"*rent*",
			"*sewa*",
			"*utilit*",
			"*listrik*",
			"*electric*",
			"*telephone*",
			"*telepon*",
			"*internet*",
			"*legal*",
			"*professional*",
			"*konsultan*",
			"*audit*",
			"*print*",
			"*cetak*",
			"*postal*",
			"*stationery*",
			"*alat tulis*",
			"*entertain*",
			"*representasi*",
			"*jamuan*",
			"*insurance*",
			"*asuransi*",
			"*travel*",
			"*perjalanan*",
			"*transport*",
			"*maintenance*",
			"*pemeliharaan*",
			"*perbaikan*",
			"*repair*",
			"*license*",
			"*perizinan*",
			"*training*",
			"*pelatihan*",
			"*donation*",
			"*sumbangan*",
			"*fuel*",
			"*bahan bakar*",
		),
		"PL-OP-GA",
		OTHER,
	),
]

# Last: anything named "other" or "miscellaneous" that no specific row took (BR-06 watches it)
MISCELLANEOUS = _rows(
	None,
	(
		"*miscellaneous*",
		"*lain-lain*",
		"*other income*",
		"*other expense*",
		"*pendapatan lain*",
		"*beban lain*",
	),
	"PL-OP-OTH",
	OTHER,
)

# Valuation offsets of landed costs and stock adjustments belong with the cost of sales
VALUATION = _rows(
	EXPENSE,
	("expenses included in*", "stock adjustment", "*selisih persediaan*"),
	"PL-OP-COS",
	RAW_MATERIALS,
)

INVENTORY_WRITE_DOWN = _rows(
	EXPENSE,
	("*inventory write*", "*penurunan nilai persediaan*", "*persediaan usang*", "*obsolete*"),
	"PL-OP-COS",
	INVENTORY_WRITE_DOWNS,
)

COST_OF_GOODS_SOLD = _rows(
	EXPENSE,
	(
		"cost of goods sold",
		"*cost of goods*",
		"*cost of sales*",
		"*harga pokok*",
		"*beban pokok*",
		"*purchase*",
		"*pembelian*",
	),
	"PL-OP-COS",
	RAW_MATERIALS,
)

SALES_REVENUE = _rows(
	INCOME,
	(
		"sales",
		"service",
		"*sales*",
		"*penjualan*",
		"*revenue*",
		"*pendapatan usaha*",
		"*retur*",
		"*return*",
		"*discount*",
		"*potongan*",
	),
	"PL-OP-REV",
)

# Project-based services (inspection, testing, certification, field services): the direct costs
# of a project are cost of sales, not general expenses
SERVICES_COST_OF_SALES = [
	*_rows(
		EXPENSE,
		("*penyusutan peralatan*", "*penyusutan alat*", "*depreciation*equipment*"),
		"PL-OP-COS",
		DEPRECIATION,
	),
	*_rows(
		EXPENSE,
		(
			"*teknisi*",
			"*technician*",
			"*direct labo*",
			"*tenaga kerja langsung*",
			"*upah proyek*",
			"*project wage*",
			"*field staff*",
		),
		"PL-OP-COS",
		EMPLOYEE_BENEFITS,
	),
	*_rows(
		EXPENSE,
		("*bahan habis pakai*", "*bahan proyek*", "*consumable*", "*material*"),
		"PL-OP-COS",
		RAW_MATERIALS,
	),
	*_rows(
		EXPENSE,
		(
			"*subkontra*",
			"*subcontract*",
			"*outsourc*",
			"*sewa alat*",
			"*sewa peralatan*",
			"*equipment rent*",
			"*equipment hire*",
			"*mobilisasi*",
			"*mobiliz*",
			"*mobilis*",
			"*perjalanan dinas proyek*",
			"*project travel*",
			"*biaya proyek*",
			"*project cost*",
			"*project expense*",
			"*cost of service*",
			"*cost of revenue*",
			"*beban pokok pendapatan*",
			"*beban pokok jasa*",
			"*beban langsung*",
			"*direct cost*",
			"*direct expense*",
		),
		"PL-OP-COS",
		OTHER,
	),
]

SERVICES_REVENUE = _rows(
	INCOME,
	("*pendapatan jasa*", "*service income*", "*pendapatan proyek*", "*project revenue*"),
	"PL-OP-REV",
)

MANUFACTURING_COST_OF_SALES = [
	*_rows(EXPENSE, ("*raw material*", "*bahan baku*", "*bahan penolong*"), "PL-OP-COS", RAW_MATERIALS),
	*_rows(
		EXPENSE,
		("*direct labo*", "*tenaga kerja langsung*", "*upah pabrik*", "*factory wage*"),
		"PL-OP-COS",
		EMPLOYEE_BENEFITS,
	),
	*_rows(
		EXPENSE,
		(
			"*depreciation*machine*",
			"*depreciation*factory*",
			"*factory*depreciation*",
			"*penyusutan mesin*",
			"*penyusutan pabrik*",
		),
		"PL-OP-COS",
		DEPRECIATION,
	),
	*_rows(
		EXPENSE,
		("*factory overhead*", "*overhead pabrik*", "*manufactur*", "*produksi*", "*production*"),
		"PL-OP-COS",
		OTHER,
	),
]

PROPERTY_SPECIFIC = [
	# Fair value changes of investment property are Investing; they move to Operating when the
	# company policy marks investing as a main business activity
	*_rows(
		INCOME,
		("*fair value*investment property*", "*nilai wajar*properti*"),
		"PL-INV-INC",
	),
	*_rows(
		EXPENSE,
		("*fair value*investment property*", "*nilai wajar*properti*"),
		"PL-INV-INC",
	),
	*_rows(
		EXPENSE,
		("*cost of property*", "*cost of land*", "*beban pokok penjualan properti*"),
		"PL-OP-COS",
		RAW_MATERIALS,
	),
	*_rows(
		EXPENSE,
		("*building management*", "*pengelolaan gedung*", "*service charge*"),
		"PL-OP-COS",
		OTHER,
	),
	*_rows(
		INCOME,
		(
			"*penjualan*properti*",
			"*penjualan unit*",
			"*sales of property*",
			"*sale of land*",
			"*rental*",
			"*sewa*",
			"*service charge*",
		),
		"PL-OP-REV",
	),
]

INVESTMENT_HOLDING_REVENUE = _rows(
	INCOME,
	("*management fee*", "*jasa manajemen*", "*fee income*"),
	"PL-OP-REV",
)


def _template(industry, specific, revenue, cost_of_sales) -> dict:
	return {
		"template_name": f"{industry} (Standard)",
		"industry": industry,
		"template_version": STANDARD_TEMPLATE_VERSION,
		"rows": [
			*specific,
			*FINAL_TAX,
			*INCOME_TAX,
			*FINANCING,
			*INVESTING_INCOME,
			*OTHER_OPERATING,
			*cost_of_sales,
			*SELLING,
			*GENERAL_AND_ADMINISTRATIVE,
			*MISCELLANEOUS,
			*revenue,
		],
	}


STANDARD_TEMPLATES = (
	_template(
		"Services",
		SERVICES_COST_OF_SALES,
		[*SERVICES_REVENUE, *SALES_REVENUE],
		[*VALUATION, *COST_OF_GOODS_SOLD],
	),
	_template("Trading", INVENTORY_WRITE_DOWN, SALES_REVENUE, [*VALUATION, *COST_OF_GOODS_SOLD]),
	_template(
		"Manufacturing",
		[*INVENTORY_WRITE_DOWN, *MANUFACTURING_COST_OF_SALES],
		SALES_REVENUE,
		[*VALUATION, *COST_OF_GOODS_SOLD],
	),
	_template("Property", PROPERTY_SPECIFIC, SALES_REVENUE, [*VALUATION, *COST_OF_GOODS_SOLD]),
	_template(
		"Investment Holding",
		(),
		[*INVESTMENT_HOLDING_REVENUE, *SALES_REVENUE],
		[*VALUATION, *COST_OF_GOODS_SOLD],
	),
)


def ensure_standard_mapping_templates():
	"""Insert standard templates that are missing; never overwrite a template the user changed."""
	for template in STANDARD_TEMPLATES:
		if frappe.db.exists("PSAK ID Mapping Template", template["template_name"]):
			continue
		frappe.get_doc({"doctype": "PSAK ID Mapping Template", **template}).insert(ignore_permissions=True)
