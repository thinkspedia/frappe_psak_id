from pathlib import Path

import frappe
from babel.messages.pofile import read_po

from frappe_psak_id.tests.utils import IntegrationTestCase

# English is the source language, so it has no PO file
SUPPORTED_LOCALES = ("id", "zh", "ja", "ar")


class TestTranslations(IntegrationTestCase):
	def setUp(self):
		self.locale_dir = Path(frappe.get_app_path("frappe_psak_id", "locale"))

	def test_pot_file_exists(self):
		self.assertTrue((self.locale_dir / "main.pot").is_file())

	def test_every_supported_locale_has_a_po_file(self):
		for locale in SUPPORTED_LOCALES:
			with self.subTest(locale=locale), open(self.locale_dir / f"{locale}.po", "rb") as f:
				self.assertEqual(str(read_po(f).locale), locale)

	def test_po_files_hold_every_pot_message(self):
		with open(self.locale_dir / "main.pot", "rb") as f:
			template = {message.id for message in read_po(f) if message.id}

		for locale in SUPPORTED_LOCALES:
			with self.subTest(locale=locale), open(self.locale_dir / f"{locale}.po", "rb") as f:
				catalog = {message.id for message in read_po(f) if message.id}
				self.assertLessEqual(template, catalog)
