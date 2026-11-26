"""Standard mapping templates, one per industry, installed with the app.

Each template is an ordered list of account name patterns (English names of ERPNext's standard
chart and common Indonesian names) and the PSAK 118 line they map to. The first matching row wins,
so specific patterns come first: final tax before income tax, lease interest before other
interest, project costs before general rent and travel, and the catch-all "other" rows last.

Version 1.1 also maps balance sheet accounts: name rows first, for what an account type cannot
tell (software is an intangible asset, employee advances are typed Payable, long-term loans are
not current), then rows on ERPNext's account type (Cash, Receivable, Fixed Asset, ...). Version
1.2 adds the cash flow lines: every balance sheet row but cash names the line its movements are
presented in, and income and expense rows below operating profit name the line their cash flows
belong to, so the movements of an account and of its counterpart land on the same activity.
Earlier versions stay as they are, since mappings record the template version they came from.
Accounts no row matches stay unmapped and show in the Mapping Control report; a template is a
starting point the accountant reviews, not a classification the app decides on its own.
"""

import frappe

from frappe_psak_id.psak_id.report_lines import ensure_standard_report_lines

STANDARD_TEMPLATE_VERSION = "1.2"
BALANCE_SHEET_TEMPLATE_VERSION = "1.1"
PROFIT_OR_LOSS_TEMPLATE_VERSION = "1.0"
_CASH_FLOW_FIELDS = ("cash_flow_line", "cash_flow_line_decrease")

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
	root_type,
	patterns,
	report_line,
	expense_nature=None,
	is_final_tax=0,
	match_on="Name",
	oci_line=None,
	cash_flow=None,
	added_in=PROFIT_OR_LOSS_TEMPLATE_VERSION,
) -> list[dict]:
	"""Template rows of the patterns. ``cash_flow`` is the cash flow line, or a pair of the lines of
	increases and decreases; ``added_in`` the first template version that has the rows."""
	cash_flow_line, cash_flow_line_decrease = cash_flow if isinstance(cash_flow, tuple) else (cash_flow, None)
	return [
		{
			"root_type": root_type,
			"match_on": match_on,
			"account_pattern": pattern,
			"report_line": report_line,
			"oci_line": oci_line,
			"expense_nature": expense_nature,
			"is_final_tax": is_final_tax,
			"cash_flow_line": cash_flow_line,
			"cash_flow_line_decrease": cash_flow_line_decrease,
			"added_in": added_in,
		}
		for pattern in patterns
	]


def _types(root_type, account_types, report_line, cash_flow=None) -> list[dict]:
	return _rows(root_type, account_types, report_line, match_on=ACCOUNT_TYPE, cash_flow=cash_flow)


# Cash flow lines of version 1.2 (PRD-002 Appendix C)
DEPRECIATION_ADD_BACK = "CF-OP-DEP"
RECEIVABLES, INVENTORIES = "CF-OP-WC-AR", "CF-OP-WC-INV"
OTHER_ASSETS, PAYABLES, OTHER_LIABILITIES = "CF-OP-WC-OA", "CF-OP-WC-AP", "CF-OP-WC-OL"
TAXES_PAID = "CF-OP-TAX"
EXCHANGE_DIFFERENCES = "CF-OP-FX"
PPE_PURCHASE, PPE_DISPOSAL = "CF-INV-PPE-BUY", "CF-INV-PPE-SELL"
INTANGIBLES = "CF-INV-INTANG"
INVESTMENTS = ("CF-INV-FIN-BUY", "CF-INV-FIN-SELL")
INTEREST_RECEIVED, DIVIDENDS_RECEIVED, OTHER_INVESTING = "CF-INV-INT", "CF-INV-DIV", "CF-INV-OTH"
BORROWINGS = ("CF-FIN-BORR-IN", "CF-FIN-BORR-OUT")
LEASE_PAYMENTS, INTEREST_PAID, DIVIDENDS_PAID = "CF-FIN-LEASE", "CF-FIN-INT", "CF-FIN-DIV"
SHARE_ISSUES, OTHER_FINANCING = "CF-FIN-EQ", "CF-FIN-OTH"
# Increases of an asset are debits: a credit to accumulated depreciation is the depreciation added
# back, a debit is the part of a disposal written off with the asset
PPE = (PPE_PURCHASE, PPE_DISPOSAL)
ACCUMULATED_DEPRECIATION = (PPE_DISPOSAL, DEPRECIATION_ADD_BACK)


