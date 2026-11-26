import json

import frappe

from frappe_psak_id.permissions import has_app_permission
from frappe_psak_id.psak_id.number_cards import unmapped_accounts
from frappe_psak_id.tests.test_financial_statement import make_mapping, make_policy
from frappe_psak_id.tests.utils import IntegrationTestCase, get_account, make_company

COMPANY = "_Test PSAK Workspace Company"
WORKSPACE = "PSAK 118"


class TestWorkspace(IntegrationTestCase):
	def test_workspace_shows_every_number_card(self):
		workspace = frappe.get_doc("Workspace", WORKSPACE)
		self.assertEqual(workspace.module, "PSAK ID")
		labels = {row.label for row in workspace.number_cards}
		self.assertEqual(len(labels), 4)
		for row in workspace.number_cards:
			self.assertTrue(frappe.db.exists("Number Card", row.number_card_name))
		# The page finds a block's widget by its label, not by the card's name
		blocks = json.loads(workspace.content)
		self.assertEqual(
			{b["data"]["number_card_name"] for b in blocks if b["type"] == "number_card"}, labels
		)
		self.assertEqual(
			{b["data"]["shortcut_name"] for b in blocks if b["type"] == "shortcut"},
			{row.label for row in workspace.shortcuts},
		)
		reports = set()
		for row in workspace.links:
			if row.type == "Link":
				self.assertTrue(frappe.db.exists(row.link_type, row.link_to), row.link_to)
				if row.link_type == "Report":
					reports.add(row.link_to)
		self.assertLessEqual({"PSAK 118 Profit or Loss", "PSAK 118 Financial Position"}, reports)

	def test_sidebar_links_exist(self):
		if not frappe.db.exists("DocType", "Sidebar"):
			self.skipTest("Frappe version without module sidebars")
		sidebar = frappe.get_doc("Sidebar", {"module": "PSAK ID"})
		links = [item for item in sidebar.items if item.type == "Link"]
		self.assertEqual(len(links), 10)
		self.assertIn("PSAK 118 Financial Position", [item.link_to for item in links])
		for item in links:
			self.assertTrue(frappe.db.exists(item.link_type, item.link_to), item.link_to)

	def test_unmapped_accounts_counts_accounts_without_a_mapping_in_force(self):
		make_company(COMPANY, "_TPW")
		make_policy(COMPANY, "2026-01-01")
		frappe.db.delete("PSAK ID Account Mapping", {"company": COMPANY})
		before = unmapped_accounts()
		self.assertGreater(before, 0)

		make_mapping(COMPANY, get_account(COMPANY, "Sales"), "PL-OP-REV")
		self.assertEqual(unmapped_accounts(), before - 1)
		# A mapping that starts later does not map the account today
		make_mapping(COMPANY, get_account(COMPANY, "Service"), "PL-OP-REV", valid_from="2099-01-01")
		self.assertEqual(unmapped_accounts(), before - 1)

	def test_apps_screen_only_for_psak_users(self):
		self.assertTrue(has_app_permission())
		frappe.set_user("Guest")
		try:
			self.assertFalse(has_app_permission())
		finally:
			frappe.set_user("Administrator")
