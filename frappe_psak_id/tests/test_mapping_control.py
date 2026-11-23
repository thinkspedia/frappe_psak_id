import frappe

from frappe_psak_id.psak_id.checks import (
	BLOCKING,
	CONFLICTING_MAPPINGS,
	CURRENT,
	ERPNEXT_DIFFERENCE,
	OTHER_ITEMS,
	RESTATED,
	RESTATEMENT_DIFFERENCE,
	WARNING,
	is_transition_period,
	other_items_threshold,
	run_checks,
)
from frappe_psak_id.psak_id.report.psak_id_mapping_control.psak_id_mapping_control import execute
from frappe_psak_id.psak_id.statement import DISABLED_LINE, NO_MATCHING_CONDITION, NOT_MAPPED
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	get_account,
	make_account,
	make_company,
	make_fiscal_year,
	make_journal_entry,
)

COMPANY = "_Test PSAK Control Company"


class TestMappingControl(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COMPANY, "_TPC")
		make_fiscal_year(2026)
		make_fiscal_year(2027)
		cls.cash = get_account(COMPANY, "Cash")
		cls.sales = get_account(COMPANY, "Sales")
		cls.cogs = get_account(COMPANY, "Cost of Goods Sold")
		cls.salary = get_account(COMPANY, "Salary")
		cls.admin = get_account(COMPANY, "Administrative Expenses")
		cls.interest_income = make_account(COMPANY, "Interest Income", "Indirect Income")
		cls.sundry = make_account(COMPANY, "Sundry Expenses", "Indirect Expenses")
		cls.legacy = make_account(COMPANY, "Legacy Expenses", "Indirect Expenses")
		cls.main = frappe.get_cached_value("Company", COMPANY, "cost_center")
		cls.root = frappe.db.get_value(
			"Cost Center", {"company": COMPANY, "is_group": 1}, "name", order_by="lft asc"
		)

		if not frappe.db.exists("PSAK ID Company Policy", COMPANY):
			frappe.get_doc({"doctype": "PSAK ID Company Policy", "company": COMPANY}).insert()
		frappe.db.set_value(
			"PSAK ID Company Policy",
			COMPANY,
			{
				"adoption_date": "2027-01-01",
				"other_items_threshold_percent": 1,
				"other_items_threshold_amount": 50_000,
			},
		)

		def cost_center_condition(cost_center):
			return {
				"condition_type": "Cost Center",
				"condition_doctype": "Cost Center",
				"condition_value": cost_center,
				"priority": 5,
			}

		frappe.db.delete("PSAK ID Account Mapping", {"company": COMPANY})
		cls.mappings = {}
		for key, account, line, extra in (
			("sales", cls.sales, "PL-OP-REV", {}),
			("admin", cls.admin, "PL-OP-SELL", {"expense_nature": "Other"}),
			("sundry", cls.sundry, "PL-OP-OTH", {"expense_nature": "Other"}),
			# Only a conditional mapping: entries of other cost centers have no line
			("interest", cls.interest_income, "PL-INV-INC", cost_center_condition(cls.ops_center())),
			# Two conditions that both cover the main cost center, at one priority, two lines
			(
				"cogs_main",
				cls.cogs,
				"PL-OP-COS",
				{"expense_nature": "Raw Materials and Goods", **cost_center_condition(cls.main)},
			),
			(
				"cogs_all",
				cls.cogs,
				"PL-OP-GA",
				{"expense_nature": "Other", **cost_center_condition(cls.root)},
			),
		):
			cls.mappings[key] = (
				frappe.get_doc(
					{
						"doctype": "PSAK ID Account Mapping",
						"company": COMPANY,
						"account": account,
						"report_line": line,
						"valid_from": "2026-01-01",
						"priority": 10,
						**extra,
					}
				)
				.insert()
				.name
			)

		for posting_date, account, amount in (
			("2026-01-15", cls.sales, -900_000),
			("2026-01-16", cls.legacy, 7_000),
			("2027-01-10", cls.sales, -1_000_000),
			("2027-01-11", cls.salary, 100_000),
			("2027-01-12", cls.interest_income, -5_000),
			("2027-01-13", cls.cogs, 200_000),
			("2027-01-14", cls.sundry, 20_000),
			("2027-02-10", cls.sales, -500_000),
			("2027-03-10", cls.admin, 30_000),
		):
			make_journal_entry(COMPANY, posting_date, account, amount, cls.cash)

	@classmethod
	def ops_center(cls):
		name = f"Control Ops - {frappe.get_cached_value('Company', COMPANY, 'abbr')}"
		if not frappe.db.exists("Cost Center", name):
			frappe.get_doc(
				{
					"doctype": "Cost Center",
					"cost_center_name": "Control Ops",
					"company": COMPANY,
					"parent_cost_center": cls.root,
				}
			).insert()
		return name

	@staticmethod
	def issues(result, check, period=CURRENT):
		return [issue for issue in result.issues if issue.check == check and issue.period == period]

	def test_unmapped_accounts_conflicts_and_differences_of_the_period(self):
		result = run_checks(COMPANY, "2027-01-01", "2027-01-31")

		(unmapped,) = self.issues(result, NOT_MAPPED)
		self.assertEqual(
			(unmapped.account, unmapped.amount, unmapped.severity), (self.salary, -100_000, BLOCKING)
		)

		(no_condition,) = self.issues(result, NO_MATCHING_CONDITION)
		self.assertEqual((no_condition.account, no_condition.amount), (self.interest_income, 5_000))

		(conflict,) = self.issues(result, CONFLICTING_MAPPINGS)
		self.assertEqual(conflict.severity, WARNING)
		self.assertEqual(conflict.priority, 5)
		self.assertEqual(conflict.mappings, sorted([self.mappings["cogs_main"], self.mappings["cogs_all"]]))

		(difference,) = self.issues(result, ERPNEXT_DIFFERENCE)
		self.assertEqual(difference.amount, 95_000)
		self.assertEqual(result.current.ledger_difference, 95_000)

	def test_transition_year_checks_the_restated_prior_year(self):
		result = run_checks(COMPANY, "2027-01-01", "2027-01-31")
		restated = [issue for issue in result.issues if issue.period == RESTATED]
		self.assertEqual(
			[(issue.check, issue.account, issue.amount) for issue in restated],
			[(NOT_MAPPED, self.legacy, -7_000), (RESTATEMENT_DIFFERENCE, None, 7_000)],
		)
		self.assertEqual(str(result.restated.from_date), "2026-01-01")

		frappe.db.set_value("PSAK ID Company Policy", COMPANY, "adoption_date", "2026-01-01")
		self.addCleanup(frappe.db.set_value, "PSAK ID Company Policy", COMPANY, "adoption_date", "2027-01-01")
		self.assertFalse(is_transition_period(COMPANY, "2027-01-01", "2027-01-31"))
		self.assertIsNone(run_checks(COMPANY, "2027-01-01", "2027-01-31").restated)

	def test_other_items_above_the_smaller_threshold(self):
		self.assertEqual(other_items_threshold(COMPANY, 1_000_000), 10_000)
		(other,) = self.issues(run_checks(COMPANY, "2027-01-01", "2027-01-31"), OTHER_ITEMS)
		self.assertEqual((other.report_line, other.amount, other.threshold), ("PL-OP-OTH", -20_000, 10_000))

		frappe.db.set_value("PSAK ID Company Policy", COMPANY, "other_items_threshold_percent", 0)
		self.addCleanup(
			frappe.db.set_value, "PSAK ID Company Policy", COMPANY, "other_items_threshold_percent", 1
		)
		self.assertEqual(self.issues(run_checks(COMPANY, "2027-01-01", "2027-01-31"), OTHER_ITEMS), [])

	def test_account_mapped_to_a_disabled_line(self):
		frappe.db.set_value("PSAK ID Report Line", "PL-OP-SELL", "disabled", 1)
		self.addCleanup(frappe.db.set_value, "PSAK ID Report Line", "PL-OP-SELL", "disabled", 0)
		(disabled,) = self.issues(run_checks(COMPANY, "2027-03-01", "2027-03-31"), DISABLED_LINE)
		self.assertEqual((disabled.account, disabled.report_line), (self.admin, "PL-OP-SELL"))

	def test_report_rows_and_summary(self):
		columns, data, message, _chart, summary = execute(
			{"company": COMPANY, "from_date": "2027-01-01", "to_date": "2027-01-31"}
		)
		self.assertEqual(columns[-1]["fieldname"], "fix")
		self.assertEqual([row.row_index for row in data], list(range(len(data))))
		self.assertIn(self.salary, [row.subject for row in data])
		self.assertIsNone(message)
		blocking, warnings, difference, restatement = (item["value"] for item in summary)
		self.assertEqual((blocking, warnings), (5, 2))
		self.assertEqual((difference, restatement), (95_000, 7_000))

	def test_clean_period_has_no_issues(self):
		_columns, data, message, _chart, summary = execute(
			{"company": COMPANY, "from_date": "2027-02-01", "to_date": "2027-02-28"}
		)
		self.assertEqual(data, [])
		self.assertTrue(message)
		self.assertEqual(summary[0]["indicator"], "Green")
