import frappe

try:
	from frappe.tests import IntegrationTestCase
except ImportError:  # Frappe v15
	from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

__all__ = ["IntegrationTestCase", "get_account", "make_account", "make_company"]


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
