import frappe
from frappe.model.workflow import apply_workflow

from frappe_psak_id.psak_id.doctype.psak_id_financial_statement.psak_id_financial_statement import (
	StatementNotReady,
	period_is_closed,
	reopen_statement,
	set_return_reason,
)
from frappe_psak_id.tests.utils import (
	IntegrationTestCase,
	get_account,
	make_account,
	make_company,
	make_fiscal_year,
	make_journal_entry,
)

TRANSITION_COMPANY = "_Test PSAK Statement Company"
COMPANY = "_Test PSAK Final Company"
STAFF_USER = "psak-statement-staff@example.com"
HEAD_USER = "psak-statement-head@example.com"


def make_policy(company, adoption_date, **values):
	if not frappe.db.exists("PSAK ID Company Policy", company):
		frappe.get_doc({"doctype": "PSAK ID Company Policy", "company": company}).insert()
	frappe.db.set_value("PSAK ID Company Policy", company, {"adoption_date": adoption_date, **values})


def make_mapping(company, account, line, valid_from="2026-01-01", **extra):
	return frappe.get_doc(
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


def make_statement(company, from_date, to_date, periodicity="Monthly", comparative="None", **values):
	return frappe.get_doc(
		{
			"doctype": "PSAK ID Financial Statement",
			"company": company,
			"periodicity": periodicity,
			"from_date": from_date,
			"to_date": to_date,
			"comparative": comparative,
			**values,
		}
	)


def close_period(company, start_date, end_date):
	"""ERPNext only closes past periods, so the workflow tests use a year before the test run."""
	return frappe.get_doc(
		{
			"doctype": "Accounting Period",
			"period_name": f"{company} {start_date}",
			"company": company,
			"start_date": start_date,
			"end_date": end_date,
			# Filled by hand: ERPNext v16 fails to fill its default list (it reads dicts as objects)
			"closed_documents": [{"document_type": "Journal Entry", "closed": 1}],
		}
	).insert()


def amounts(doc, field="amount"):
	return {row.report_line: row.get(field) for row in doc.lines}


class TestStatementLines(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(TRANSITION_COMPANY, "_TPS")
		make_fiscal_year(2026)
		make_fiscal_year(2027)
		make_policy(
			TRANSITION_COMPANY,
			"2027-01-01",
			other_items_threshold_percent=0,
			other_items_threshold_amount=0,
		)
		cash = get_account(TRANSITION_COMPANY, "Cash")
		cls.sales = get_account(TRANSITION_COMPANY, "Sales")
		cls.salary = get_account(TRANSITION_COMPANY, "Salary")
		frappe.db.delete("PSAK ID Account Mapping", {"company": TRANSITION_COMPANY})
		make_mapping(TRANSITION_COMPANY, cls.sales, "PL-OP-REV")
		make_mapping(TRANSITION_COMPANY, cls.salary, "PL-OP-GA", expense_nature="Employee Benefits")
		for posting_date, account, amount in (
			("2026-01-10", cls.sales, -800_000),
			("2027-01-10", cls.sales, -1_000_000),
			("2027-01-11", cls.salary, 300_000),
		):
			make_journal_entry(TRANSITION_COMPANY, posting_date, account, amount, cash)

	def test_lines_and_restated_comparative_of_the_first_year(self):
		with self.assertRaises(frappe.ValidationError):
			make_statement(TRANSITION_COMPANY, "2027-01-01", "2027-01-31", comparative="None").insert()

		doc = make_statement(
			TRANSITION_COMPANY, "2027-01-01", "2027-01-31", comparative="Restated Prior Year"
		).insert()
		self.assertTrue(doc.name.startswith("PSAK-_TPS-2027-01-"))
		self.assertEqual(doc.workflow_state, "Draft")
		self.assertEqual(doc.currency, "IDR")
		current, prior = amounts(doc), amounts(doc, "comparative_amount")
		self.assertEqual((current["PL-OP-REV"], prior["PL-OP-REV"]), (1_000_000, 800_000))
		self.assertEqual((current["PL-OP-GA"], current["PL-SUB-PL"]), (-300_000, 700_000))
		self.assertEqual(prior["PL-SUB-PL"], 800_000)
		self.assertEqual(
			(doc.blocking_issues, doc.erpnext_pl_difference, doc.restatement_difference), (0, 0, 0)
		)
		self.assertEqual(doc.lines[0].report_line, "PL-OP-REV")

		with self.assertRaises(frappe.DuplicateEntryError):
			make_statement(
				TRANSITION_COMPANY, "2027-01-01", "2027-01-31", comparative="Restated Prior Year"
			).insert()

	def test_transition_reconciliation_from_psak201_to_psak118_lines(self):
		cash = get_account(TRANSITION_COMPANY, "Cash")
		legacy = make_account(TRANSITION_COMPANY, "Statement Legacy", "Indirect Expenses")
		for posting_date, account, amount in (
			("2026-02-10", self.sales, -600_000),
			("2026-02-11", self.salary, 100_000),
			("2026-02-12", legacy, 50_000),
		):
			make_journal_entry(TRANSITION_COMPANY, posting_date, account, amount, cash)
		doc = make_statement(
			TRANSITION_COMPANY, "2027-02-01", "2027-02-28", comparative="Restated Prior Year"
		).insert()

		self.assertTrue(doc.is_transition)
		self.assertEqual(
			[(row.psak201_line, row.report_line, row.amount) for row in doc.transition_lines],
			[
				("Pendapatan", "PL-OP-REV", 600_000),
				("Beban umum dan administrasi", "PL-OP-GA", -100_000),
				("Not mapped", None, -50_000),
			],
		)
		self.assertEqual((doc.psak201_profit_or_loss, doc.restated_profit_or_loss), (450_000, 500_000))
		self.assertEqual(doc.restatement_difference, 50_000)
		self.assertEqual(sum(row.amount for row in doc.transition_lines), doc.psak201_profit_or_loss)
		# BR-19: the restated year must equal PSAK 201 before review
		with self.assertRaises(StatementNotReady):
			apply_workflow(doc, "Submit for Review")

	def test_expenses_by_nature_per_function_line(self):
		cash = get_account(TRANSITION_COMPANY, "Cash")
		cogs = get_account(TRANSITION_COMPANY, "Cost of Goods Sold")
		technicians = make_account(TRANSITION_COMPANY, "Statement Technicians", "Indirect Expenses")
		make_mapping(TRANSITION_COMPANY, cogs, "PL-OP-COS", expense_nature="Raw Materials and Goods")
		make_mapping(TRANSITION_COMPANY, technicians, "PL-OP-COS", expense_nature="Employee Benefits")
		for posting_date, account, amount in (
			("2026-04-10", self.salary, 40_000),
			("2027-04-10", cogs, 200_000),
			("2027-04-11", technicians, 70_000),
			("2027-04-12", self.salary, 50_000),
		):
			make_journal_entry(TRANSITION_COMPANY, posting_date, account, amount, cash)

		frappe.db.set_value(
			"PSAK ID Company Policy", TRANSITION_COMPANY, "expense_presentation", "By Function"
		)
		doc = make_statement(
			TRANSITION_COMPANY, "2027-04-01", "2027-04-30", comparative="Restated Prior Year"
		).insert()
		self.assertEqual(
			[
				(row.expense_nature, row.report_line, row.amount, row.comparative_amount)
				for row in doc.nature_lines
			],
			[
				("Raw Materials and Goods", "PL-OP-COS", -200_000, 0),
				("Employee Benefits", "PL-OP-COS", -70_000, 0),
				("Employee Benefits", "PL-OP-GA", -50_000, -40_000),
			],
		)

		frappe.db.set_value("PSAK ID Company Policy", TRANSITION_COMPANY, "expense_presentation", "By Nature")
		self.addCleanup(
			frappe.db.set_value,
			"PSAK ID Company Policy",
			TRANSITION_COMPANY,
			"expense_presentation",
			"By Function",
		)
		doc.compute()
		self.assertEqual(doc.nature_lines, [])

	def test_new_statement_takes_the_unit_of_the_company_policy(self):
		make_policy(TRANSITION_COMPANY, "2027-01-01", default_unit="Thousands")
		self.addCleanup(make_policy, TRANSITION_COMPANY, "2027-01-01", default_unit="Full")
		# A form starts from new_doc, which fills a Select with its first option
		doc = frappe.new_doc("PSAK ID Financial Statement")
		doc.update(
			{
				"company": TRANSITION_COMPANY,
				"periodicity": "Monthly",
				"from_date": "2027-05-01",
				"to_date": "2027-05-31",
				"comparative": "Restated Prior Year",
			}
		)
		doc.insert()
		self.assertEqual(doc.unit, "Thousands")

	def test_period_is_whole_months_of_the_periodicity(self):
		for periodicity, from_date, to_date in (
			("Monthly", "2027-01-01", "2027-02-28"),
			("Quarterly", "2027-01-15", "2027-04-14"),
			("Annual", "2027-01-01", "2027-06-30"),
		):
			with self.assertRaises(frappe.ValidationError, msg=periodicity):
				make_statement(
					TRANSITION_COMPANY, from_date, to_date, periodicity, "Restated Prior Year"
				).insert()

	def test_unmapped_account_blocks_review_and_note_numbers_survive_recompute(self):
		cash = get_account(TRANSITION_COMPANY, "Cash")
		travel = make_account(TRANSITION_COMPANY, "Statement Travel", "Indirect Expenses")
		make_journal_entry(TRANSITION_COMPANY, "2027-03-05", travel, 40_000, cash)
		doc = make_statement(
			TRANSITION_COMPANY, "2027-03-01", "2027-03-31", comparative="Restated Prior Year"
		).insert()
		self.assertEqual((doc.unmapped_count, doc.blocking_issues), (1, 2))
		self.assertEqual(doc.erpnext_pl_difference, 40_000)

		with self.assertRaises(StatementNotReady):
			apply_workflow(doc, "Submit for Review")

		make_mapping(TRANSITION_COMPANY, travel, "PL-OP-GA", "2027-03-01", expense_nature="Other")
		doc.reload()
		doc.lines[0].note_no = "21"
		doc.save()
		doc = apply_workflow(doc, "Submit for Review")
		self.assertEqual((doc.workflow_state, doc.blocking_issues), ("Under Review", 0))
		self.assertEqual(doc.prepared_by, "Administrator")
		self.assertEqual(amounts(doc)["PL-OP-GA"], -40_000)
		self.assertEqual(doc.lines[0].note_no, "21")


class TestStatementWorkflow(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COMPANY, "_TPF")
		make_fiscal_year(2026)
		make_policy(
			COMPANY, "2025-01-01", other_items_threshold_percent=0, other_items_threshold_amount=10_000
		)
		cls.cash = get_account(COMPANY, "Cash")
		cls.sales = get_account(COMPANY, "Sales")
		cls.sundry = make_account(COMPANY, "Statement Sundry", "Indirect Expenses")
		frappe.db.delete("PSAK ID Account Mapping", {"company": COMPANY})
		make_mapping(COMPANY, cls.sales, "PL-OP-REV")
		make_mapping(COMPANY, cls.sundry, "PL-OP-OTH", expense_nature="Other")
		for posting_date, account, amount in (
			("2026-04-10", cls.sales, -500_000),
			("2026-04-11", cls.sundry, 25_000),
			("2026-05-10", cls.sales, -200_000),
		):
			make_journal_entry(COMPANY, posting_date, account, amount, cls.cash)

	def send_to_cfo(self, from_date, to_date, **values):
		doc = make_statement(COMPANY, from_date, to_date, **values).insert()
		doc = apply_workflow(doc, "Submit for Review")
		return apply_workflow(doc, "Send to CFO")

	def test_review_approval_final_and_reopen(self):
		doc = make_statement(COMPANY, "2026-04-01", "2026-04-30").insert()
		self.assertFalse(doc.is_transition)
		self.assertEqual(doc.transition_lines, [])
		self.assertIn("PL-OP-OTH", doc.other_items_warnings)
		with self.assertRaises(StatementNotReady):
			apply_workflow(doc, "Submit for Review")
		doc.reload()
		doc.other_items_note = "<p>Bank charges and stamp duty.</p>"
		doc.save()
		doc = apply_workflow(doc, "Submit for Review")

		with self.assertRaises(frappe.MandatoryError):
			apply_workflow(doc, "Return to Draft")
		set_return_reason(doc.name, "Add the note number of revenue.")
		doc = apply_workflow(doc, "Return to Draft")
		self.assertEqual(doc.workflow_state, "Draft")
		doc = apply_workflow(doc, "Submit for Review")
		self.assertIsNone(doc.return_reason)
		doc = apply_workflow(doc, "Send to CFO")
		self.assertEqual(doc.reviewed_by, "Administrator")

		# BR-13: the period must be closed in ERPNext first
		with self.assertRaises(frappe.ValidationError):
			apply_workflow(doc, "Approve")
		close_period(COMPANY, "2026-04-01", "2026-04-30")
		doc = apply_workflow(doc, "Approve")
		self.assertEqual((doc.docstatus, doc.workflow_state), (1, "Final"))
		self.assertEqual(doc.approved_by, "Administrator")
		self.assertTrue(doc.approved_on)
		self.assertEqual(amounts(doc)["PL-SUB-PL"], 475_000)

		# BR-09: mappings in force in a final period stay as they are
		with self.assertRaises(frappe.ValidationError):
			make_mapping(COMPANY, self.sundry, "PL-OP-GA", "2026-04-01", expense_nature="Other")
		mapping = frappe.get_doc("PSAK ID Account Mapping", {"account": self.sales})
		mapping.report_line = "PL-OP-OTH"
		with self.assertRaises(frappe.ValidationError):
			mapping.save()
		mapping.reload()
		with self.assertRaises(frappe.ValidationError):
			mapping.delete()
		mapping.notes = "Checked by the auditor."
		mapping.save()
		make_mapping(COMPANY, self.sundry, "PL-OP-GA", "2026-05-01", expense_nature="Other").delete()

		# BR-08: no direct cancel; reopening keeps the final version and creates a new one
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()
		with self.assertRaises(frappe.MandatoryError):
			reopen_statement(doc.name, " ")
		amended = frappe.get_doc(
			"PSAK ID Financial Statement", reopen_statement(doc.name, "Audit adjustment")
		)
		doc.reload()
		self.assertEqual((doc.docstatus, doc.workflow_state), (2, "Cancelled"))
		self.assertEqual((amended.docstatus, amended.workflow_state), (0, "Reopened"))
		self.assertEqual((amended.amended_from, amended.reopen_reason), (doc.name, "Audit adjustment"))
		self.assertEqual(amended.reopened_by, "Administrator")
		self.assertIsNone(amended.approved_by)
		self.assertEqual(amended.other_items_note, doc.other_items_note)
		# With no final statement left, the period's mappings can change again
		make_mapping(COMPANY, self.sundry, "PL-OP-GA", "2026-04-01", expense_nature="Other").delete()

	def test_approval_refused_when_the_ledger_changed_after_review(self):
		doc = self.send_to_cfo("2026-05-01", "2026-05-31")
		make_journal_entry(COMPANY, "2026-05-20", self.sales, -1_000, self.cash)
		close_period(COMPANY, "2026-05-01", "2026-05-31")
		with self.assertRaises(frappe.ValidationError) as error:
			apply_workflow(doc, "Approve")
		self.assertIn("PL-OP-REV", str(error.exception))

	def test_closed_accounting_periods_may_cover_the_period_together(self):
		self.assertFalse(period_is_closed(COMPANY, "2026-07-01", "2026-09-30", annual=False))
		close_period(COMPANY, "2026-07-01", "2026-07-31")
		close_period(COMPANY, "2026-08-01", "2026-09-30")
		self.assertTrue(period_is_closed(COMPANY, "2026-07-01", "2026-09-30", annual=False))
		self.assertFalse(period_is_closed(COMPANY, "2026-07-01", "2026-10-31", annual=False))

	def test_staff_may_prepare_but_not_approve_or_reopen(self):
		if not frappe.db.exists("User", STAFF_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": STAFF_USER,
					"first_name": "PSAK Statement Staff",
					"send_welcome_email": 0,
				}
			).insert().add_roles("PSAK ID - Accounting - Staff")
		doc = self.send_to_cfo("2026-06-01", "2026-06-30")
		frappe.set_user(STAFF_USER)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.ValidationError):
			apply_workflow(doc, "Approve")
		with self.assertRaises(frappe.PermissionError):
			reopen_statement(doc.name, "No reason")

	def test_head_reviews_but_does_not_prepare(self):
		if not frappe.db.exists("User", HEAD_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": HEAD_USER,
					"first_name": "PSAK Statement Head",
					"send_welcome_email": 0,
				}
			).insert().add_roles("PSAK ID - Accounting - Head")
		frappe.set_user(HEAD_USER)
		self.addCleanup(frappe.set_user, "Administrator")
		# The reviewer does not prepare what they review; a small company gives one person both roles
		self.assertFalse(frappe.has_permission("PSAK ID Financial Statement", "create"))
		self.assertTrue(frappe.has_permission("PSAK ID Financial Statement", "read"))
