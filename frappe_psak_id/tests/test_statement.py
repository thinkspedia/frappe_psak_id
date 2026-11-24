import frappe

from frappe_psak_id.psak_id.statement import (
	NOT_MAPPED,
	Condition,
	Mapping,
	StatementError,
	compute,
	compute_periods,
	evaluate_lines,
	ledger_filters,
	presentation_order,
	resolve_mapping,
	tied_mappings,
)
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	erpnext_net_profit,
	get_account,
	make_account,
	make_company,
	make_cost_center,
	make_fiscal_year,
	make_journal_entry,
)

COMPANY = "_Test PSAK Statement Company"


class TestResolveAndEvaluate(IntegrationTestCase):
	def test_conditional_mapping_wins_then_unconditional_fallback(self):
		fallback = Mapping("M1", "PL-INV-INC", 1, None)
		conditional = Mapping("M2", "PL-OP-OTH", 5, Condition("cost_center", frozenset({"Ops"})))
		group = frappe._dict(account="A", cost_center="Ops")
		self.assertEqual(resolve_mapping(group, [fallback, conditional]), conditional)
		group.cost_center = "Main"
		self.assertEqual(resolve_mapping(group, [fallback, conditional]), fallback)
		self.assertIsNone(resolve_mapping(group, [conditional]))

	def test_lowest_priority_number_wins_among_matches(self):
		first = Mapping("M1", "PL-OP-REV", 2, Condition("project", frozenset({"P"})))
		second = Mapping("M2", "PL-OP-OTH", 1, Condition("project", frozenset({"P"})))
		self.assertEqual(resolve_mapping(frappe._dict(project="P"), [first, second]), second)

	def test_matching_conditions_at_one_priority_naming_other_lines_are_tied(self):
		by_cost_center = Mapping("M1", "PL-OP-OTH", 5, Condition("cost_center", frozenset({"Ops"})))
		by_project = Mapping("M2", "PL-INV-INC", 5, Condition("project", frozenset({"P"})))
		same_line = Mapping("M3", "PL-OP-OTH", 5, Condition("project", frozenset({"P"})))
		lower = Mapping("M4", "PL-FIN-OTH", 6, Condition("project", frozenset({"P"})))
		group = frappe._dict(cost_center="Ops", project="P")
		candidates = [by_cost_center, by_project, same_line, lower]
		chosen = resolve_mapping(group, candidates)
		self.assertEqual(chosen, by_cost_center)
		self.assertEqual(tied_mappings(group, candidates, chosen), [by_project])
		group.project = "Q"
		self.assertEqual(tied_mappings(group, candidates, chosen), [])

	def test_ledger_filters_select_the_entries_of_a_split_account(self):
		groups = [
			frappe._dict(account="A", cost_center="Ops", party="X", line="L1"),
			frappe._dict(account="A", cost_center="Main", party="X", line="L2"),
			frappe._dict(account="B", cost_center="Main", party="Y", line="L1"),
			frappe._dict(account="B", cost_center="Main", party="Z", line="L3"),
		]
		# A is split by cost center, which the General Ledger filters on; B is split by party
		self.assertEqual(
			ledger_filters("L2", groups[1:2], groups),
			{
				"accounts": ["A"],
				"ledger_filters": {"cost_center": ["Main"]},
				"ledger_exact": True,
				"ledger_accounts": [],
			},
		)
		on_l1 = ledger_filters("L1", [groups[0], groups[2]], groups)
		# Main is needed for B, so one set of filters also shows A in Main, which is on L2
		self.assertEqual(on_l1["ledger_filters"], {})
		self.assertFalse(on_l1["ledger_exact"])
		# Per account, A is exact; B is not, the ledger cannot filter on party
		self.assertEqual(
			[(item["account"], item["filters"], item["exact"]) for item in on_l1["ledger_accounts"]],
			[("A", {"cost_center": ["Ops"]}, True), ("B", {}, False)],
		)

	def test_subtotals_follow_formulas_and_categories(self):
		line = lambda code, line_type="Line", formula=None: frappe._dict(  # noqa: E731
			name=code, line_type=line_type, subtotal_formula=formula, disabled=0
		)
		lines = [
			line("REV"),
			line("COS"),
			line("INV"),
			line("GP", "Subtotal", "+REV +COS"),
			line("OP", "Subtotal", "+CAT:Operating"),
			line("PBFT", "Subtotal", "+OP +CAT:Investing"),
		]
		amounts = evaluate_lines(
			lines,
			{"REV": 100.0, "COS": -60.0, "INV": 7.0},
			{"REV": "Operating", "COS": "Operating", "INV": "Investing"},
		)
		self.assertEqual((amounts["GP"], amounts["OP"], amounts["PBFT"]), (40.0, 40.0, 47.0))

	def test_line_moved_to_operating_is_presented_above_the_operating_subtotal(self):
		line = lambda code, category=None, line_type="Line", formula=None: frappe._dict(  # noqa: E731
			name=code, category=category, line_type=line_type, subtotal_formula=formula
		)
		lines = [
			line("REV", "Operating"),
			line("OP", line_type="Subtotal", formula="+CAT:Operating"),
			line("ASSOC", "Investing"),
			line("INV", "Investing"),
			line("PBFT", line_type="Subtotal", formula="+OP +CAT:Investing"),
		]
		categories = {"REV": "Operating", "ASSOC": "Investing", "INV": "Operating"}
		self.assertEqual(
			[line.name for line in presentation_order(lines, categories)],
			["REV", "INV", "OP", "ASSOC", "PBFT"],
		)


