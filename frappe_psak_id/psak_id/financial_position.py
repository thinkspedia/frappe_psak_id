"""Balance sheet accounts of the PSAK 118 statement of financial position, read from ERPNext's
General Ledger.

The ledger is only read: GL Entries are summed per account up to the reporting date in SQL, with
the same finance book choice as the statement of profit or loss.
"""

import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate

from frappe_psak_id.psak_id.statement import include_default_book

BALANCE_SHEET_ROOT_TYPES = ("Asset", "Liability", "Equity")


def get_account_balances(company: str, to_date, finance_book: str | None = None) -> list:
	"""Debit minus credit of every balance sheet account with a balance on ``to_date``.

	Period Closing Vouchers are included: they move the year's profit or loss into an equity
	account, which is part of that account's balance.
	"""
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	books = [finance_book or ""]
	if include_default_book(company, finance_book):
		books.append(frappe.get_cached_value("Company", company, "default_finance_book") or "")

	rows = (
		frappe.qb.from_(gle)
		.join(account)
		.on(account.name == gle.account)
		.select(gle.account, account.root_type, (Sum(gle.debit) - Sum(gle.credit)).as_("balance"))
		.where(gle.company == company)
		.where(account.root_type.isin(BALANCE_SHEET_ROOT_TYPES))
		.where(gle.posting_date <= getdate(to_date))
		.where(gle.is_cancelled == 0)
		.where(gle.finance_book.isin(books) | gle.finance_book.isnull())
		.groupby(gle.account, account.root_type)
		.run(as_dict=True)
	)
	return [row for row in rows if flt(row.balance, 2)]


def mapped_accounts(company: str, to_date) -> set:
	"""Balance sheet accounts with a mapping in force on ``to_date``."""
	return set(
		frappe.get_all(
			"PSAK ID Account Mapping",
			filters={
				"company": company,
				"valid_from": ("<=", getdate(to_date)),
				"root_type": ("in", BALANCE_SHEET_ROOT_TYPES),
			},
			pluck="account",
			distinct=True,
		)
	)
