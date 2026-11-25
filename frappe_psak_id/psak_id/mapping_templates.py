"""Standard mapping templates, one per industry, installed with the app.

Each template is an ordered list of account name patterns (English names of ERPNext's standard
chart and common Indonesian names) and the PSAK 118 line they map to. The first matching row wins,
so specific patterns come first: final tax before income tax, lease interest before other
interest, project costs before general rent and travel, and the catch-all "other" rows last.

Version 1.1 also maps balance sheet accounts: name rows first, for what an account type cannot
tell (software is an intangible asset, employee advances are typed Payable, long-term loans are
not current), then rows on ERPNext's account type (Cash, Receivable, Fixed Asset, ...). Version
1.0 templates stay as they are, since mappings record the template version they came from.
Accounts no row matches stay unmapped and show in the Mapping Control report; a template is a
starting point the accountant reviews, not a classification the app decides on its own.
"""

import frappe

STANDARD_TEMPLATE_VERSION = "1.1"
PROFIT_OR_LOSS_TEMPLATE_VERSION = "1.0"

INCOME, EXPENSE = "Income", "Expense"
ASSET, LIABILITY, EQUITY = "Asset", "Liability", "Equity"
ACCOUNT_TYPE = "Account Type"
RAW_MATERIALS = "Raw Materials and Goods"
EMPLOYEE_BENEFITS = "Employee Benefits"
DEPRECIATION = "Depreciation"
AMORTISATION = "Amortisation"
IMPAIRMENT = "Impairment Losses (Reversals)"
INVENTORY_WRITE_DOWNS = "Inventory Write-downs (Reversals)"
OTHER = "Other"


def _rows(
	root_type, patterns, report_line, expense_nature=None, is_final_tax=0, match_on="Name", oci_line=None
) -> list[dict]:
	return [
		{
			"root_type": root_type,
			"match_on": match_on,
			"account_pattern": pattern,
			"report_line": report_line,
			"oci_line": oci_line,
			"expense_nature": expense_nature,
			"is_final_tax": is_final_tax,
		}
		for pattern in patterns
	]


def _types(root_type, account_types, report_line) -> list[dict]:
	return _rows(root_type, account_types, report_line, match_on=ACCOUNT_TYPE)


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


ASSETS = [
	*_rows(ASSET, ("*right-of-use*", "*right of use*", "*hak guna*"), "FP-NCA-ROU"),
	*_rows(ASSET, ("*goodwill*",), "FP-NCA-GW"),
	# ERPNext's standard chart types Software as a fixed asset; PSAK 219 makes it intangible
	*_rows(
		ASSET,
		(
			"software",
			"*perangkat lunak*",
			"*intangible*",
			"*tak berwujud*",
			"*takberwujud*",
			"*accumulated amorti*",
			"*akumulasi amortisasi*",
		),
		"FP-NCA-INTANG",
	),
	*_rows(ASSET, ("*investment property*", "*properti investasi*"), "FP-NCA-INVPROP"),
	*_rows(
		ASSET,
		(
			"*investment*associate*",
			"*investasi*asosiasi*",
			"*investment*joint venture*",
			"*investasi*ventura*",
		),
		"FP-NCA-ASSOC",
	),
	*_rows(ASSET, ("*deferred tax*", "*pajak tangguhan*"), "FP-NCA-DTA"),
	*_rows(ASSET, ("*held for sale*", "*dimiliki untuk dijual*"), "FP-CA-HFS"),
	*_rows(
		ASSET,
		(
			"*prepaid tax*",
			"*pajak dibayar dimuka*",
			"*uang muka pajak*",
			"*input vat*",
			"*input tax*",
			"*ppn masukan*",
			"*pph 22*",
			"*pph 23*",
			"*pph pasal 22*",
			"*pph pasal 23*",
		),
		"FP-CA-TAX",
	),
	# Employee Advances of the standard chart is typed Payable; the name decides
	*_rows(
		ASSET,
		("*advance*", "*uang muka*", "*kasbon*", "*prepaid*", "*prepayment*", "*dibayar dimuka*"),
		"FP-CA-PREP",
	),
	*_rows(ASSET, ("*long-term investment*", "*investasi jangka panjang*"), "FP-NCA-FIN"),
	*_rows(
		ASSET,
		(
			"earnest money",
			"*deposit*",
			"*deposito*",
			"*jaminan*",
			"*short-term investment*",
			"*investasi jangka pendek*",
		),
		"FP-CA-FIN",
	),
	*_types(ASSET, ("Cash", "Bank"), "FP-CA-CASH"),
	*_types(ASSET, ("Receivable",), "FP-CA-AR"),
	*_types(ASSET, ("Stock",), "FP-CA-INV"),
	*_types(ASSET, ("Fixed Asset", "Accumulated Depreciation", "Capital Work in Progress"), "FP-NCA-PPE"),
	*_types(ASSET, ("Tax",), "FP-CA-TAX"),
	*_types(ASSET, ("Temporary",), "FP-CA-OTH"),
	*_rows(ASSET, ("kas", "kas *", "*kas kecil*", "*petty cash*"), "FP-CA-CASH"),
	*_rows(ASSET, ("*piutang*", "*receivable*"), "FP-CA-AR"),
	*_rows(ASSET, ("*persediaan*", "*inventor*"), "FP-CA-INV"),
	*_rows(
		ASSET,
		("*aset tetap*", "*fixed asset*", "*akumulasi penyusutan*", "*accumulated depreciation*"),
		"FP-NCA-PPE",
	),
]

