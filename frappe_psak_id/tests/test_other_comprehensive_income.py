import frappe

from frappe_psak_id.psak_id.report.psak_118_profit_or_loss.psak_118_profit_or_loss import execute
from frappe_psak_id.psak_id.statement import compute, compute_periods
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	get_account,
	make_account,
	make_company,
	make_cost_center,
	make_fiscal_year,
	make_journal_entry,
)

COMPANY = "_Test PSAK OCI Company"


class TestOtherComprehensiveIncome(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COMPANY, "_TPI")
		make_fiscal_year(2034)
		cash = get_account(COMPANY, "Cash")
		sales = get_account(COMPANY, "Sales")
		building = make_account(COMPANY, "Buildings", "Fixed Assets")
		deferred_tax = make_account(COMPANY, "Deferred Tax Liability", "Current Liabilities")
		retained = get_account(COMPANY, "Retained Earnings")
		reserve = make_account(COMPANY, "Revaluation Reserve", "Equity")
		reserve_tax = make_account(COMPANY, "Revaluation Reserve Tax", "Equity")
		cls.reserve, cls.reserve_tax = reserve, reserve_tax
		cls.branch = make_cost_center(COMPANY, "OCI Branch")

		if not frappe.db.exists("PSAK ID Company Policy", COMPANY):
			frappe.get_doc({"doctype": "PSAK ID Company Policy", "company": COMPANY}).insert()

		frappe.db.delete("PSAK ID Account Mapping", {"company": COMPANY})
		for account, line, extra in (
			(cash, "FP-CA-CASH", {}),
			(building, "FP-NCA-PPE", {}),
			(deferred_tax, "FP-NCL-DTL", {}),
			(retained, "FP-EQ-RE", {}),
			(sales, "PL-OP-REV", {}),
			(reserve, "FP-EQ-OCI", {"oci_line": "OCI-NR-REV"}),
			(reserve_tax, "FP-EQ-OCI", {"oci_line": "OCI-NR-TAX"}),
		):
			frappe.get_doc(
				{
					"doctype": "PSAK ID Account Mapping",
					"company": COMPANY,
					"account": account,
					"report_line": line,
					"valid_from": "2034-01-01",
					"priority": 10,
					**extra,
				}
			).insert()

		for posting_date, account, amount, against in (
			("2034-02-01", cash, 100_000, sales),
			# Revaluation surplus and its deferred tax
			("2034-03-01", building, 50_000, reserve),
			("2034-03-01", reserve_tax, 11_000, deferred_tax),
			# Part of the surplus realised: a transfer between equity components, not OCI
			("2034-04-01", reserve, 5_000, retained),
		):
			make_journal_entry(COMPANY, posting_date, account, amount, against)

	@staticmethod
	def _oci_lines(statement):
		return {line.line_code: line.amount for line in statement.oci_lines}

	def test_oci_and_total_comprehensive_income(self):
		statement = compute(COMPANY, "2034-01-01", "2034-12-31")
		lines = self._oci_lines(statement)
		self.assertTrue(statement.has_other_comprehensive_income)
		self.assertEqual(lines["OCI-NR-REV"], 50_000)
		self.assertEqual(lines["OCI-NR-TAX"], -11_000)
		self.assertEqual(lines["OCI-SUB-NR"], 39_000)
		self.assertEqual(lines["OCI-SUB-R"], 0)
		self.assertEqual(statement.other_comprehensive_income, 39_000)
		self.assertEqual(statement.profit_or_loss, 100_000)
		self.assertEqual(statement.total_comprehensive_income, 139_000)
		self.assertEqual(lines["OCI-SUB-TCI"], 139_000)
		self.assertEqual(statement.ledger_difference, 0)

	def test_each_period_has_its_own_movements(self):
		first, second = compute_periods(COMPANY, [("2034-01-01", "2034-03-31"), ("2034-04-01", "2034-06-30")])
		self.assertEqual(first.other_comprehensive_income, 39_000)
		self.assertEqual(second.other_comprehensive_income, 0)
		self.assertEqual(second.total_comprehensive_income, 0)

	def test_a_cost_center_statement_has_no_oci(self):
		statement = compute(COMPANY, "2034-01-01", "2034-12-31", cost_center=self.branch)
		self.assertFalse(statement.has_other_comprehensive_income)
		self.assertEqual(statement.other_comprehensive_income, 0)

	def test_report_presents_oci_below_profit_or_loss(self):
		_columns, data, *_rest = execute(
			{
				"company": COMPANY,
				"from_date": "2034-01-01",
				"to_date": "2034-12-31",
				"periodicity": "Yearly",
			}
		)
		codes = [row.get("line_code") for row in data]
		self.assertLess(codes.index("PL-SUB-PL"), codes.index("OCI-NR-REV"))
		heading = data[codes.index("OCI-NR-REV") - 1]
		self.assertEqual(heading.line_type, "Heading")
		self.assertEqual(heading.line, "Penghasilan Komprehensif Lain")
		total = data[codes.index("OCI-SUB-TCI")]
		self.assertTrue(total.is_total)
		self.assertEqual(total.p0, 139_000)
		self.assertEqual(data[codes.index("OCI-NR-REV")].ledger["p0"]["accounts"], [self.reserve])
