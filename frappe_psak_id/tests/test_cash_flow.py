import frappe

from frappe_psak_id.psak_id.cash_flow import NO_CASH_FLOW_LINE, REVALUATION, compute_cash_flows
from frappe_psak_id.psak_id.checks import (
	BLOCKING,
	CASH_DIFFERENCE,
	INFORMATION,
	NON_CASH_TRANSACTION,
	WARNING,
	cash_flow_issues,
)
from frappe_psak_id.psak_id.report.psak_118_cash_flows.psak_118_cash_flows import execute
from frappe_psak_id.psak_id.report.psak_id_mapping_control.psak_id_mapping_control import (
	execute as mapping_control,
)
from frappe_psak_id.psak_id.statement import NOT_MAPPED
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	get_account,
	make_account,
	make_company,
	make_fiscal_year,
	make_journal_entry,
)

COMPANY = "_Test PSAK Cash Flow Company"


def _lines(statement) -> dict:
	return {line.line_code: line.amount for line in statement.lines}


def _set_up_company() -> frappe._dict:
	make_company(COMPANY, "_TCF")
	accounts = frappe._dict(
		cash=get_account(COMPANY, "Cash"),
		building=make_account(COMPANY, "Buildings", "Fixed Assets"),
		accrued=make_account(COMPANY, "Accrued Liabilities", "Current Liabilities"),
		loan=make_account(COMPANY, "Bank Loan", "Current Liabilities"),
		capital=get_account(COMPANY, "Capital Stock"),
		retained=get_account(COMPANY, "Retained Earnings"),
		sales=get_account(COMPANY, "Sales"),
		admin=get_account(COMPANY, "Administrative Expenses"),
		disposal=make_account(COMPANY, "Gain on Disposal of Assets", "Indirect Income"),
		interest=make_account(COMPANY, "Interest Income", "Indirect Income"),
		right_of_use=make_account(COMPANY, "Right-of-use Assets", "Fixed Assets"),
		lease=make_account(COMPANY, "Lease Liabilities", "Current Liabilities"),
		exchange=make_account(COMPANY, "Unrealized Exchange Gain", "Indirect Income"),
		interest_expense=make_account(COMPANY, "Interest Expense", "Indirect Expenses"),
		accrued_interest=make_account(COMPANY, "Accrued Interest", "Current Liabilities"),
	)
	if not frappe.db.exists("PSAK ID Company Policy", COMPANY):
		frappe.get_doc({"doctype": "PSAK ID Company Policy", "company": COMPANY}).insert()

	frappe.db.delete("PSAK ID Account Mapping", {"company": COMPANY})
	for account, line, extra in (
		(accounts.cash, "FP-CA-CASH", {}),
		(
			accounts.building,
			"FP-NCA-PPE",
			{"cash_flow_line": "CF-INV-PPE-BUY", "cash_flow_line_decrease": "CF-INV-PPE-SELL"},
		),
		(accounts.accrued, "FP-CL-ACCR", {"cash_flow_line": "CF-OP-WC-OL"}),
		(
			accounts.loan,
			"FP-CL-BORR",
			{"cash_flow_line": "CF-FIN-BORR-IN", "cash_flow_line_decrease": "CF-FIN-BORR-OUT"},
		),
		(accounts.capital, "FP-EQ-CAP", {"cash_flow_line": "CF-FIN-EQ"}),
		(accounts.retained, "FP-EQ-RE", {"cash_flow_line": "CF-FIN-DIV"}),
		(accounts.sales, "PL-OP-REV", {}),
		(accounts.admin, "PL-OP-SELL", {"expense_nature": "Other"}),
		(accounts.disposal, "PL-OP-OTH", {"cash_flow_line": "CF-INV-PPE-SELL"}),
		(accounts.interest, "PL-INV-INC", {"cash_flow_line": "CF-INV-INT"}),
		(
			accounts.right_of_use,
			"FP-NCA-ROU",
			{"cash_flow_line": "CF-INV-PPE-BUY", "cash_flow_line_decrease": "CF-OP-DEP"},
		),
		(accounts.lease, "FP-CL-LEASE", {"cash_flow_line": "CF-FIN-LEASE"}),
		(accounts.exchange, "PL-OP-OTH", {}),
		(accounts.interest_expense, "PL-FIN-INT", {"cash_flow_line": "CF-FIN-INT"}),
		(accounts.accrued_interest, "FP-CL-ACCR", {"cash_flow_line": "CF-FIN-INT"}),
	):
		frappe.get_doc(
			{
				"doctype": "PSAK ID Account Mapping",
				"company": COMPANY,
				"account": account,
				"report_line": line,
				"valid_from": "2030-01-01",
				"priority": 10,
				**extra,
			}
		).insert()
	return accounts


