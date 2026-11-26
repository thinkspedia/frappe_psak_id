import frappe

from frappe_psak_id.psak_id.checks import (
	BALANCE_SHEET_DIFFERENCE,
	BLOCKING,
	CONFLICTING_MAPPINGS,
	CURRENT,
	ERPNEXT_DIFFERENCE,
	OTHER_ITEMS,
	RESTATED,
	RESTATEMENT_DIFFERENCE,
	UNMAPPED_BALANCE,
	WARNING,
	balance_sheet_issues,
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
		cls.deposit = make_account(COMPANY, "Control Deposit", "Current Assets")
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
			("cash", cls.cash, "FP-CA-CASH", {}),
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
			# Entries that net to nothing under the conflicting mappings
			("2027-04-10", cls.cogs, 50_000),
			("2027-04-11", cls.cogs, -50_000),
			# A balance sheet account with no mapping; profit or loss is untouched
			("2027-03-05", cls.deposit, 40_000),
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

		# Which of the two lines gets the balance is arbitrary, so the statement cannot go on
		(conflict,) = self.issues(result, CONFLICTING_MAPPINGS)
		self.assertEqual((conflict.severity, conflict.amount), (BLOCKING, -200_000))
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

	def test_conflict_without_a_balance_is_a_warning(self):
		(conflict,) = self.issues(run_checks(COMPANY, "2027-04-01", "2027-04-30"), CONFLICTING_MAPPINGS)
		self.assertEqual((conflict.severity, conflict.amount), (WARNING, 0))

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
		values = {item["label"]: item["value"] for item in summary}
		self.assertEqual((values["Blocking Issues"], values["Warnings"]), (8, 2))
		# Unmapped expenses leave operating cash flows short too: a warning, as a monthly package
		# has no statement of cash flows
		self.assertEqual(values["Cash Difference"], 95_000)
		self.assertEqual([row.severity for row in data if row.check == "Cash Difference"], [WARNING])
		self.assertEqual(
			(values["Difference to ERPNext Profit and Loss"], values["Restatement Difference"]),
			(95_000, 7_000),
		)
		# The profit missing from the statement is missing from its retained earnings too
		self.assertEqual(
			(values["Difference to ERPNext Balance Sheet"], values["Restated Balance Sheet Difference"]),
			(95_000, 7_000),
		)

	def test_balance_sheet_difference_lasts_until_the_accounts_are_mapped(self):
		_columns, data, message, _chart, summary = execute(
			{"company": COMPANY, "from_date": "2027-02-01", "to_date": "2027-02-28"}
		)
		# February's profit or loss is clean, but January's unmapped profit is still missing from
		# retained earnings on 28 February
		self.assertEqual(
			[(row.check, row.period, row.amount) for row in data],
			[(BALANCE_SHEET_DIFFERENCE, CURRENT, 95_000), (BALANCE_SHEET_DIFFERENCE, RESTATED, 7_000)],
		)
		self.assertEqual(data[0].from_date, "2027-01-01")
		self.assertIsNone(message)
		self.assertEqual(summary[2]["indicator"], "Green")
		self.assertEqual(summary[3]["indicator"], "Red")

	def test_balance_sheet_account_with_a_balance_needs_a_mapping(self):
		self.assertEqual(balance_sheet_issues(COMPANY, "2027-02-28"), [])

		(unmapped,) = balance_sheet_issues(COMPANY, "2027-03-31")
		self.assertEqual(
			(unmapped.check, unmapped.severity, unmapped.account, unmapped.amount),
			(UNMAPPED_BALANCE, BLOCKING, self.deposit, 40_000),
		)
		self.assertEqual(str(unmapped.to_date), "2027-03-31")

		# A mapping from a later date is not in force on the reporting date
		mapping = frappe.get_doc(
			{
				"doctype": "PSAK ID Account Mapping",
				"company": COMPANY,
				"account": self.deposit,
				"report_line": "FP-CA-FIN",
				"valid_from": "2027-04-01",
				"priority": 10,
			}
		).insert()
		self.addCleanup(frappe.delete_doc, "PSAK ID Account Mapping", mapping.name)
		self.assertEqual(len(balance_sheet_issues(COMPANY, "2027-03-31")), 1)
		self.assertEqual(balance_sheet_issues(COMPANY, "2027-04-30"), [])

	def test_report_lists_unmapped_balance_sheet_accounts(self):
		_columns, data, message, _chart, summary = execute(
			{"company": COMPANY, "from_date": "2027-03-01", "to_date": "2027-03-31"}
		)
		(row,) = [row for row in data if row.check == UNMAPPED_BALANCE]
		self.assertEqual((row.subject, row.amount, row.severity), (self.deposit, 40_000, BLOCKING))
		# The deposit is missing from the statement of financial position as well
		(difference,) = [
			row for row in data if row.check == BALANCE_SHEET_DIFFERENCE and row.period == CURRENT
		]
		self.assertEqual(difference.amount, -40_000)
		self.assertIsNone(message)
		self.assertEqual(summary[0]["indicator"], "Red")
