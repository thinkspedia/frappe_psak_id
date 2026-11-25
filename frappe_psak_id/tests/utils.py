import frappe

try:
	from frappe.tests import IntegrationTestCase
except ImportError:  # Frappe v15
	from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

__all__ = [
	"IntegrationTestCase",
	"erpnext_net_profit",
	"erpnext_total_assets",
	"get_account",
	"make_account",
	"make_company",
	"make_cost_center",
	"make_fiscal_year",
	"make_journal_entry",
]


def make_company(company_name: str, abbr: str) -> str:
	"""Return a test company with ERPNext's standard chart, creating it on first use.

	Tests build their own company so they never depend on data that happens to exist on a site.
	"""
	# ERPNext's setup wizard normally creates this master; CI and fresh Dev sites skip the wizard,
	# and Company.on_update needs it for the default transit warehouse
	if not frappe.db.exists("Warehouse Type", "Transit"):
		frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert()
	if not frappe.db.exists("Company", company_name):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": company_name,
				"abbr": abbr,
				"country": "Indonesia",
				"default_currency": "IDR",
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": "Standard",
			}
		).insert()
	return company_name


def get_account(company: str, account_name: str) -> str:
	"""Return the name of an account of ERPNext's standard chart, e.g. ``get_account(c, "Sales")``."""
	abbr = frappe.get_cached_value("Company", company, "abbr")
	return f"{account_name} - {abbr}"


def make_account(company: str, account_name: str, parent_account_name: str) -> str:
	"""Return a leaf account under a group of the standard chart, creating it on first use.

	ERPNext's standard chart differs between versions (v15 has no interest or tax expense
	accounts), so tests create the accounts they need beyond the common ones.
	"""
	name = get_account(company, account_name)
	if not frappe.db.exists("Account", name):
		frappe.get_doc(
			{
				"doctype": "Account",
				"company": company,
				"account_name": account_name,
				"parent_account": get_account(company, parent_account_name),
			}
		).insert()
	return name


def make_fiscal_year(year: int) -> str:
	"""Return a calendar fiscal year, creating it on first use (ERPNext needs one for postings)."""
	start = f"{year}-01-01"
	existing = frappe.db.get_value(
		"Fiscal Year", {"year_start_date": ("<=", start), "year_end_date": (">=", start)}
	)
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": str(year),
				"year_start_date": start,
				"year_end_date": f"{year}-12-31",
			}
		)
		.insert()
		.name
	)


def make_cost_center(company: str, cost_center_name: str) -> str:
	"""Return a leaf cost center under the company's root, creating it on first use."""
	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = f"{cost_center_name} - {abbr}"
	if not frappe.db.exists("Cost Center", name):
		frappe.get_doc(
			{
				"doctype": "Cost Center",
				"company": company,
				"cost_center_name": cost_center_name,
				"parent_cost_center": f"{company} - {abbr}",
			}
		).insert()
	return name


def make_journal_entry(
	company: str,
	posting_date: str,
	account: str,
	amount: float,
	against: str,
	cost_center: str | None = None,
	finance_book: str | None = None,
):
	"""Post ``amount`` to ``account`` (positive = debit, negative = credit) against ``against``."""
	cost_center = cost_center or frappe.get_cached_value("Company", company, "cost_center")
	debit, credit = (amount, 0) if amount > 0 else (0, -amount)
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"company": company,
			"posting_date": posting_date,
			"finance_book": finance_book,
			"accounts": [
				{
					"account": account,
					"debit_in_account_currency": debit,
					"credit_in_account_currency": credit,
					"cost_center": cost_center,
				},
				{
					"account": against,
					"debit_in_account_currency": credit,
					"credit_in_account_currency": debit,
					"cost_center": cost_center,
				},
			],
		}
	)
	je.insert()
	je.submit()
	return je


def erpnext_net_profit(
	company: str, from_date, to_date, cost_center: str | None = None, finance_book: str | None = None
) -> float:
	"""Net profit or loss of ERPNext's own Profit and Loss Statement, with its default of including
	the company's default finance book unless another book is asked for."""
	from erpnext.accounts.report.profit_and_loss_statement.profit_and_loss_statement import execute
	from frappe import _
	from frappe.utils import flt

	default_book = frappe.get_cached_value("Company", company, "default_finance_book")
	filters = frappe._dict(
		company=company,
		filter_based_on="Date Range",
		period_start_date=from_date,
		period_end_date=to_date,
		periodicity="Yearly",
		accumulated_values=0,
		presentation_currency=frappe.get_cached_value("Company", company, "default_currency"),
		cost_center=[cost_center] if cost_center else [],
		finance_book=finance_book,
		include_default_book_entries=int(
			not (finance_book and default_book and finance_book != default_book)
		),
	)
	# ERPNext's own label, translated by ERPNext; kept out of a literal _() so it is not extracted
	# into this app's translation files
	label = "Profit for the year"
	profit_row = "'" + _(label) + "'"
	for row in reversed(execute(filters)[1] or []):
		if row.get("account") == profit_row:
			return flt(row.get("total"), 2)
	return 0.0


def erpnext_total_assets(company: str, from_date, to_date, finance_book: str | None = None) -> float:
	"""Total Asset of ERPNext's own Balance Sheet on ``to_date``; ``from_date`` is the start of the
	fiscal year, which ERPNext needs to build its period. Liabilities, equity and the provisional
	profit or loss of that report always add up to the same amount."""
	from erpnext.accounts.report.balance_sheet.balance_sheet import execute
	from frappe.utils import flt

	default_book = frappe.get_cached_value("Company", company, "default_finance_book")
	filters = frappe._dict(
		company=company,
		filter_based_on="Date Range",
		period_start_date=from_date,
		period_end_date=to_date,
		periodicity="Yearly",
		accumulated_values=1,
		presentation_currency=frappe.get_cached_value("Company", company, "default_currency"),
		finance_book=finance_book,
		include_default_book_entries=int(
			not (finance_book and default_book and finance_book != default_book)
		),
	)
	# The report summary starts with Total Asset on v15 and v16
	return flt(execute(filters)[4][0]["value"], 2)