def _post(posting_date: str, rows: tuple, voucher_type: str = "Journal Entry"):
	"""Submit a Journal Entry of (account, debit, credit) rows."""
	cost_center = frappe.get_cached_value("Company", COMPANY, "cost_center")
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": voucher_type,
			"company": COMPANY,
			"posting_date": posting_date,
			"accounts": [
				{
					"account": account,
					"debit_in_account_currency": debit,
					"credit_in_account_currency": credit,
					"cost_center": cost_center,
				}
				for account, debit, credit in rows
			],
		}
	)
	je.insert()
	je.submit()
	return je


def _sell_building(accounts, posting_date: str, proceeds: float, carrying_amount: float):
	_post(
		posting_date,
		(
			(accounts.cash, proceeds, 0),
			(accounts.building, 0, carrying_amount),
			(accounts.disposal, 0, proceeds - carrying_amount),
		),
	)


class TestCashFlows(IntegrationTestCase):
	"""Postings up to 2031-03-31 are the fixed base; each test that posts uses later dates."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_fiscal_year(2030)
		make_fiscal_year(2031)
		cls.accounts = a = _set_up_company()
		for posting_date, account, amount, against in (
			("2030-01-05", a.cash, 1_000_000, a.capital),
			("2030-03-01", a.building, 400_000, a.cash),
			("2030-06-01", a.cash, 300_000, a.sales),
			("2031-01-10", a.cash, 500_000, a.loan),
			("2031-02-01", a.cash, 200_000, a.sales),
			("2031-02-15", a.admin, 50_000, a.accrued),
			("2031-03-01", a.building, 100_000, a.cash),
			("2031-03-10", a.cash, 5_000, a.interest),
			("2031-03-20", a.loan, 100_000, a.cash),
			("2031-03-25", a.retained, 30_000, a.cash),
		):
			make_journal_entry(COMPANY, posting_date, account, amount, against)
		_sell_building(a, "2031-03-05", proceeds=80_000, carrying_amount=60_000)

	def test_indirect_method_starts_from_operating_profit_and_reconciles_cash(self):
		statement = compute_cash_flows(COMPANY, "2031-01-01", "2031-03-31")
		lines = _lines(statement)
		# Sales 200,000 - expenses 50,000 + gain on disposal 20,000
		self.assertEqual(lines["CF-OP-START"], 170_000)
		# The gain is part of the disposal proceeds, not an operating cash flow
		self.assertEqual(lines["CF-OP-ADJ"], -20_000)
		self.assertEqual(lines["CF-OP-WC-OL"], 50_000)
		self.assertEqual(lines["CF-SUB-OP"], 200_000)
		self.assertEqual(lines["CF-INV-PPE-BUY"], -100_000)
		self.assertEqual(lines["CF-INV-PPE-SELL"], 80_000)
		self.assertEqual(lines["CF-INV-INT"], 5_000)
		self.assertEqual(lines["CF-SUB-INV"], -15_000)
		# Gross per direction: proceeds and repayments of the same loan are shown apart
		self.assertEqual(lines["CF-FIN-BORR-IN"], 500_000)
		self.assertEqual(lines["CF-FIN-BORR-OUT"], -100_000)
		self.assertEqual(lines["CF-FIN-DIV"], -30_000)
		self.assertEqual(lines["CF-SUB-FIN"], 370_000)
		self.assertEqual(lines["CF-SUB-NET"], 555_000)
		self.assertEqual(lines["CF-OPEN"], 900_000)
		self.assertEqual(lines["CF-SUB-CLOSE"], 1_455_000)
		self.assertEqual(statement.ledger_closing_cash, 1_455_000)
		self.assertEqual(statement.cash_difference, 0)
		self.assertEqual(statement.unmapped, [])

	def test_lines_drill_down_to_their_accounts(self):
		lines = {
			line.line_code: line for line in compute_cash_flows(COMPANY, "2031-01-01", "2031-03-31").lines
		}
		self.assertEqual(
			lines["CF-INV-PPE-SELL"].accounts, sorted([self.accounts.building, self.accounts.disposal])
		)
		# The building's purchases are on another line
		self.assertFalse(lines["CF-INV-PPE-SELL"].ledger_exact)
		self.assertEqual(lines["CF-FIN-DIV"].accounts, [self.accounts.retained])
		self.assertEqual(lines["CF-OP-START"].accounts, [])

	def test_account_without_cash_flow_line_is_listed_and_breaks_the_check(self):
		deposit = make_account(COMPANY, "Unmapped Deposit", "Current Assets")
		make_journal_entry(COMPANY, "2031-04-10", deposit, 25_000, self.accounts.cash)
		# From April the accrual and the interest income lose their cash flow lines
		for account, line in ((self.accounts.accrued, "FP-CL-ACCR"), (self.accounts.interest, "PL-INV-INC")):
			frappe.get_doc(
				{
					"doctype": "PSAK ID Account Mapping",
					"company": COMPANY,
					"account": account,
					"report_line": line,
					"valid_from": "2031-04-01",
					"priority": 10,
				}
			).insert()
		make_journal_entry(COMPANY, "2031-04-15", self.accounts.admin, 10_000, self.accounts.accrued)
		make_journal_entry(COMPANY, "2031-04-20", self.accounts.cash, 3_000, self.accounts.interest)

		statement = compute_cash_flows(COMPANY, "2031-04-01", "2031-04-30")
		self.assertEqual(
			[(row.account, row.reason, row.amount) for row in statement.unmapped],
			[
				(self.accounts.accrued, NO_CASH_FLOW_LINE, 10_000),
				(self.accounts.interest, NO_CASH_FLOW_LINE, 3_000),
				(deposit, NOT_MAPPED, -25_000),
			],
		)
		self.assertEqual(statement.cash_difference, -10_000 - 3_000 + 25_000)

	def test_report_presents_the_same_period_last_year_and_the_check(self):
		frappe.db.set_value("PSAK ID Company Policy", COMPANY, "show_category_headings", 1)
		columns, data, message, _chart, summary = execute(
			{
				"company": COMPANY,
				"from_date": "2031-01-01",
				"to_date": "2031-03-31",
				"comparative": 1,
				"unit": "Thousands",
			}
		)
		self.assertEqual([column["fieldname"] for column in columns], ["line", "p0", "p1"])
		self.assertEqual((columns[2]["from_date"], columns[2]["to_date"]), ("2030-01-01", "2030-03-31"))
		rows = {row.get("line_code"): row for row in data if row.get("line_code")}
		self.assertEqual((rows["CF-SUB-CLOSE"]["p0"], rows["CF-SUB-CLOSE"]["p1"]), (1_455, 600))
		self.assertEqual((rows["CF-FIN-EQ"]["p0"], rows["CF-FIN-EQ"]["p1"]), (0, 1_000))
		self.assertEqual(rows["CF-OPEN"]["p1"], 0)
		self.assertTrue(rows["CF-SUB-CLOSE"]["is_total"])
		self.assertIn(
			"Arus Kas dari Aktivitas Investasi",
			[row["line"] for row in data if row["line_type"] == "Heading"],
		)
		self.assertIsNone(message)
		self.assertEqual(summary[-1]["value"], 0)
		self.assertEqual(summary[-1]["indicator"], "Green")

	def test_non_cash_transaction_is_left_out_and_listed(self):
		a = self.accounts
		lease = make_journal_entry(COMPANY, "2031-05-05", a.right_of_use, 120_000, a.lease)
		make_journal_entry(COMPANY, "2031-05-20", a.lease, 10_000, a.cash)

		statement = compute_cash_flows(COMPANY, "2031-05-01", "2031-05-31")
		lines = _lines(statement)
		# The right-of-use asset is not a purchase for cash; only the lease payment is a cash flow
		self.assertEqual(lines["CF-INV-PPE-BUY"], 0)
		self.assertEqual(lines["CF-FIN-LEASE"], -10_000)
		self.assertEqual(
			[(row.voucher_no, row.account, row.amount) for row in statement.non_cash],
			[(lease.name, a.lease, -120_000), (lease.name, a.right_of_use, 120_000)],
		)
		self.assertEqual(statement.cash_difference, 0)

	def test_revaluation_of_cash_is_the_exchange_rate_effect(self):
		a = self.accounts
		_post("2031-06-30", ((a.cash, 7_000, 0), (a.exchange, 0, 7_000)), voucher_type=REVALUATION)

		statement = compute_cash_flows(COMPANY, "2031-06-01", "2031-06-30")
		lines = _lines(statement)
		self.assertEqual(lines["CF-OP-START"], 7_000)
		self.assertEqual(lines["CF-OP-FX"], -7_000)
		self.assertEqual(lines["CF-SUB-OP"], 0)
		self.assertEqual(lines["CF-FX"], 7_000)
		self.assertEqual(statement.cash_difference, 0)

	def test_interest_follows_the_main_business_activity(self):
		a = self.accounts
		make_journal_entry(COMPANY, "2031-07-10", a.interest_expense, 4_000, a.accrued_interest)
		make_journal_entry(COMPANY, "2031-07-20", a.accrued_interest, 3_000, a.cash)

		lines = _lines(compute_cash_flows(COMPANY, "2031-07-01", "2031-07-31"))
		self.assertEqual((lines["CF-SUB-OP"], lines["CF-FIN-INT"]), (0, -3_000))

		frappe.db.set_value("PSAK ID Company Policy", COMPANY, "main_business_financing", 1)
		statement = compute_cash_flows(COMPANY, "2031-07-01", "2031-07-31")
		lines = _lines(statement)
		# Interest is in operating profit, and the unpaid part is a change in other liabilities
		self.assertEqual(lines["CF-OP-START"], -4_000)
		self.assertEqual(lines["CF-OP-WC-OL"], 1_000)
		self.assertEqual((lines["CF-SUB-OP"], lines["CF-FIN-INT"]), (-3_000, 0))
		self.assertEqual(statement.cash_difference, 0)

	def test_mapping_control_checks_cash_flow_lines_cash_and_non_cash_transactions(self):
		a = self.accounts
		# The first quarter is fully mapped and reconciles
		self.assertEqual(cash_flow_issues(COMPANY, "2031-01-01", "2031-03-31", periodicity="Quarterly"), [])

		idle = make_account(COMPANY, "Idle Deposit", "Current Assets")
		deposit = make_account(COMPANY, "Escrow Deposit", "Current Assets")
		for account in (idle, deposit):
			frappe.get_doc(
				{
					"doctype": "PSAK ID Account Mapping",
					"company": COMPANY,
					"account": account,
					"report_line": "FP-CA-OTH",
					"valid_from": "2031-08-01",
					"priority": 10,
				}
			).insert()
		make_journal_entry(COMPANY, "2031-08-10", idle, 15_000, a.cash)
		make_journal_entry(COMPANY, "2031-09-10", deposit, 40_000, a.cash)
		lease = make_journal_entry(COMPANY, "2031-09-15", a.right_of_use, 60_000, a.lease)

		def issues(periodicity):
			return [
				(issue.check, issue.severity, issue.account or issue.voucher_no, issue.amount)
				for issue in cash_flow_issues(COMPANY, "2031-09-01", "2031-09-30", periodicity=periodicity)
				if issue.account in (idle, deposit) or issue.check in (CASH_DIFFERENCE, NON_CASH_TRANSACTION)
			]

		self.assertEqual(
			issues("Monthly"),
			[
				(NO_CASH_FLOW_LINE, WARNING, deposit, -40_000),
				# No movement in September, but the next one would be left out
				(NO_CASH_FLOW_LINE, WARNING, idle, 15_000),
				(CASH_DIFFERENCE, WARNING, None, 40_000),
				(NON_CASH_TRANSACTION, INFORMATION, lease.name, 60_000),
			],
		)
		# A quarterly package presents cash flows from the start of the fiscal year, idle included
		quarterly = cash_flow_issues(COMPANY, "2031-07-01", "2031-09-30", periodicity="Quarterly")
		self.assertTrue(all(issue.from_date == frappe.utils.getdate("2031-01-01") for issue in quarterly))
		self.assertEqual(
			{issue.severity for issue in quarterly if issue.account in (idle, deposit)}, {BLOCKING}
		)

		_columns, data, message, _chart, summary = mapping_control(
			{
				"company": COMPANY,
				"from_date": "2031-09-01",
				"to_date": "2031-09-30",
				"periodicity": "Quarterly",
			}
		)
		rows = {row.subject: row for row in data}
		self.assertEqual(rows[deposit].severity_label, "Blocking")
		self.assertEqual(rows[lease.name].severity_label, "Information")
		self.assertEqual(rows[lease.name].voucher_type, "Journal Entry")
		self.assertIsNone(message)
		self.assertEqual(summary[-1]["label"], "Cash Difference")
		self.assertNotEqual(summary[-1]["value"], 0)
