# Copyright (c) 2026, Thinkspedia and contributors
# For license information, please see license.txt

"""A PSAK 118 statement of profit or loss for one company and period, reviewed and made final.

Recompute fills the lines from the statement engine and records the checks of the Mapping
Control. The workflow (fixture ``PSAK ID Financial Statement``) moves it from Draft through
Under Review and Approval CFO to Final; this controller enforces what each step needs: the
checks pass before review (BR-02, BR-06, BR-07, BR-19), the period is closed in ERPNext before
the CFO approves (BR-13), and the approved values still match the ledger. A final statement keeps
its values (BR-14) and is only reopened with a reason, which cancels it and creates an amendment
(BR-08).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import (
	add_days,
	add_months,
	add_years,
	flt,
	fmt_money,
	formatdate,
	get_last_day,
	getdate,
	now,
)

from frappe_psak_id.compat import accounting_period_filters
from frappe_psak_id.psak_id.checks import BLOCKING, OTHER_ITEMS, is_transition_period, run_checks
from frappe_psak_id.psak_id.statement import (
	DISABLED_LINE,
	NO_MATCHING_CONDITION,
	NOT_MAPPED,
	check_read_access,
	compute,
)

DRAFT = "Draft"
UNDER_REVIEW = "Under Review"
APPROVAL_CFO = "Approval CFO"
FINAL = "Final"
REOPENED = "Reopened"
CANCELLED = "Cancelled"
EDITABLE_STATES = (DRAFT, REOPENED)

NO_COMPARATIVE = "None"
SAME_PERIOD_LAST_YEAR = "Same Period Last Year"
RESTATED_PRIOR_YEAR = "Restated Prior Year"

PERIOD_MONTHS = {"Monthly": 1, "Quarterly": 3, "Annual": 12}
REOPEN_ROLES = ("PSAK ID - Accounting - Head", "PSAK ID - CFO")
UNMAPPED_CHECKS = (NOT_MAPPED, NO_MATCHING_CONDITION, DISABLED_LINE)


class PSAKIDFinancialStatement(Document):
	def autoname(self):
		abbr = frappe.get_cached_value("Company", self.company, "abbr")
		self.name = make_autoname(f"PSAK-{abbr}-{getdate(self.to_date).strftime('%Y-%m')}-.##", doc=self)

	def validate(self):
		check_read_access(self.company)
		self._validate_period()
		self._set_defaults()
		self._validate_comparative()
		self._validate_unique()
		if self.is_new():
			self.compute()
		self._on_state_change()

	def before_submit(self):
		previous = self.get_doc_before_save()
		if not previous or previous.workflow_state != APPROVAL_CFO:
			frappe.throw(_("A statement becomes final only when the CFO approves it."))
		self._validate_period_closed()
		self._validate_unchanged_ledger()
		self.approved_by = frappe.session.user
		self.approved_on = now()

	def before_cancel(self):
		# Only reopen_statement cancels, so a final statement is never undone without a reason and
		# a new version
		if not self.flags.reopen_reason:
			frappe.throw(
				_(
					"A final statement is not cancelled. Use Reopen: it keeps this version and creates a new "
					"one to correct."
				)
			)
		# Frappe sets the workflow state on cancel only through a workflow action, and Reopen is not one
		self.workflow_state = CANCELLED

	def compute(self):
		"""Fill the lines and the check results from the General Ledger."""
		result = run_checks(self.company, self.from_date, self.to_date, self.finance_book)
		current, comparative = result.current, self._comparative_statement(result)

		notes = {row.report_line: row.note_no for row in self.lines if row.note_no}
		prior_lines = {line.line_code: line for line in comparative.lines} if comparative else {}
		self.set("lines", [])
		for line in current.lines:
			prior = prior_lines.get(line.line_code)
			if line.hidden and (not prior or prior.hidden):
				continue
			self.append(
				"lines",
				{
					"report_line": line.line_code,
					"label_id": line.label_id,
					"label_en": line.label_en,
					"category": line.category,
					"line_type": line.line_type,
					"is_other_items": line.is_other_items,
					"note_no": notes.get(line.line_code),
					"amount": line.amount,
					"comparative_amount": prior.amount if prior else 0,
				},
			)

		self._set_transition_lines(result.restated)

		issues = result.issues
		self.unmapped_count = len({issue.account for issue in issues if issue.check in UNMAPPED_CHECKS})
		self.erpnext_pl_difference = current.ledger_difference
		self.restatement_difference = result.restated.ledger_difference if result.restated else 0
		self.blocking_issues = len([issue for issue in issues if issue.severity == BLOCKING])
		self.other_items_warnings = "\n".join(
			_("{0}: {1} is above the threshold of {2}.").format(
				issue.report_line, self._money(abs(issue.amount)), self._money(issue.threshold)
			)
			for issue in issues
			if issue.check == OTHER_ITEMS
		)
		self.check_messages = "\n".join(self._blocking_messages())
		self.computed_on = now()

	def _set_transition_lines(self, restated):
		"""The prior year reconciled from PSAK 201 lines to PSAK 118 lines (BR-11).

		PSAK 201 amounts are ERPNext's Profit and Loss per account; each account's PSAK 201 line is
		the PSAK 201 line of the PSAK 118 line it is mapped to, so one PSAK 201 line may split over
		several PSAK 118 lines. Accounts without a mapping stay in their own row, and the two totals
		differ by exactly that row (BR-19).
		"""
		self.set("transition_lines", [])
		self.is_transition = bool(restated)
		if not restated:
			self.psak201_profit_or_loss = self.restated_profit_or_loss = 0
			return
		self.psak201_profit_or_loss = restated.ledger_profit_or_loss
		self.restated_profit_or_loss = restated.profit_or_loss

		psak201_lines = dict(
			frappe.get_all(
				"PSAK ID Report Line",
				filters={"statement": "Profit or Loss"},
				fields=["name", "psak201_line"],
				as_list=True,
			)
		)
		groups = {}
		for line in restated.lines:
			if line.line_type == "Line" and flt(line.amount, 2):
				psak201_line = psak201_lines.get(line.line_code) or _("No PSAK 201 line")
				groups.setdefault(psak201_line, []).append(
					{
						"psak201_line": psak201_line,
						"report_line": line.line_code,
						"label_id": line.label_id,
						"label_en": line.label_en,
						"category": line.category,
						"amount": line.amount,
					}
				)
		if flt(restated.ledger_difference, 2):
			groups.setdefault(_("Not mapped"), []).append(
				{"psak201_line": _("Not mapped"), "amount": -restated.ledger_difference}
			)
		# Rows of one PSAK 201 line together, in the order its first PSAK 118 line is presented
		for rows in groups.values():
			for row in rows:
				self.append("transition_lines", row)

	def _comparative_statement(self, result):
		if self.comparative == NO_COMPARATIVE:
			return None
		if self.comparative == RESTATED_PRIOR_YEAR and result.restated:
			return result.restated
		# Restated: the prior year classified with this period's mappings (BR-11)
		mapping_date = self.to_date if self.comparative == RESTATED_PRIOR_YEAR else None
		return compute(
			self.company,
			add_years(self.from_date, -1),
			add_years(self.to_date, -1),
			finance_book=self.finance_book,
			mapping_date=mapping_date,
		)

	def _blocking_messages(self) -> list[str]:
		"""What stops the statement from being sent for review, in plain words (FR-12)."""
		messages = []
		if self.unmapped_count:
			messages.append(
				_("{0} accounts with a balance have no PSAK 118 line. Map them in Mapping Control.").format(
					self.unmapped_count
				)
			)
		if flt(self.erpnext_pl_difference):
			messages.append(
				_(
					"The profit or loss differs from ERPNext's Profit and Loss by {0}. Open Mapping Control to "
					"find the accounts."
				).format(self._money(self.erpnext_pl_difference))
			)
		if flt(self.restatement_difference):
			messages.append(
				_(
					"The restated prior year differs from its PSAK 201 profit or loss by {0}. Map the prior "
					"year's accounts in Mapping Control."
				).format(self._money(self.restatement_difference))
			)
		return messages

	def _money(self, amount) -> str:
		return fmt_money(flt(amount), currency=self.currency)

	def _validate_period(self):
		months = PERIOD_MONTHS[self.periodicity]
		from_date, to_date = getdate(self.from_date), getdate(self.to_date)
		expected_end = getdate(get_last_day(add_months(from_date, months - 1)))
		if from_date.day != 1 or to_date != expected_end:
			frappe.throw(
				_(
					"A {0} statement covers {1} whole months: from the first day of a month to the last day "
					"of its last month. Starting {2}, it ends {3}."
				).format(_(self.periodicity).lower(), months, formatdate(from_date), formatdate(expected_end))
			)

	def _set_defaults(self):
		policy = frappe.db.get_value(
			"PSAK ID Company Policy", self.company, ["default_unit", "currency"], as_dict=True
		)
		if not self.unit:
			self.unit = (policy and policy.default_unit) or "Full"
		self.currency = (policy and policy.currency) or frappe.get_cached_value(
			"Company", self.company, "default_currency"
		)
		start, end = getdate(self.from_date), getdate(self.to_date)
		period = formatdate(start, "MMM yyyy")
		if (start.year, start.month) != (end.year, end.month):
			period = f"{period} \u2013 {formatdate(end, 'MMM yyyy')}"
		self.title = f"{self.company} {period}"

	def _validate_comparative(self):
		if self.comparative != RESTATED_PRIOR_YEAR and is_transition_period(
			self.company, self.from_date, self.to_date
		):
			adoption_date = frappe.db.get_value("PSAK ID Company Policy", self.company, "adoption_date")
			frappe.throw(
				_(
					"{0} applies PSAK 118 from {1}. In that first year the comparative is the prior year "
					"restated with this year's mappings: choose Restated Prior Year."
				).format(self.company, formatdate(adoption_date))
			)

	def _validate_unique(self):
		duplicate = frappe.db.exists(
			self.doctype,
			{
				"name": ("!=", self.name),
				"company": self.company,
				"from_date": self.from_date,
				"to_date": self.to_date,
				"finance_book": self.finance_book or ("is", "not set"),
				"docstatus": ("<", 2),
			},
		)
		if duplicate:
			frappe.throw(
				_("{0} already covers this company, period and finance book. Open that statement.").format(
					duplicate
				),
				frappe.DuplicateEntryError,
			)

	def _on_state_change(self):
		previous = self.get_doc_before_save()
		old_state = previous.workflow_state if previous else None
		if not old_state or old_state == self.workflow_state:
			return
		if self.workflow_state == UNDER_REVIEW and old_state in EDITABLE_STATES:
			# Review always starts from the ledger as it is now, never from values computed earlier
			self.compute()
			self._validate_ready_for_review()
			self.prepared_by = frappe.session.user
			self.return_reason = None
		elif self.workflow_state == APPROVAL_CFO:
			self.reviewed_by = frappe.session.user
			self.return_reason = None
		elif (old_state, self.workflow_state) in ((UNDER_REVIEW, DRAFT), (APPROVAL_CFO, UNDER_REVIEW)):
			if not (self.return_reason or "").strip():
				frappe.throw(_("Give the reason for sending the statement back."), frappe.MandatoryError)
			self.add_comment(
				"Comment", _("Sent back to {0}: {1}").format(_(self.workflow_state), self.return_reason)
			)

	def _validate_ready_for_review(self):
		messages = self._blocking_messages()
		if self.other_items_warnings and not strip_text(self.other_items_note):
			messages.append(
				_(
					"Other Items lines are above the company threshold. Explain what they consist of in Other "
					"Items Breakdown."
				)
			)
		if messages:
			frappe.throw(
				"<br>".join(messages), title=_("The statement is not ready for review"), exc=StatementNotReady
			)

	def _validate_period_closed(self):
		if not period_is_closed(self.company, self.from_date, self.to_date, self.periodicity == "Annual"):
			frappe.throw(
				_(
					"Close {0} to {1} in ERPNext before approving: a closed Accounting Period covering it, or "
					"a Period Closing Voucher for an annual statement. Then no entry can change the approved "
					"amounts."
				).format(formatdate(self.from_date), formatdate(self.to_date)),
				title=_("The period is not closed"),
			)

	def _validate_unchanged_ledger(self):
		stored = {(row.report_line, flt(row.amount, 2), flt(row.comparative_amount, 2)) for row in self.lines}
		fresh = frappe.get_doc(self.as_dict())
		fresh.compute()
		changed = sorted(
			row.report_line
			for row in fresh.lines
			if (row.report_line, flt(row.amount, 2), flt(row.comparative_amount, 2)) not in stored
		)
		if changed or len(fresh.lines) != len(self.lines) or fresh.blocking_issues:
			frappe.throw(
				_(
					"The ledger changed after the statement was reviewed ({0}). Send it back to Draft, where "
					"it is recomputed on the next review."
				).format(", ".join(changed) or _("check results")),
				title=_("The amounts no longer match the ledger"),
			)


class StatementNotReady(frappe.ValidationError):
	pass


def strip_text(html) -> str:
	return frappe.utils.strip_html(html or "").strip()


def period_is_closed(company: str, from_date, to_date, annual: bool) -> bool:
	"""Whether ERPNext no longer accepts entries in the period (BR-13).

	Closed Accounting Periods may cover it together, e.g. three closed months for a quarter; an
	annual statement may instead rely on a submitted Period Closing Voucher for the year.
	"""
	from_date, to_date = getdate(from_date), getdate(to_date)
	if annual and frappe.db.exists(
		"Period Closing Voucher",
		{
			"company": company,
			"docstatus": 1,
			"period_start_date": ("<=", from_date),
			"period_end_date": (">=", to_date),
		},
	):
		return True

	periods = frappe.get_all(
		"Accounting Period",
		filters={
			"company": company,
			"start_date": ("<=", to_date),
			"end_date": (">=", from_date),
			**accounting_period_filters(),
		},
		fields=["name", "start_date", "end_date"],
		order_by="start_date",
	)
	closed = set(
		frappe.get_all(
			"Closed Document",
			filters={
				"parenttype": "Accounting Period",
				"parent": ("in", [period.name for period in periods] or [""]),
				"closed": 1,
			},
			pluck="parent",
		)
	)
	covered_until = getdate(add_days(from_date, -1))
	for period in periods:
		if period.name not in closed:
			continue
		if getdate(period.start_date) > getdate(add_days(covered_until, 1)):
			break
		covered_until = max(covered_until, getdate(period.end_date))
	return covered_until >= to_date


@frappe.whitelist()
def refresh_statement(name: str) -> None:
	"""Recompute a Draft or Reopened statement from the General Ledger (FR-07)."""
	doc = frappe.get_doc("PSAK ID Financial Statement", name)
	doc.check_permission("write")
	if doc.docstatus != 0 or doc.workflow_state not in EDITABLE_STATES:
		frappe.throw(
			_("Only Draft or Reopened statements are recomputed. Send this one back to Draft first.")
		)
	doc.compute()
	doc.save()


@frappe.whitelist()
def set_return_reason(name: str, reason: str) -> None:
	"""Record why a statement is sent back, just before the workflow action that sends it back."""
	doc = frappe.get_doc("PSAK ID Financial Statement", name)
	doc.check_permission("write")
	if doc.workflow_state not in (UNDER_REVIEW, APPROVAL_CFO):
		frappe.throw(_("Only a statement under review or awaiting approval is sent back."))
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for sending the statement back."), frappe.MandatoryError)
	doc.db_set("return_reason", reason)


@frappe.whitelist()
def reopen_statement(name: str, reason: str) -> str:
	"""Cancel a final statement and return the amendment created to correct it (FR-09, BR-08)."""
	doc = frappe.get_doc("PSAK ID Financial Statement", name)
	doc.check_permission("read")
	if not set(REOPEN_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Only an Accounting Head or the CFO can reopen a final statement."), frappe.PermissionError
		)
	if doc.docstatus != 1:
		frappe.throw(_("Only a final statement can be reopened."))
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for reopening the statement."), frappe.MandatoryError)

	# The roles were checked above; ignore_permissions because Cancel is otherwise granted to no one,
	# which keeps the standard Cancel button off final statements
	doc.flags.reopen_reason = reason
	doc.flags.ignore_permissions = True
	doc.cancel()
	doc.add_comment("Comment", _("Reopened: {0}").format(reason))

	amendment = frappe.copy_doc(doc, ignore_no_copy=False)
	amendment.update(
		{
			"docstatus": 0,
			"amended_from": doc.name,
			"reopen_reason": reason,
			"reopened_by": frappe.session.user,
			"reopened_on": now(),
		}
	)
	amendment.flags.ignore_permissions = True
	amendment.insert()
	# Frappe's workflow starts every new document in its first state; Reopened tells reviewers this
	# version replaces a final one
	amendment.db_set("workflow_state", REOPENED)
	return amendment.name
