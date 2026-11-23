# Copyright (c) 2026, Thinkspedia and Contributors
# See license.txt

import frappe

from frappe_psak_id.tests.utils import IntegrationTestCase, make_company

# The tests create their own company. ERPNext's Company and Letter Head test records are skipped:
# they fail on a site where ERPNext's setup wizard never ran. Frappe v16 reads the first name,
# v15 the second.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Company", "Letter Head"]
test_ignore = IGNORE_TEST_RECORD_DEPENDENCIES

PSAK_ID_ROLES = (
	"PSAK ID - Accounting - Staff",
	"PSAK ID - Accounting - Head",
	"PSAK ID - CFO",
	"PSAK ID - Auditor",
)


class TestPSAKIDCompanyPolicy(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = make_company("_Test PSAK Policy Company", "_TPP")

	def setUp(self):
		frappe.db.delete("PSAK ID Company Policy", {"company": self.company})

	def _policy(self, **values):
		return frappe.get_doc({"doctype": "PSAK ID Company Policy", "company": self.company, **values})

	def test_roles_are_installed(self):
		for role in PSAK_ID_ROLES:
			self.assertTrue(frappe.db.exists("Role", role), role)

	def test_defaults(self):
		policy = self._policy().insert()
		self.assertEqual(policy.name, self.company)
		self.assertEqual(policy.reporting_framework, "SAK Indonesia")
		self.assertEqual(str(policy.adoption_date), "2027-01-01")
		self.assertEqual(policy.expense_presentation, "By Function")
		self.assertEqual(policy.default_unit, "Full")
		self.assertEqual(policy.currency, frappe.db.get_value("Company", self.company, "default_currency"))

	def test_one_policy_per_company(self):
		self._policy().insert()
		with self.assertRaises(frappe.DuplicateEntryError):
			self._policy().insert()

	def test_negative_threshold_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self._policy(other_items_threshold_amount=-1).insert()
		with self.assertRaises(frappe.ValidationError):
			self._policy(other_items_threshold_percent=-0.5).insert()

	def test_threshold_percent_above_100_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self._policy(other_items_threshold_percent=100.5).insert()

	def test_all_financing_in_operating_needs_customer_financing(self):
		with self.assertRaises(frappe.ValidationError):
			self._policy(financing_all_operating=1).insert()

		policy = self._policy(main_business_financing=1, financing_all_operating=1).insert()
		self.assertEqual(policy.financing_all_operating, 1)
