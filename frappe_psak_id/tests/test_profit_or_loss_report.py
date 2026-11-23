import datetime

import frappe

from frappe_psak_id.psak_id.report.psak_118_profit_or_loss.psak_118_profit_or_loss import (
	execute,
	get_periods,
)
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	erpnext_net_profit,
	get_account,
	make_company,
	make_fiscal_year,
	make_journal_entry,
)

COMPANY = "_Test PSAK Report Company"
OTHER_COMPANY = "_Test PSAK Report Other Company"
STAFF_USER = "psak-report-staff@example.com"


class TestPeriods(IntegrationTestCase):
	def test_periods_follow_calendar_months(self):
		d = datetime.date
		self.assertEqual(
			get_periods("2027-01-01", "2027-03-15", "Monthly"),
			[
				(d(2027, 1, 1), d(2027, 1, 31)),
				(d(2027, 2, 1), d(2027, 2, 28)),
				(d(2027, 3, 1), d(2027, 3, 15)),
			],
		)
		self.assertEqual(
			get_periods("2027-01-01", "2027-12-31", "Quarterly")[1], (d(2027, 4, 1), d(2027, 6, 30))
		)
		self.assertEqual(
			get_periods("2027-01-01", "2027-12-31", "Yearly"), [(d(2027, 1, 1), d(2027, 12, 31))]
		)


