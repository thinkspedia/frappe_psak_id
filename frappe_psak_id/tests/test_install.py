import frappe

from frappe_psak_id.compat import is_supported
from frappe_psak_id.tests.utils import IntegrationTestCase


class TestInstall(IntegrationTestCase):
	def test_app_is_installed(self):
		self.assertIn("frappe_psak_id", frappe.get_installed_apps())

	def test_erpnext_is_installed(self):
		# The statements read ERPNext's ledger, so the app is useless without it
		self.assertIn("erpnext", frappe.get_installed_apps())

	def test_frappe_version_is_supported(self):
		self.assertTrue(is_supported(), frappe.__version__)

	def test_module_is_registered(self):
		self.assertEqual(frappe.db.get_value("Module Def", "PSAK ID", "app_name"), "frappe_psak_id")