class TestCompute(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COMPANY, "_TPS")
		make_fiscal_year(2027)
		cls.cash = get_account(COMPANY, "Cash")
		cls.sales = get_account(COMPANY, "Sales")
		cls.cogs = get_account(COMPANY, "Cost of Goods Sold")
		cls.salary = get_account(COMPANY, "Salary")
		cls.admin = get_account(COMPANY, "Administrative Expenses")
		cls.interest_income = make_account(COMPANY, "Interest Income", "Indirect Income")
		cls.interest_expense = make_account(COMPANY, "Interest Expense", "Indirect Expenses")
		cls.tax = make_account(COMPANY, "Tax Expense", "Indirect Expenses")
		cls.main = frappe.get_cached_value("Company", COMPANY, "cost_center")
		cls.ops = make_cost_center(COMPANY, "Financing Ops")

		if not frappe.db.exists("PSAK ID Company Policy", COMPANY):
			frappe.get_doc({"doctype": "PSAK ID Company Policy", "company": COMPANY}).insert()

		frappe.db.delete("PSAK ID Account Mapping", {"company": COMPANY})
		for account, line, extra in (
			(cls.sales, "PL-OP-REV", {}),
			(cls.cogs, "PL-OP-COS", {"expense_nature": "Raw Materials and Goods"}),
			(cls.salary, "PL-OP-GA", {"expense_nature": "Employee Benefits"}),
			(cls.interest_income, "PL-INV-INC", {}),
			(
				cls.interest_income,
				"PL-OP-OTH",
				{
					"condition_type": "Cost Center",
					"condition_doctype": "Cost Center",
					"condition_value": cls.ops,
					"priority": 1,
				},
			),
			(cls.interest_expense, "PL-FIN-INT", {}),
			(cls.tax, "PL-TAX", {}),
		):
			frappe.get_doc(
				{
					"doctype": "PSAK ID Account Mapping",
					"company": COMPANY,
					"account": account,
					"report_line": line,
					"valid_from": "2027-01-01",
					"priority": 10,
					**extra,
				}
			).insert()

	def _post(self, posting_date, account, amount, **kwargs):
		make_journal_entry(COMPANY, posting_date, account, amount, self.cash, **kwargs)

	def _set_policy(self, **values):
		policy = frappe.get_doc("PSAK ID Company Policy", COMPANY)
		previous = {field: policy.get(field) for field in values}
		policy.update(values)
		policy.save()
		self.addCleanup(lambda: frappe.get_doc("PSAK ID Company Policy", COMPANY).update(previous).save())

	def _assert_ledger_is_erpnext(self, result):
		"""The statement's ledger total must be ERPNext's net profit for the same filters."""
		self.assertEqual(
			result.ledger_profit_or_loss,
			erpnext_net_profit(
				COMPANY, result.from_date, result.to_date, result.cost_center, result.finance_book
			),
		)

	@staticmethod
	def _lines(result):
		return {line.line_code: line for line in result.lines}

	def test_subtotals_and_reconciliation_to_erpnext(self):
		self._post("2027-01-10", self.sales, -1_000_000)
		self._post("2027-01-11", self.cogs, 600_000)
		self._post("2027-01-12", self.salary, 100_000)
		self._post("2027-01-13", self.interest_income, -50_000)
		self._post("2027-01-14", self.interest_expense, 20_000)
		self._post("2027-01-15", self.tax, 30_000)

		result = compute(COMPANY, "2027-01-01", "2027-01-31")
		lines = self._lines(result)
		expected = {
			"PL-OP-REV": 1_000_000,
			"PL-OP-COS": -600_000,
			"PL-SUB-GP": 400_000,
			"PL-OP-GA": -100_000,
			"PL-SUB-OP": 300_000,
			"PL-INV-INC": 50_000,
			"PL-SUB-PBFT": 350_000,
			"PL-FIN-INT": -20_000,
			"PL-SUB-PBT": 330_000,
			"PL-TAX": -30_000,
			"PL-SUB-PL": 300_000,
		}
		for code, amount in expected.items():
			self.assertEqual(lines[code].amount, amount, code)
		self.assertEqual(result.profit_or_loss, 300_000)
		self.assertEqual(result.ledger_profit_or_loss, 300_000)
		self.assertEqual(result.ledger_difference, 0)
		self._assert_ledger_is_erpnext(result)
		self.assertEqual(result.unmapped, [])
		self.assertEqual(lines["PL-OP-REV"].accounts, [self.sales])
		self.assertTrue(lines["PL-SUB-CONT"].hidden)
		self.assertTrue(lines["PL-DISC"].hidden)
		self.assertFalse(lines["PL-SUB-PBFT"].hidden)

	def test_unmapped_account_is_listed_and_breaks_the_reconciliation(self):
		self._post("2027-02-10", self.sales, -500_000)
		self._post("2027-02-11", self.admin, 200_000)

		result = compute(COMPANY, "2027-02-01", "2027-02-28")
		self.assertEqual(
			result.unmapped,
			[frappe._dict(account=self.admin, reason=NOT_MAPPED, report_line=None, amount=-200_000)],
		)
		self.assertEqual(result.profit_or_loss, 500_000)
		self.assertEqual(result.ledger_profit_or_loss, 300_000)
		self.assertEqual(result.ledger_difference, 200_000)
		self._assert_ledger_is_erpnext(result)

	def test_conditional_mapping_splits_one_account(self):
		self._post("2027-03-10", self.interest_income, -10_000, cost_center=self.ops)
		self._post("2027-03-11", self.interest_income, -5_000, cost_center=self.main)

		lines = self._lines(compute(COMPANY, "2027-03-01", "2027-03-31"))
		self.assertEqual(lines["PL-OP-OTH"].amount, 10_000)
		self.assertEqual(lines["PL-INV-INC"].amount, 5_000)
		# The drill-down to the General Ledger selects each line's cost centers
		self.assertEqual(lines["PL-OP-OTH"].ledger_filters, {"cost_center": [self.ops]})
		self.assertEqual(lines["PL-INV-INC"].ledger_filters, {"cost_center": [self.main]})
		self.assertTrue(lines["PL-OP-OTH"].ledger_exact)
		self.assertTrue(lines["PL-INV-INC"].ledger_exact)
		self.assertEqual(lines["PL-OP-REV"].ledger_filters, {})

	def test_main_business_investing_moves_investment_income_to_operating(self):
		self._set_policy(main_business_investing=1)
		self._post("2027-04-10", self.interest_income, -5_000)

		lines = self._lines(compute(COMPANY, "2027-04-01", "2027-04-30"))
		self.assertEqual(lines["PL-INV-INC"].category, "Operating")
		self.assertEqual(lines["PL-SUB-OP"].amount, 5_000)

	def test_all_financing_in_operating_hides_the_before_financing_subtotal(self):
		self._set_policy(main_business_financing=1, financing_all_operating=1)
		self._post("2027-05-10", self.interest_expense, 8_000)

		lines = self._lines(compute(COMPANY, "2027-05-01", "2027-05-31"))
		self.assertEqual(lines["PL-FIN-INT"].category, "Operating")
		self.assertEqual(lines["PL-SUB-OP"].amount, -8_000)
		self.assertTrue(lines["PL-SUB-PBFT"].hidden)

	def test_cost_center_filter_matches_erpnext(self):
		self._post("2027-06-10", self.sales, -100_000, cost_center=self.main)
		self._post("2027-06-11", self.sales, -40_000, cost_center=self.ops)

		result = compute(COMPANY, "2027-06-01", "2027-06-30", cost_center=self.ops)
		self.assertEqual(self._lines(result)["PL-OP-REV"].amount, 40_000)
		self.assertEqual(result.ledger_difference, 0)
		self._assert_ledger_is_erpnext(result)

	def test_finance_book_filter_matches_erpnext(self):
		book = "_Test PSAK Book"
		if not frappe.db.exists("Finance Book", book):
			frappe.get_doc({"doctype": "Finance Book", "finance_book_name": book}).insert()
		self._post("2027-07-10", self.sales, -100_000)
		self._post("2027-07-11", self.sales, -30_000, finance_book=book)

		without_book = compute(COMPANY, "2027-07-01", "2027-07-31")
		with_book = compute(COMPANY, "2027-07-01", "2027-07-31", finance_book=book)
		self.assertEqual(without_book.profit_or_loss, 100_000)
		self.assertEqual(with_book.profit_or_loss, 130_000)
		self._assert_ledger_is_erpnext(without_book)
		self._assert_ledger_is_erpnext(with_book)

	def test_cancelled_entries_are_ignored(self):
		self._post("2027-08-10", self.sales, -70_000)
		make_journal_entry(COMPANY, "2027-08-11", self.sales, -9_000, self.cash).cancel()

		result = compute(COMPANY, "2027-08-01", "2027-08-31")
		self.assertEqual(result.profit_or_loss, 70_000)
		self._assert_ledger_is_erpnext(result)

	def test_periods_come_from_one_pass_and_add_up_to_the_whole_range(self):
		self._post("2027-09-10", self.sales, -10_000)
		self._post("2027-10-10", self.sales, -20_000)
		self._post("2027-10-20", self.salary, 5_000)

		september, october = compute_periods(
			COMPANY, [("2027-09-01", "2027-09-30"), ("2027-10-01", "2027-10-31")]
		)
		whole = compute(COMPANY, "2027-09-01", "2027-10-31")
		self.assertEqual(september.profit_or_loss, 10_000)
		self.assertEqual(october.profit_or_loss, 15_000)
		self.assertEqual(whole.profit_or_loss, september.profit_or_loss + october.profit_or_loss)
		for result in (september, october):
			self._assert_ledger_is_erpnext(result)

	def test_overlapping_periods_are_refused(self):
		with self.assertRaises(StatementError):
			compute_periods(COMPANY, [("2027-01-01", "2027-01-31"), ("2027-01-31", "2027-02-28")])

	def test_mapping_date_classifies_an_earlier_period_with_later_mappings(self):
		self._post("2027-11-10", self.admin, 4_000)
		reclassified = frappe.get_doc(
			{
				"doctype": "PSAK ID Account Mapping",
				"company": COMPANY,
				"account": self.admin,
				"report_line": "PL-OP-GA",
				"valid_from": "2027-12-01",
				"priority": 10,
				"expense_nature": "Other",
			}
		).insert()
		self.addCleanup(reclassified.delete)

		as_posted = compute(COMPANY, "2027-11-01", "2027-11-30")
		restated = compute(COMPANY, "2027-11-01", "2027-11-30", mapping_date="2027-12-31")
		self.assertEqual(
			as_posted.unmapped,
			[frappe._dict(account=self.admin, reason=NOT_MAPPED, report_line=None, amount=-4_000)],
		)
		self.assertEqual(restated.unmapped, [])
		self.assertEqual(self._lines(restated)["PL-OP-GA"].amount, -4_000)

	def test_company_without_policy_is_refused(self):
		frappe.db.delete("PSAK ID Company Policy", {"company": COMPANY})
		self.addCleanup(
			lambda: frappe.get_doc({"doctype": "PSAK ID Company Policy", "company": COMPANY}).insert()
		)
		with self.assertRaises(StatementError):
			compute(COMPANY, "2027-01-01", "2027-01-31")