# PPh final is not income tax (PSAK 212): it follows the income it is levied on (BR-21)
FINAL_TAX = [
	*_rows(
		EXPENSE,
		("*final*bunga*", "*bunga*final*", "*final*deposit*", "*final*interest*"),
		"PL-INV-INC",
		is_final_tax=1,
		cash_flow=INTEREST_RECEIVED,
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
		cash_flow=TAXES_PAID,
	),
]

FINANCING = [
	*_rows(
		EXPENSE,
		("*interest*lease*", "*lease*interest*", "*bunga*sewa*", "*bunga*liabilitas sewa*"),
		"PL-FIN-LEASE",
		cash_flow=INTEREST_PAID,
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
		# Interest added to the liability, presented with its movements
		cash_flow=OTHER_LIABILITIES,
	),
	*_rows(
		EXPENSE,
		("*interest expense*", "*beban bunga*", "*bunga pinjaman*", "*loan interest*", "*interest on loan*"),
		"PL-FIN-INT",
		cash_flow=INTEREST_PAID,
	),
	*_rows(EXPENSE, ("*loan*fee*", "*provisi pinjaman*"), "PL-FIN-OTH", cash_flow=OTHER_FINANCING),
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
		# Not cash: offsets the increase of the investment
		cash_flow=INVESTMENTS[0],
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
		),
		"PL-INV-INC",
		cash_flow=INTEREST_RECEIVED,
	),
	*_rows(INCOME, ("*dividend*", "*dividen*"), "PL-INV-INC", cash_flow=DIVIDENDS_RECEIVED),
	*_rows(INCOME, ("*gain*investment*", "*laba*investasi*"), "PL-INV-INC", cash_flow=INVESTMENTS[1]),
]

