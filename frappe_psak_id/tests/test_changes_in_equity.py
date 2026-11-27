import frappe

from frappe_psak_id.psak_id.changes_in_equity import compute_changes_in_equity
from frappe_psak_id.psak_id.report.psak_118_changes_in_equity.psak_118_changes_in_equity import execute
from frappe_psak_id.psak_id.statement import NOT_MAPPED
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	get_account,
	make_account,
	make_company,
	make_fiscal_year,
	make_journal_entry,
)

COMPANY = "_Test PSAK Equity Company"
CLOSING_COMPANY = "_Test PSAK Equity Closing Company"


def _set_up_company(company: str, abbr: str) -> frappe._dict:
	make_company(company, abbr)
	accounts = frappe._dict(
		cash=get_account(company, "Cash"),
		building=make_account(company, "Buildings", "Fixed Assets"),
		dividends_payable=make_account(company, "Dividends Payable", "Current Liabilities"),
		capital=get_account(company, "Capital Stock"),
		retained=get_account(company, "Retained Earnings"),
		opening=get_account(company, "Opening Balance Equity"),
		reserve=make_account(company, "Asset Revaluation Reserve", "Equity"),
		treasury=make_account(company, "Treasury Shares", "Equity"),
		sales=get_account(company, "Sales"),
	)
	if not frappe.db.exists("PSAK ID Company Policy", company):
		frappe.get_doc({"doctype": "PSAK ID Company Policy", "company": company}).insert()

	frappe.db.delete("PSAK ID Account Mapping", {"company": company})
	for account, line, extra in (
		(accounts.cash, "FP-CA-CASH", {}),
		(accounts.building, "FP-NCA-PPE", {"cash_flow_line": "CF-INV-PPE-BUY"}),
		(accounts.dividends_payable, "FP-CL-AP", {"cash_flow_line": "CF-FIN-DIV"}),
		(accounts.capital, "FP-EQ-CAP", {"cash_flow_line": "CF-FIN-EQ"}),
		(accounts.retained, "FP-EQ-RE", {"cash_flow_line": "CF-FIN-DIV"}),
		(accounts.opening, "FP-EQ-OTH", {"cash_flow_line": "CF-FIN-OTH"}),
		(accounts.reserve, "FP-EQ-OCI", {"oci_line": "OCI-NR-REV", "cash_flow_line": "CF-FIN-OTH"}),
		(accounts.treasury, "FP-EQ-TREAS", {"cash_flow_line": "CF-FIN-OTH"}),
		(accounts.sales, "PL-OP-REV", {}),
	):
		frappe.get_doc(
			{
				"doctype": "PSAK ID Account Mapping",
				"company": company,
				"account": account,
				"report_line": line,
				"valid_from": "2030-01-01",
				"priority": 10,
				**extra,
			}
		).insert()
	return accounts


def _cells(statement) -> dict:
	return {
		(row.line_code, component): amount
		for row in statement.rows
		for component, amount in row.amounts.items()
		if amount
	}


def _totals(statement) -> dict:
	return {row.line_code: row.total for row in statement.rows}


