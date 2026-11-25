import frappe

from frappe_psak_id.psak_id.financial_position import (
	compute_financial_position,
	compute_positions,
	prior_year_end,
)
from frappe_psak_id.psak_id.report.psak_118_financial_position.psak_118_financial_position import (
	execute,
)
from frappe_psak_id.psak_id.statement import NOT_MAPPED, evaluate_lines
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	erpnext_total_assets,
	get_account,
	make_account,
	make_company,
	make_fiscal_year,
	make_journal_entry,
)

COMPANY = "_Test PSAK Position Company"
CLOSING_COMPANY = "_Test PSAK Closing Company"


def _lines(position) -> dict:
	return {line.line_code: line.amount for line in position.lines}


def _set_up_company(company: str, abbr: str, valid_from: str) -> frappe._dict:
	"""A company with balance sheet and profit or loss mappings for the accounts the tests post to."""
	make_company(company, abbr)
	accounts = frappe._dict(
		cash=get_account(company, "Cash"),
		building=make_account(company, "Buildings", "Fixed Assets"),
		accrued=make_account(company, "Accrued Liabilities", "Current Liabilities"),
		capital=get_account(company, "Capital Stock"),
		retained=get_account(company, "Retained Earnings"),
		sales=get_account(company, "Sales"),
		admin=get_account(company, "Administrative Expenses"),
	)
	if not frappe.db.exists("PSAK ID Company Policy", company):
		frappe.get_doc({"doctype": "PSAK ID Company Policy", "company": company}).insert()

	frappe.db.delete("PSAK ID Account Mapping", {"company": company})
	for account, line, extra in (
		(accounts.cash, "FP-CA-CASH", {}),
		(accounts.building, "FP-NCA-PPE", {}),
		(accounts.accrued, "FP-CL-ACCR", {}),
		(accounts.capital, "FP-EQ-CAP", {}),
		(accounts.retained, "FP-EQ-RE", {}),
		(accounts.sales, "PL-OP-REV", {}),
		(accounts.admin, "PL-OP-SELL", {"expense_nature": "Other"}),
	):
		frappe.get_doc(
			{
				"doctype": "PSAK ID Account Mapping",
				"company": company,
				"account": account,
				"report_line": line,
				"valid_from": valid_from,
				"priority": 10,
				**extra,
			}
		).insert()
	return accounts


class TestSubtotalClassification(IntegrationTestCase):
	def test_category_term_with_classification_adds_only_that_classification(self):
		def line(code, classification=None, line_type="Line", formula=None):
			return frappe._dict(
				name=code,
				line_type=line_type,
				classification=classification,
				subtotal_formula=formula,
				disabled=0,
			)

		lines = [
			line("PPE", "Non-current"),
			line("CASH", "Current"),
			line("NCA", line_type="Subtotal", formula="+CAT:Asset/Non-current"),
			line("CA", line_type="Subtotal", formula="+CAT:Asset/Current"),
			line("TA", line_type="Subtotal", formula="+CAT:Asset"),
		]
		amounts = evaluate_lines(lines, {"PPE": 400.0, "CASH": 150.0}, {"PPE": "Asset", "CASH": "Asset"})
		self.assertEqual((amounts["NCA"], amounts["CA"], amounts["TA"]), (400.0, 150.0, 550.0))