# Exchange differences on trade receivables and payables, disposals of operating assets and
# rounding are operating; review exchange differences on borrowings (Financing, BR-18). The gain
# or loss on a disposal is part of its proceeds, an investing cash flow.
OTHER_OPERATING = [
	*_rows(
		None, ("*exchange*", "*selisih kurs*", "*laba*kurs*", "*rugi*kurs*", "*forex*"), "PL-OP-OTH", OTHER
	),
	*_rows(
		None,
		("*disposal*", "*pelepasan aset*", "*penjualan aset*"),
		"PL-OP-OTH",
		OTHER,
		cash_flow=PPE_DISPOSAL,
	),
	*_rows(None, ("round off", "*pembulatan*", "write off"), "PL-OP-OTH", OTHER),
]

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
		cash_flow=OTHER_INVESTING,
	),
	*_rows(
		EXPENSE,
		("*fair value*investment property*", "*nilai wajar*properti*"),
		"PL-INV-INC",
		cash_flow=OTHER_INVESTING,
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
	# Additions are not cash (the lease liability is the counterpart, BR-35); depreciation is
	# credited to the asset or its accumulated depreciation
	*_rows(
		ASSET,
		("*right-of-use*", "*right of use*", "*hak guna*"),
		"FP-NCA-ROU",
		cash_flow=(PPE_PURCHASE, DEPRECIATION_ADD_BACK),
	),
	*_rows(ASSET, ("*goodwill*",), "FP-NCA-GW", cash_flow=OTHER_INVESTING),
	# ERPNext's standard chart types Software as a fixed asset; PSAK 219 makes it intangible
	*_rows(
		ASSET,
		("software", "*perangkat lunak*", "*intangible*", "*tak berwujud*", "*takberwujud*"),
		"FP-NCA-INTANG",
		cash_flow=(INTANGIBLES, DEPRECIATION_ADD_BACK),
	),
	*_rows(
		ASSET,
		("*accumulated amorti*", "*akumulasi amortisasi*"),
		"FP-NCA-INTANG",
		cash_flow=(INTANGIBLES, DEPRECIATION_ADD_BACK),
	),
	*_rows(
		ASSET, ("*investment property*", "*properti investasi*"), "FP-NCA-INVPROP", cash_flow=OTHER_INVESTING
	),
	*_rows(
		ASSET,
		(
			"*investment*associate*",
			"*investasi*asosiasi*",
			"*investment*joint venture*",
			"*investasi*ventura*",
		),
		"FP-NCA-ASSOC",
		cash_flow=INVESTMENTS,
	),
	*_rows(ASSET, ("*deferred tax*", "*pajak tangguhan*"), "FP-NCA-DTA", cash_flow=TAXES_PAID),
	*_rows(ASSET, ("*held for sale*", "*dimiliki untuk dijual*"), "FP-CA-HFS", cash_flow=OTHER_INVESTING),
	# Prepaid income tax is part of the income tax paid; VAT is a working capital item
	*_rows(
		ASSET,
		("*prepaid tax*", "*pajak dibayar dimuka*", "*uang muka pajak*"),
		"FP-CA-TAX",
		cash_flow=TAXES_PAID,
	),
	*_rows(ASSET, ("*input vat*", "*input tax*", "*ppn masukan*"), "FP-CA-TAX", cash_flow=OTHER_ASSETS),
	*_rows(
		ASSET,
		("*pph 22*", "*pph 23*", "*pph pasal 22*", "*pph pasal 23*"),
		"FP-CA-TAX",
		cash_flow=TAXES_PAID,
	),
	# Employee Advances of the standard chart is typed Payable; the name decides
	*_rows(
		ASSET,
		("*advance*", "*uang muka*", "*kasbon*", "*prepaid*", "*prepayment*", "*dibayar dimuka*"),
		"FP-CA-PREP",
		cash_flow=OTHER_ASSETS,
	),
	*_rows(
		ASSET,
		("*long-term investment*", "*investasi jangka panjang*"),
		"FP-NCA-FIN",
		cash_flow=INVESTMENTS,
	),
	*_rows(ASSET, ("earnest money",), "FP-CA-FIN", cash_flow=OTHER_ASSETS),
	*_rows(
		ASSET,
		("*deposit*", "*deposito*"),
		"FP-CA-FIN",
		cash_flow=INVESTMENTS,
	),
	*_rows(ASSET, ("*jaminan*",), "FP-CA-FIN", cash_flow=OTHER_ASSETS),
	*_rows(
		ASSET,
		("*short-term investment*", "*investasi jangka pendek*"),
		"FP-CA-FIN",
		cash_flow=INVESTMENTS,
	),
	*_types(ASSET, ("Cash", "Bank"), "FP-CA-CASH"),
	*_types(ASSET, ("Receivable",), "FP-CA-AR", cash_flow=RECEIVABLES),
	*_types(ASSET, ("Stock",), "FP-CA-INV", cash_flow=INVENTORIES),
	*_types(ASSET, ("Fixed Asset",), "FP-NCA-PPE", cash_flow=PPE),
	*_types(ASSET, ("Accumulated Depreciation",), "FP-NCA-PPE", cash_flow=ACCUMULATED_DEPRECIATION),
	*_types(ASSET, ("Capital Work in Progress",), "FP-NCA-PPE", cash_flow=PPE),
	*_types(ASSET, ("Tax",), "FP-CA-TAX", cash_flow=OTHER_ASSETS),
	*_types(ASSET, ("Temporary",), "FP-CA-OTH", cash_flow=OTHER_ASSETS),
	*_rows(ASSET, ("kas", "kas *", "*kas kecil*", "*petty cash*"), "FP-CA-CASH"),
	*_rows(ASSET, ("*piutang*", "*receivable*"), "FP-CA-AR", cash_flow=RECEIVABLES),
	*_rows(ASSET, ("*persediaan*", "*inventor*"), "FP-CA-INV", cash_flow=INVENTORIES),
	*_rows(ASSET, ("*aset tetap*", "*fixed asset*"), "FP-NCA-PPE", cash_flow=PPE),
	*_rows(
		ASSET,
		("*akumulasi penyusutan*", "*accumulated depreciation*"),
		"FP-NCA-PPE",
		cash_flow=ACCUMULATED_DEPRECIATION,
	),
]