class TestChangesInEquity(IntegrationTestCase):
	"""Postings up to 2031-03-31 are the fixed base."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_fiscal_year(2030)
		make_fiscal_year(2031)
		cls.accounts = a = _set_up_company(COMPANY, "_TEQ")
		for posting_date, account, amount, against in (
			("2030-01-05", a.cash, 1_000_000, a.capital),
			("2030-06-01", a.cash, 300_000, a.sales),
			("2031-01-10", a.cash, 200_000, a.capital),
			("2031-02-01", a.cash, 150_000, a.sales),
			# Dividends declared, then paid
			("2031-02-10", a.retained, 40_000, a.dividends_payable),
			("2031-02-20", a.dividends_payable, 40_000, a.cash),
			# Revaluation surplus, part of it realised into retained earnings
			("2031-03-01", a.building, 50_000, a.reserve),
			("2031-03-10", a.reserve, 10_000, a.retained),
			("2031-03-15", a.treasury, 20_000, a.cash),
			("2031-03-20", a.cash, 5_000, a.opening),
		):
			make_journal_entry(COMPANY, posting_date, account, amount, against)

	def test_movements_are_presented_per_component(self):
		statement = compute_changes_in_equity(COMPANY, "2031-01-01", "2031-03-31")
		cells = _cells(statement)
		self.assertEqual(
			[component.line_code for component in statement.components],
			["FP-EQ-CAP", "FP-EQ-TREAS", "FP-EQ-OCI", "FP-EQ-RE", "FP-EQ-OTH"],
		)
		# 2030's profit is in retained earnings without a Period Closing Voucher
		self.assertEqual(cells[("EQ-OPEN", "FP-EQ-CAP")], 1_000_000)
		self.assertEqual(cells[("EQ-OPEN", "FP-EQ-RE")], 300_000)
		self.assertEqual(cells[("EQ-PL", "FP-EQ-RE")], 150_000)
		self.assertEqual(cells[("EQ-OCI", "FP-EQ-OCI")], 50_000)
		self.assertEqual(cells[("EQ-SUB-TCI", "FP-EQ-RE")], 150_000)
		# Declared dividends are on the cash flow line of retained earnings, not of the payable
		self.assertEqual(cells[("EQ-DIV", "FP-EQ-RE")], -40_000)
		self.assertEqual(cells[("EQ-ISSUE", "FP-EQ-CAP")], 200_000)
		self.assertEqual(cells[("EQ-TREAS", "FP-EQ-TREAS")], -20_000)
		# A voucher of equity accounts only is a transfer, not other comprehensive income
		self.assertEqual(cells[("EQ-TRANSFER", "FP-EQ-OCI")], -10_000)
		self.assertEqual(cells[("EQ-TRANSFER", "FP-EQ-RE")], 10_000)
		self.assertEqual(cells[("EQ-OTH", "FP-EQ-OTH")], 5_000)
		self.assertEqual(cells[("EQ-CLOSE", "FP-EQ-RE")], 420_000)

		totals = _totals(statement)
		self.assertEqual(totals["EQ-OPEN"], 1_300_000)
		self.assertEqual(totals["EQ-SUB-TCI"], 200_000)
		self.assertEqual(totals["EQ-TRANSFER"], 0)
		self.assertEqual(totals["EQ-CLOSE"], 1_645_000)

	def test_closing_balances_match_the_statement_of_financial_position(self):
		statement = compute_changes_in_equity(COMPANY, "2031-01-01", "2031-03-31")
		self.assertEqual(statement.closing_equity, 1_645_000)
		self.assertEqual(statement.position_equity, 1_645_000)
		self.assertEqual(statement.equity_difference, 0)
		self.assertEqual(statement.component_differences, [])
		self.assertEqual(statement.total_comprehensive_income, 200_000)
		self.assertEqual(statement.comprehensive_income_difference, 0)
		self.assertEqual(statement.unmapped, [])

	def test_mapping_with_a_line_for_decreases_splits_movements(self):
		mapping = frappe.db.get_value(
			"PSAK ID Account Mapping", {"company": COMPANY, "account": self.accounts.capital}
		)
		frappe.db.set_value("PSAK ID Account Mapping", mapping, "cash_flow_line_decrease", "CF-FIN-OTH")
		self.addCleanup(
			frappe.db.set_value, "PSAK ID Account Mapping", mapping, "cash_flow_line_decrease", None
		)
		make_journal_entry(COMPANY, "2031-04-10", self.accounts.capital, 30_000, self.accounts.cash)
		make_journal_entry(COMPANY, "2031-04-11", self.accounts.cash, 70_000, self.accounts.capital)

		cells = _cells(compute_changes_in_equity(COMPANY, "2031-04-01", "2031-04-30"))
		self.assertEqual(cells[("EQ-ISSUE", "FP-EQ-CAP")], 70_000)
		self.assertEqual(cells[("EQ-OTH", "FP-EQ-CAP")], -30_000)

	def test_equity_component_other_than_the_report_line_is_reported(self):
		mapping = frappe.db.get_value(
			"PSAK ID Account Mapping", {"company": COMPANY, "account": self.accounts.opening}
		)
		frappe.db.set_value("PSAK ID Account Mapping", mapping, "equity_component", "FP-EQ-RE")
		self.addCleanup(
			frappe.db.set_value, "PSAK ID Account Mapping", mapping, "equity_component", "FP-EQ-OTH"
		)

		statement = compute_changes_in_equity(COMPANY, "2031-01-01", "2031-03-31")
		self.assertEqual(_cells(statement)[("EQ-OTH", "FP-EQ-RE")], 5_000)
		self.assertEqual(statement.equity_difference, 0)
		self.assertEqual(
			{row.component: row.difference for row in statement.component_differences},
			{"FP-EQ-RE": 5_000, "FP-EQ-OTH": -5_000},
		)

	def test_unmapped_equity_account_is_left_out(self):
		make_account(COMPANY, "Share Premium", "Equity")
		premium = get_account(COMPANY, "Share Premium")
		make_journal_entry(COMPANY, "2031-05-10", self.accounts.cash, 25_000, premium)

		statement = compute_changes_in_equity(COMPANY, "2031-05-01", "2031-05-31")
		self.assertEqual(
			[(row.account, row.reason, row.amount) for row in statement.unmapped],
			[(premium, NOT_MAPPED, 25_000)],
		)

	def test_report_presents_the_comparative_block_first(self):
		columns, data, _message, _chart, summary = execute(
			{"company": COMPANY, "from_date": "2031-01-01", "to_date": "2031-03-31", "comparative": 1}
		)
		self.assertEqual(columns[-1]["fieldname"], "total")
		self.assertEqual(
			[column["component"] for column in columns[1:-1]],
			["FP-EQ-CAP", "FP-EQ-TREAS", "FP-EQ-OCI", "FP-EQ-RE", "FP-EQ-OTH"],
		)
		headings = [row for row in data if row.line_type == "Heading"]
		self.assertEqual([row.block for row in headings], [1, 0])

		closing = {row.block: row for row in data if row.get("line_code") == "EQ-CLOSE"}
		# Q1 2030: share capital issued, profit of the quarter not yet earned
		self.assertEqual(closing[1].total, 1_000_000)
		self.assertEqual(closing[0].total, 1_645_000)
		self.assertEqual(summary[2]["value"], 0)

		issue = next(row for row in data if row.get("line_code") == "EQ-ISSUE" and row.block == 0)
		ledger = issue.ledger[columns[1]["fieldname"]]
		self.assertEqual(ledger["accounts"], [self.accounts.capital])


class TestChangesInEquityWithClosing(IntegrationTestCase):
	"""Period Closing Vouchers are left out; the profit they close is counted once."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_fiscal_year(2032)
		make_fiscal_year(2033)
		cls.accounts = a = _set_up_company(CLOSING_COMPANY, "_TEX")
		for posting_date, account, amount, against in (
			("2032-01-05", a.cash, 500_000, a.capital),
			("2032-06-01", a.cash, 120_000, a.sales),
			("2033-02-01", a.cash, 80_000, a.sales),
		):
			make_journal_entry(CLOSING_COMPANY, posting_date, account, amount, against)
		# v16 processes closing vouchers in a background job unless the legacy controller is on
		if frappe.get_meta("Accounts Settings").has_field("use_legacy_controller_for_pcv"):
			frappe.db.set_single_value("Accounts Settings", "use_legacy_controller_for_pcv", 1)

	def _close(self, year: int):
		pcv = frappe.get_doc(
			{
				"doctype": "Period Closing Voucher",
				"company": CLOSING_COMPANY,
				"fiscal_year": frappe.db.get_value("Fiscal Year", {"year_start_date": f"{year}-01-01"}),
				"transaction_date": f"{year}-12-31",
				"posting_date": f"{year}-12-31",
				"period_start_date": f"{year}-01-01",
				"period_end_date": f"{year}-12-31",
				"closing_account_head": self.accounts.retained,
				"remarks": "Year end closing",
			}
		)
		pcv.insert()
		pcv.submit()
		if not frappe.db.exists("GL Entry", {"voucher_no": pcv.name}):
			# ERPNext moves the closing to a background job on a ledger of over 100,000 entries
			from erpnext.accounts.doctype.period_closing_voucher.period_closing_voucher import (
				process_gl_and_closing_entries,
			)

			process_gl_and_closing_entries(pcv)

	def _retained_earnings(self, from_date, to_date) -> tuple:
		statement = compute_changes_in_equity(CLOSING_COMPANY, from_date, to_date)
		self.assertEqual(statement.equity_difference, 0)
		cells = _cells(statement)
		return (
			cells.get(("EQ-OPEN", "FP-EQ-RE"), 0),
			cells.get(("EQ-PL", "FP-EQ-RE"), 0),
			cells.get(("EQ-CLOSE", "FP-EQ-RE"), 0),
		)

	def test_profit_is_counted_once_before_and_after_closing(self):
		self.assertEqual(self._retained_earnings("2033-01-01", "2033-03-31"), (120_000, 80_000, 200_000))
		self.assertEqual(self._retained_earnings("2032-03-01", "2033-03-31"), (0, 200_000, 200_000))

		self._close(2032)
		self.assertEqual(self._retained_earnings("2033-01-01", "2033-03-31"), (120_000, 80_000, 200_000))
		# A period across the closing: the voucher is left out, the profit it closes is in EQ-PL
		self.assertEqual(self._retained_earnings("2032-03-01", "2033-03-31"), (0, 200_000, 200_000))