class TestFinancialPosition(IntegrationTestCase):
	"""Postings up to 2031-03-31 are the fixed base; each test posts after that date."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_fiscal_year(2030)
		make_fiscal_year(2031)
		cls.accounts = _set_up_company(COMPANY, "_TPP", "2030-01-01")
		a = cls.accounts
		for posting_date, account, amount, against in (
			("2030-01-05", a.cash, 1_000_000, a.capital),
			("2030-03-01", a.building, 400_000, a.cash),
			("2030-06-01", a.cash, 300_000, a.sales),
			("2030-07-01", a.admin, 100_000, a.accrued),
			("2031-02-01", a.cash, 200_000, a.sales),
			("2031-02-15", a.admin, 50_000, a.cash),
		):
			make_journal_entry(COMPANY, posting_date, account, amount, against)

	def _assert_matches_erpnext(self, position):
		self.assertEqual(position.balance_difference, 0)
		self.assertEqual(position.ledger_difference, 0)
		self.assertEqual(
			position.ledger_total_assets,
			erpnext_total_assets(COMPANY, position.from_date, position.to_date, position.finance_book),
		)

	def test_lines_and_classified_subtotals_match_erpnext(self):
		position = compute_financial_position(COMPANY, "2031-03-31")
		lines = _lines(position)
		self.assertEqual(lines["FP-CA-CASH"], 1_050_000)
		self.assertEqual(lines["FP-SUB-NCA"], 400_000)
		self.assertEqual(lines["FP-SUB-CA"], 1_050_000)
		self.assertEqual(lines["FP-SUB-TA"], 1_450_000)
		self.assertEqual(lines["FP-SUB-TL"], 100_000)
		self.assertEqual(lines["FP-EQ-CAP"], 1_000_000)
		self.assertEqual(lines["FP-SUB-TLE"], 1_450_000)
		self.assertEqual(position.from_date, frappe.utils.getdate("2031-01-01"))
		self._assert_matches_erpnext(position)

	def test_retained_earnings_hold_this_year_and_unclosed_earlier_years(self):
		position = compute_financial_position(COMPANY, "2031-03-31")
		# 2030 left 200,000 that no Period Closing Voucher moved; 2031 adds 150,000 so far
		self.assertEqual(position.profit_or_loss, 350_000)
		self.assertEqual(_lines(position)["FP-EQ-RE"], 350_000)
		self.assertEqual(position.profit_or_loss_difference, 0)

	def test_comparative_is_the_prior_year_end(self):
		self.assertEqual(prior_year_end(COMPANY, "2031-03-31"), frappe.utils.getdate("2030-12-31"))
		current, comparative = compute_positions(COMPANY, ["2031-03-31", "2030-12-31"])
		lines = _lines(comparative)
		self.assertEqual(lines["FP-SUB-TA"], 1_300_000)
		self.assertEqual(lines["FP-EQ-RE"], 200_000)
		self.assertEqual(lines["FP-SUB-TLE"], 1_300_000)
		self._assert_matches_erpnext(current)
		self._assert_matches_erpnext(comparative)

	def test_finance_book_matches_erpnext(self):
		book = "_Test PSAK Position Book"
		if not frappe.db.exists("Finance Book", book):
			frappe.get_doc({"doctype": "Finance Book", "finance_book_name": book}).insert()
		make_journal_entry(
			COMPANY, "2031-05-10", self.accounts.cash, 70_000, self.accounts.sales, finance_book=book
		)
		without_book = compute_financial_position(COMPANY, "2031-05-31")
		with_book = compute_financial_position(COMPANY, "2031-05-31", finance_book=book)
		self.assertEqual(with_book.total_assets - without_book.total_assets, 70_000)
		self.assertEqual(_lines(with_book)["FP-EQ-RE"] - _lines(without_book)["FP-EQ-RE"], 70_000)
		self._assert_matches_erpnext(without_book)
		self._assert_matches_erpnext(with_book)

	def test_unmapped_account_is_listed_and_breaks_the_check(self):
		deposit = make_account(COMPANY, "Unmapped Deposit", "Current Assets")
		make_journal_entry(COMPANY, "2031-06-10", deposit, 25_000, self.accounts.cash)
		position = compute_financial_position(COMPANY, "2031-06-30")
		self.assertEqual(
			[(row.account, row.reason, row.amount) for row in position.unmapped],
			[(deposit, NOT_MAPPED, 25_000)],
		)
		self.assertEqual(position.ledger_difference, -25_000)
		self.assertEqual(position.balance_difference, -25_000)
		self.assertEqual(
			position.ledger_total_assets,
			erpnext_total_assets(COMPANY, position.from_date, position.to_date),
		)

	def test_report_presents_the_comparative_and_the_check(self):
		frappe.db.set_value("PSAK ID Company Policy", COMPANY, "show_category_headings", 1)
		columns, data, message, _chart, summary = execute(
			{"company": COMPANY, "to_date": "2031-03-31", "comparative": 1, "unit": "Thousands"}
		)
		self.assertEqual([column["fieldname"] for column in columns], ["line", "p0", "p1"])
		self.assertEqual(columns[1]["from_date"], "2031-01-01")
		rows = {row.get("line_code"): row for row in data if row.get("line_code")}
		self.assertEqual((rows["FP-SUB-TA"]["p0"], rows["FP-SUB-TA"]["p1"]), (1_450, 1_300))
		self.assertTrue(rows["FP-SUB-TLE"]["is_total"])
		self.assertEqual(rows["FP-CA-CASH"]["ledger"]["p0"]["accounts"], [self.accounts.cash])
		self.assertFalse(rows["FP-EQ-RE"]["ledger"]["p0"]["exact"])
		self.assertIn("Aset Lancar", [row["line"] for row in data if row["line_type"] == "Heading"])
		self.assertIsNone(message)
		self.assertEqual(summary[-1]["value"], 0)
		self.assertEqual(summary[-1]["indicator"], "Green")

		_columns, _data, _message, _chart, _summary = execute({"company": COMPANY, "to_date": "2031-03-31"})
		self.assertEqual(len(_columns), 2)


class TestFinancialPositionWithClosing(IntegrationTestCase):
	"""Period Closing Vouchers move the year's profit to retained earnings; it must not count twice."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_fiscal_year(2032)
		make_fiscal_year(2033)
		cls.accounts = _set_up_company(CLOSING_COMPANY, "_TPX", "2032-01-01")
		a = cls.accounts
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

	def _retained_earnings(self, to_date):
		position = compute_financial_position(CLOSING_COMPANY, to_date)
		self.assertEqual(position.balance_difference, 0)
		self.assertEqual(position.ledger_difference, 0)
		self.assertEqual(
			position.ledger_total_assets,
			erpnext_total_assets(CLOSING_COMPANY, position.from_date, position.to_date),
		)
		return _lines(position)["FP-EQ-RE"]

	def test_profit_is_counted_once_before_and_after_closing(self):
		self.assertEqual(self._retained_earnings("2032-12-31"), 120_000)
		self.assertEqual(self._retained_earnings("2033-03-31"), 200_000)

		self._close(2032)
		self.assertEqual(self._retained_earnings("2032-12-31"), 120_000)
		self.assertEqual(self._retained_earnings("2033-03-31"), 200_000)

		self._close(2033)
		self.assertEqual(self._retained_earnings("2033-12-31"), 200_000)