# Long-term rows come before the general ones that would also match them
LIABILITIES = [
	*_rows(
		LIABILITY,
		("*long-term lease*", "*non-current lease*", "*liabilitas sewa jangka panjang*"),
		"FP-NCL-LEASE",
		cash_flow=LEASE_PAYMENTS,
	),
	*_rows(LIABILITY, ("*lease liabilit*", "*liabilitas sewa*"), "FP-CL-LEASE", cash_flow=LEASE_PAYMENTS),
	*_rows(LIABILITY, ("*deferred tax*", "*pajak tangguhan*"), "FP-NCL-DTL", cash_flow=TAXES_PAID),
	*_rows(LIABILITY, ("*held for sale*", "*dimiliki untuk dijual*"), "FP-CL-HFS", cash_flow=OTHER_INVESTING),
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
		cash_flow=OTHER_LIABILITIES,
	),
	*_rows(
		LIABILITY,
		("*long-term provision*", "*provisi jangka panjang*"),
		"FP-NCL-PROV",
		cash_flow=OTHER_LIABILITIES,
	),
	*_rows(LIABILITY, ("*provision*", "*provisi*"), "FP-CL-PROV", cash_flow=OTHER_LIABILITIES),
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
		cash_flow=BORROWINGS,
	),
	*_rows(
		LIABILITY,
		("*loan*", "*borrow*", "*pinjaman*", "*overdraft*", "*cerukan*", "*utang bank*"),
		"FP-CL-BORR",
		cash_flow=BORROWINGS,
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
		cash_flow=OTHER_LIABILITIES,
	),
	# Income tax payable belongs with the income tax paid, other taxes with working capital
	*_rows(
		LIABILITY,
		(
			"*income tax payable*",
			"*utang pph badan*",
			"*utang pph 29*",
			"*utang pph pasal 29*",
			"*utang pajak penghasilan badan*",
		),
		"FP-CL-TAX",
		cash_flow=TAXES_PAID,
		added_in="1.2",
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
		cash_flow=OTHER_LIABILITIES,
	),
	# Payables of investing and financing items, kept apart from trade payables (OQ-12): their
	# settlement is the cash flow of the item
	*_rows(
		LIABILITY,
		("*accrued interest*", "*bunga*masih harus dibayar*", "*utang bunga*"),
		"FP-CL-ACCR",
		cash_flow=INTEREST_PAID,
		added_in="1.2",
	),
	*_rows(
		LIABILITY,
		("*dividend*payable*", "*utang dividen*"),
		"FP-CL-AP",
		cash_flow=DIVIDENDS_PAID,
		added_in="1.2",
	),
	*_rows(
		LIABILITY,
		(
			"*fixed asset*payable*",
			"*asset purchase*payable*",
			"*utang pembelian aset*",
			"*utang aset tetap*",
		),
		"FP-CL-AP",
		cash_flow=PPE_PURCHASE,
		added_in="1.2",
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
		cash_flow=OTHER_LIABILITIES,
	),
	*_types(LIABILITY, ("Payable", "Stock Received But Not Billed"), "FP-CL-AP", cash_flow=PAYABLES),
	*_types(LIABILITY, ("Asset Received But Not Billed",), "FP-CL-AP", cash_flow=PPE_PURCHASE),
	*_types(LIABILITY, ("Tax",), "FP-CL-TAX", cash_flow=OTHER_LIABILITIES),
	*_rows(LIABILITY, ("*utang usaha*", "*utang lain*", "*payable*"), "FP-CL-AP", cash_flow=PAYABLES),
]