# Long-term rows come before the general ones that would also match them
LIABILITIES = [
	*_rows(
		LIABILITY,
		("*long-term lease*", "*non-current lease*", "*liabilitas sewa jangka panjang*"),
		"FP-NCL-LEASE",
	),
	*_rows(LIABILITY, ("*lease liabilit*", "*liabilitas sewa*"), "FP-CL-LEASE"),
	*_rows(LIABILITY, ("*deferred tax*", "*pajak tangguhan*"), "FP-NCL-DTL"),
	*_rows(LIABILITY, ("*held for sale*", "*dimiliki untuk dijual*"), "FP-CL-HFS"),
	*_rows(
		LIABILITY,
		(
			"*employee benefit*",
			"*imbalan kerja*",
			"*imbalan pascakerja*",
			"*pension*",
			"*pensiun*",
			"*pesangon*",
		),
		"FP-NCL-EB",
	),
	*_rows(LIABILITY, ("*long-term provision*", "*provisi jangka panjang*"), "FP-NCL-PROV"),
	*_rows(LIABILITY, ("*provision*", "*provisi*"), "FP-CL-PROV"),
	*_rows(
		LIABILITY,
		(
			"*long-term loan*",
			"*long-term borrow*",
			"*pinjaman jangka panjang*",
			"*utang bank jangka panjang*",
			"*bonds payable*",
			"*utang obligasi*",
		),
		"FP-NCL-BORR",
	),
	*_rows(
		LIABILITY,
		("*loan*", "*borrow*", "*pinjaman*", "*overdraft*", "*cerukan*", "*utang bank*"),
		"FP-CL-BORR",
	),
	*_rows(
		LIABILITY,
		(
			"*advance*",
			"*uang muka*",
			"*unearned*",
			"*deferred revenue*",
			"*diterima dimuka*",
			"*contract liabilit*",
			"*liabilitas kontrak*",
		),
		"FP-CL-CONTRACT",
	),
	*_rows(
		LIABILITY,
		(
			"*tax*payable*",
			"*utang pajak*",
			"*utang pph*",
			"*output vat*",
			"*output tax*",
			"*ppn keluaran*",
		),
		"FP-CL-TAX",
	),
	*_rows(
		LIABILITY,
		(
			"*accrued*",
			"*accrual*",
			"*akrual*",
			"*masih harus dibayar*",
			"*payroll payable*",
			"*salar*payable*",
			"*utang gaji*",
		),
		"FP-CL-ACCR",
	),
	*_types(
		LIABILITY,
		("Payable", "Stock Received But Not Billed", "Asset Received But Not Billed"),
		"FP-CL-AP",
	),
	*_types(LIABILITY, ("Tax",), "FP-CL-TAX"),
	*_rows(LIABILITY, ("*utang usaha*", "*utang lain*", "*payable*"), "FP-CL-AP"),
]