class TestProfitOrLossReport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COMPANY, "_TPR")
		make_company(OTHER_COMPANY, "_TPO")
		make_fiscal_year(2026)
		make_fiscal_year(2027)
		cls.cash = get_account(COMPANY, "Cash")
		cls.sales = get_account(COMPANY, "Sales")
		cls.salary = get_account(COMPANY, "Salary")
		cls.admin = get_account(COMPANY, "Administrative Expenses")

		for company in (COMPANY, OTHER_COMPANY):
			if not frappe.db.exists("PSAK ID Company Policy", company):
				frappe.get_doc({"doctype": "PSAK ID Company Policy", "company": company}).insert()

		frappe.db.delete("PSAK ID Account Mapping", {"company": COMPANY})
		for account, line, valid_from, extra in (
			(cls.sales, "PL-OP-REV", "2026-01-01", {}),
			(cls.salary, "PL-OP-GA", "2026-01-01", {"expense_nature": "Employee Benefits"}),
			# Mapped only from the first PSAK 118 year: the prior year is unmapped unless restated
			(cls.admin, "PL-OP-GA", "2027-01-01", {"expense_nature": "Other"}),
		):
			frappe.get_doc(
				{
					"doctype": "PSAK ID Account Mapping",
					"company": COMPANY,
					"account": account,
					"report_line": line,
					"valid_from": valid_from,
					"priority": 10,
					**extra,
				}
			).insert()

		cls.post("2026-01-15", cls.sales, -800_000)
		cls.post("2026-01-16", cls.admin, 100_000)
		cls.post("2027-01-15", cls.sales, -1_234_567)
		cls.post("2027-01-20", cls.salary, 234_000)
		cls.post("2027-02-15", cls.sales, -500_000)
		cls.post("2027-02-20", cls.admin, 50_000)

	@classmethod
	def post(cls, posting_date, account, amount):
		make_journal_entry(COMPANY, posting_date, account, amount, cls.cash)

	def run_report(self, **filters):
		columns, data, message, _chart, summary = execute(
			{"company": COMPANY, "from_date": "2027-01-01", "to_date": "2027-01-31", **filters}
		)
		return columns, {row.line_code: row for row in data if row.get("line_code")}, data, message, summary

	def test_statement_matches_erpnext_and_hides_lines_without_values(self):
		columns, rows, _data, message, summary = self.run_report()
		self.assertEqual([column["fieldname"] for column in columns], ["line", "p0"])
		self.assertEqual(rows["PL-OP-REV"].p0, 1_234_567)
		self.assertEqual(rows["PL-OP-GA"].p0, -234_000)
		self.assertEqual(rows["PL-SUB-OP"].p0, 1_000_567)
		self.assertEqual(rows["PL-SUB-PL"].p0, 1_000_567)
		self.assertTrue(rows["PL-SUB-PL"].is_profit_or_loss)
		self.assertEqual(rows["PL-OP-REV"].accounts["p0"], [self.sales])
		self.assertNotIn("PL-SUB-CONT", rows)
		self.assertNotIn("PL-DISC", rows)
		self.assertIsNone(message)

		profit, erpnext, difference = (item["value"] for item in summary)
		self.assertEqual(profit, 1_000_567)
		self.assertEqual(erpnext, erpnext_net_profit(COMPANY, "2027-01-01", "2027-01-31"))
		self.assertEqual(difference, 0)
		self.assertEqual(summary[2]["indicator"], "Green")

	def test_units_round_for_display_only(self):
		_columns, rows, _data, _message, summary = self.run_report(unit="Thousands")
		self.assertEqual(rows["PL-OP-REV"].p0, 1_235)
		self.assertEqual(rows["PL-OP-GA"].p0, -234)
		self.assertEqual(summary[0]["value"], 1_000_567)

	def test_empty_unit_takes_the_company_default(self):
		frappe.db.set_value("PSAK ID Company Policy", COMPANY, "default_unit", "Millions")
		self.addCleanup(frappe.db.set_value, "PSAK ID Company Policy", COMPANY, "default_unit", "Full")
		columns, rows, _data, _message, _summary = self.run_report(unit="")
		self.assertEqual(rows["PL-OP-REV"].p0, 1)
		self.assertEqual(columns[1]["unit"], "Millions")

	def test_monthly_columns_and_total(self):
		columns, rows, _data, _message, summary = self.run_report(to_date="2027-02-28", periodicity="Monthly")
		self.assertEqual([column["fieldname"] for column in columns], ["line", "p0", "p1", "total"])
		self.assertEqual(rows["PL-SUB-PL"].p1, 450_000)
		self.assertEqual(rows["PL-SUB-PL"].total, 1_450_567)
		self.assertEqual(sorted(rows["PL-OP-GA"].accounts["total"]), sorted([self.admin, self.salary]))
		self.assertEqual(summary[2]["value"], 0)

	def test_restated_comparative_uses_this_years_mappings(self):
		columns, rows, _data, message, _summary = self.run_report(comparative="Restated Prior Year")
		self.assertEqual([column["fieldname"] for column in columns], ["line", "p0", "c0"])
		self.assertEqual((columns[2]["from_date"], columns[2]["to_date"]), ("2026-01-01", "2026-01-31"))
		self.assertEqual(rows["PL-OP-GA"].c0, -100_000)
		self.assertEqual(rows["PL-SUB-PL"].c0, 700_000)
		self.assertIsNone(message)

	def test_same_period_last_year_uses_that_years_mappings(self):
		_columns, rows, _data, _message, _summary = self.run_report(comparative="Same Period Last Year")
		self.assertEqual(rows["PL-OP-GA"].c0, 0)
		self.assertEqual(rows["PL-SUB-PL"].c0, 800_000)

	def test_unmapped_accounts_are_explained(self):
		frappe.db.set_value(
			"PSAK ID Account Mapping",
			{"company": COMPANY, "account": self.salary},
			"valid_from",
			"2027-03-01",
		)
		self.addCleanup(
			frappe.db.set_value,
			"PSAK ID Account Mapping",
			{"company": COMPANY, "account": self.salary},
			"valid_from",
			"2026-01-01",
		)
		_columns, _rows, _data, message, summary = self.run_report()
		self.assertIn(self.salary, message)
		self.assertEqual(summary[2]["value"], 234_000)
		self.assertEqual(summary[2]["indicator"], "Red")

	def test_category_headings_and_language(self):
		frappe.db.set_value("PSAK ID Company Policy", COMPANY, "show_category_headings", 1)
		self.addCleanup(frappe.db.set_value, "PSAK ID Company Policy", COMPANY, "show_category_headings", 0)
		_columns, rows, data, _message, _summary = self.run_report(language="English")
		self.assertEqual((data[0].line, data[0].line_type), ("Operating", "Heading"))
		self.assertTrue(rows["PL-OP-REV"].indented)
		self.assertFalse(rows["PL-SUB-OP"].indented)
		self.assertNotIn("label_alt", rows["PL-OP-REV"])

		_columns, rows, _data, _message, _summary = self.run_report()
		self.assertTrue(rows["PL-OP-REV"].label_alt)

	def test_user_of_another_company_is_refused(self):
		if not frappe.db.exists("User", STAFF_USER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": STAFF_USER,
					"first_name": "PSAK Report Staff",
					"send_welcome_email": 0,
				}
			).insert()
			user.add_roles("PSAK ID - Accounting - Staff")
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": STAFF_USER,
					"allow": "Company",
					"for_value": OTHER_COMPANY,
				}
			).insert()
		frappe.set_user(STAFF_USER)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			self.run_report()