# Equity has no account types to go by. Reserves of other comprehensive income also name the line
# of the statement their movements are presented in (BR-38). Their movements are not cash: each
# takes the cash flow line of the account it is booked against (the revalued asset, the deferred
# tax, the employee benefit liability).
EQUITY_ROWS = [
	*_rows(
		EQUITY,
		("*revaluation*tax*", "*pajak*revaluasi*"),
		"FP-EQ-OCI",
		oci_line="OCI-NR-TAX",
		cash_flow=TAXES_PAID,
	),
	*_rows(
		EQUITY,
		("*revaluation*", "*revaluasi*"),
		"FP-EQ-OCI",
		oci_line="OCI-NR-REV",
		cash_flow=PPE_PURCHASE,
	),
	*_rows(
		EQUITY,
		("*remeasurement*", "*pengukuran kembali*"),
		"FP-EQ-OCI",
		oci_line="OCI-NR-EB",
		cash_flow=OTHER_LIABILITIES,
	),
	*_rows(
		EQUITY,
		("*translation*", "*penjabaran*"),
		"FP-EQ-OCI",
		oci_line="OCI-R-FX",
		cash_flow=EXCHANGE_DIFFERENCES,
	),
	*_rows(EQUITY, ("*treasury*", "*treasuri*"), "FP-EQ-TREAS", cash_flow=OTHER_FINANCING),
	*_rows(
		EQUITY,
		("*additional paid-in*", "*share premium*", "*agio*", "*tambahan modal disetor*"),
		"FP-EQ-APIC",
		cash_flow=SHARE_ISSUES,
	),
	*_rows(
		EQUITY,
		("*capital stock*", "*share capital*", "*modal saham*", "*modal disetor*"),
		"FP-EQ-CAP",
		cash_flow=SHARE_ISSUES,
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
		cash_flow=DIVIDENDS_PAID,
	),
	*_rows(
		EQUITY,
		("opening balance*", "*saldo awal*", "*other equity*", "*ekuitas lain*"),
		"FP-EQ-OTH",
		cash_flow=OTHER_FINANCING,
	),
]

BALANCE_SHEET = [*ASSETS, *LIABILITIES, *EQUITY_ROWS]


def _template(industry, specific, revenue, cost_of_sales, version=STANDARD_TEMPLATE_VERSION) -> dict:
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
	if version == PROFIT_OR_LOSS_TEMPLATE_VERSION:
		return {
			"template_name": f"{industry} (Standard)",
			"industry": industry,
			"template_version": version,
			"rows": _rows_of_version(profit_or_loss, version),
		}
	return {
		"template_name": f"{industry} (Standard {version})",
		"industry": industry,
		"template_version": version,
		"rows": _rows_of_version([*BALANCE_SHEET, *profit_or_loss], version),
	}


def _rows_of_version(rows: list[dict], version: str) -> list[dict]:
	"""The rows a template version has, without the cash flow lines before version 1.2."""
	with_cash_flow = _version_key(version) >= _version_key(STANDARD_TEMPLATE_VERSION)
	return [
		{
			key: value
			for key, value in row.items()
			if key != "added_in" and (with_cash_flow or key not in _CASH_FLOW_FIELDS)
		}
		for row in rows
		if _version_key(row["added_in"]) <= _version_key(version)
	]


def _version_key(version: str) -> tuple:
	return tuple(int(part) for part in version.split("."))


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

# The templates of earlier versions remain for the mappings made from them
STANDARD_TEMPLATES = tuple(
	_template(*industry, version=version)
	for version in (
		STANDARD_TEMPLATE_VERSION,
		BALANCE_SHEET_TEMPLATE_VERSION,
		PROFIT_OR_LOSS_TEMPLATE_VERSION,
	)
	for industry in INDUSTRIES
)


def ensure_standard_mapping_templates():
	"""Insert standard templates that are missing; never overwrite a template the user changed."""
	# An older patch may run this before the patch that adds the lines the templates map to
	ensure_standard_report_lines()
	for template in STANDARD_TEMPLATES:
		if frappe.db.exists("PSAK ID Mapping Template", template["template_name"]):
			continue
		frappe.get_doc({"doctype": "PSAK ID Mapping Template", **template}).insert(ignore_permissions=True)