# Equity has no account types to go by. Reserves of other comprehensive income also name the line
# of the statement their movements are presented in (BR-38).
EQUITY_ROWS = [
	*_rows(
		EQUITY,
		("*revaluation*tax*", "*pajak*revaluasi*"),
		"FP-EQ-OCI",
		oci_line="OCI-NR-TAX",
	),
	*_rows(EQUITY, ("*revaluation*", "*revaluasi*"), "FP-EQ-OCI", oci_line="OCI-NR-REV"),
	*_rows(EQUITY, ("*remeasurement*", "*pengukuran kembali*"), "FP-EQ-OCI", oci_line="OCI-NR-EB"),
	*_rows(EQUITY, ("*translation*", "*penjabaran*"), "FP-EQ-OCI", oci_line="OCI-R-FX"),
	*_rows(EQUITY, ("*treasury*", "*treasuri*"), "FP-EQ-TREAS"),
	*_rows(
		EQUITY,
		("*additional paid-in*", "*share premium*", "*agio*", "*tambahan modal disetor*"),
		"FP-EQ-APIC",
	),
	*_rows(
		EQUITY,
		("*capital stock*", "*share capital*", "*modal saham*", "*modal disetor*"),
		"FP-EQ-CAP",
	),
	*_rows(
		EQUITY,
		(
			"*retained earning*",
			"*saldo laba*",
			"*laba ditahan*",
			"*dividend*",
			"*dividen*",
			"*laba tahun berjalan*",
		),
		"FP-EQ-RE",
	),
	*_rows(
		EQUITY,
		("opening balance*", "*saldo awal*", "*other equity*", "*ekuitas lain*"),
		"FP-EQ-OTH",
	),
]

BALANCE_SHEET = [*ASSETS, *LIABILITIES, *EQUITY_ROWS]


def _template(industry, specific, revenue, cost_of_sales, balance_sheet=True) -> dict:
	profit_or_loss = [
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
	]
	if not balance_sheet:
		return {
			"template_name": f"{industry} (Standard)",
			"industry": industry,
			"template_version": PROFIT_OR_LOSS_TEMPLATE_VERSION,
			"rows": profit_or_loss,
		}
	return {
		"template_name": f"{industry} (Standard {STANDARD_TEMPLATE_VERSION})",
		"industry": industry,
		"template_version": STANDARD_TEMPLATE_VERSION,
		"rows": [*BALANCE_SHEET, *profit_or_loss],
	}


INDUSTRIES = (
	(
		"Services",
		SERVICES_COST_OF_SALES,
		[*SERVICES_REVENUE, *SALES_REVENUE],
		[*VALUATION, *COST_OF_GOODS_SOLD],
	),
	("Trading", INVENTORY_WRITE_DOWN, SALES_REVENUE, [*VALUATION, *COST_OF_GOODS_SOLD]),
	(
		"Manufacturing",
		[*INVENTORY_WRITE_DOWN, *MANUFACTURING_COST_OF_SALES],
		SALES_REVENUE,
		[*VALUATION, *COST_OF_GOODS_SOLD],
	),
	("Property", PROPERTY_SPECIFIC, SALES_REVENUE, [*VALUATION, *COST_OF_GOODS_SOLD]),
	(
		"Investment Holding",
		(),
		[*INVESTMENT_HOLDING_REVENUE, *SALES_REVENUE],
		[*VALUATION, *COST_OF_GOODS_SOLD],
	),
)

# The profit or loss only templates of 1.0 remain for the mappings made from them
STANDARD_TEMPLATES = (
	*(_template(*industry) for industry in INDUSTRIES),
	*(_template(*industry, balance_sheet=False) for industry in INDUSTRIES),
)


def ensure_standard_mapping_templates():
	"""Insert standard templates that are missing; never overwrite a template the user changed."""
	for template in STANDARD_TEMPLATES:
		if frappe.db.exists("PSAK ID Mapping Template", template["template_name"]):
			continue
		frappe.get_doc({"doctype": "PSAK ID Mapping Template", **template}).insert(ignore_permissions=True)
