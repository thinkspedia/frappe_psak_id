import frappe

from frappe_psak_id.permissions import AUDITOR
from frappe_psak_id.tests.utils import IntegrationTestCase, make_company

AUDITOR_USER = "psak-auditor@example.com"
OWN_COMPANY = "_Test PSAK Audited Company"
OTHER_COMPANY = "_Test PSAK Other Audited Company"


def make_version(ref_doctype, docname):
	return frappe.get_doc(
		{"doctype": "Version", "ref_doctype": ref_doctype, "docname": docname, "data": "{}"}
	).insert(ignore_permissions=True)


class TestAuditorVersionAccess(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for company, abbr in ((OWN_COMPANY, "_TAC"), (OTHER_COMPANY, "_TOC")):
			make_company(company, abbr)
			if not frappe.db.exists("PSAK ID Company Policy", company):
				frappe.get_doc({"doctype": "PSAK ID Company Policy", "company": company}).insert()
		if not frappe.db.exists("User", AUDITOR_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": AUDITOR_USER,
					"first_name": "PSAK Auditor",
					"send_welcome_email": 0,
				}
			).insert().add_roles(AUDITOR)
		if not frappe.db.exists("User Permission", {"user": AUDITOR_USER, "allow": "Company"}):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": AUDITOR_USER,
					"allow": "Company",
					"for_value": OWN_COMPANY,
				}
			).insert()
		cls.own = make_version("PSAK ID Company Policy", OWN_COMPANY)
		cls.other = make_version("PSAK ID Company Policy", OTHER_COMPANY)
		cls.outside = make_version("User", "Administrator")

	def test_auditor_reads_the_versions_of_psak_documents_they_can_read(self):
		self.assertTrue(
			frappe.db.exists("Custom DocPerm", {"parent": "Version", "role": AUDITOR, "read": 1, "report": 1})
		)
		frappe.set_user(AUDITOR_USER)
		self.addCleanup(frappe.set_user, "Administrator")

		self.assertTrue(frappe.has_permission("Version", "read", self.own.name))
		self.assertFalse(frappe.has_permission("Version", "read", self.other.name))
		self.assertFalse(frappe.has_permission("Version", "read", self.outside.name))
		listed = frappe.get_list("Version", pluck="name")
		self.assertIn(self.own.name, listed)
		self.assertNotIn(self.other.name, listed)
		self.assertNotIn(self.outside.name, listed)

	def test_system_manager_still_reads_every_version(self):
		listed = frappe.get_list("Version", filters={"name": ("in", [self.other.name, self.outside.name])})
		self.assertEqual(len(listed), 2)
