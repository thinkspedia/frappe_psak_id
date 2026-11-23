import frappe

try:
	from frappe.tests import IntegrationTestCase
except ImportError:  # Frappe v15
	from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

__all__ = ["IntegrationTestCase", "make_company"]


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
