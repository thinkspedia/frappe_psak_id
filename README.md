<div align="center">

<img src="frappe_psak_id/public/images/psak-id-logo.svg" alt="PSAK ID logo" width="96">

# PSAK ID

**Indonesian financial statement presentation (PSAK 118) for ERPNext.**

Present ERPNext's ledger in the PSAK 118 format, without changing ERPNext's core or its standard reports.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
![Frappe](https://img.shields.io/badge/Frappe-v15%20%7C%20v16-0089FF)
![ERPNext](https://img.shields.io/badge/ERPNext-v15%20%7C%20v16-0089FF)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Status](https://img.shields.io/badge/release-1-green)

</div>

---

## Why PSAK ID?

PSAK 118 *Penyajian dan Pengungkapan dalam Laporan Keuangan* (the Indonesian adoption of IFRS 18) replaces PSAK 201 and takes effect on 1 January 2027, with 2026 comparatives restated. ERPNext's standard Profit and Loss, Balance Sheet and Cash Flow reports do not present those categories and subtotals.

PSAK ID adds the PSAK 118 presentation on top of ERPNext's General Ledger. It only reads the ledger: posting, closing and ERPNext's own reports stay exactly as they are.

## Scope

> Release 1 is out as version 1.0.0. Release 2 is in progress: the statement of financial position and other comprehensive income are in; the statement of cash flows, the statement of changes in equity and MPM follow. Release 3 is planned.

| Release | Scope |
|---|---|
| **1** | Per-company PSAK 118 policy, mapping of the Chart of Accounts to the PSAK 118 categories (with industry templates), a mapping check, the PSAK 118 statement of profit or loss with its three required subtotals and restated comparatives, a review and approval flow, and PDF / Excel export |
| **2** | Statement of financial position, statement of cash flows, statement of changes in equity, management-defined performance measures (MPM) |
| **3** | Compliance calendar and regulatory exports |

## Features

- **Company Policy**: one per company. It holds the PSAK 118 adoption date, the main business activities (which move investing or financing lines into Operating), expense presentation (by function, by nature or mixed), the Other Items threshold, the default unit and the letter head.
- **Report Lines**: the standard PSAK 118 statement of profit or loss, other comprehensive income, statement of financial position and statement of cash flows.
  - Lines carry Indonesian and English labels. Profit or loss lines fall into the categories Operating, Investing, Financing, Income Tax and Discontinued Operations; financial position lines are assets, liabilities (current or non-current) or equity; other comprehensive income lines will not or may be reclassified to profit or loss.
  - The three required subtotals are operating profit or loss, profit or loss before financing and income taxes, and profit or loss. Total assets, total equity, total liabilities and equity and total comprehensive income are required too.
  - Subtotals are formulas, which can add the current or non-current lines of a category or the subtotal of another statement. You can add lines; the required subtotals are protected.
- **Account Mapping**: maps each account to a line from a start date. A mapping can be limited to a cost center, project, party or accounting dimension value, with a priority and an unconditional fallback.
  - Each operating expense also records its nature for the by-nature note.
  - Asset, liability and equity accounts go to a financial position line of their own category. Equity accounts name their equity component and, for reserves of other comprehensive income, the line their movements are presented in.
  - Each balance sheet account names the cash flow line of its movements, and optionally another line for decreases. Income and expense accounts name one only for a non-cash item or one presented outside operating activities, such as depreciation.
- **Mapping Templates**: five standard templates (services, trading, manufacturing, property, investment holding) map a company's accounts in one step by name, number or account type pattern, and you can add your own. Version 1.1 of the standard templates (`<Industry> (Standard 1.1)`) also maps the balance sheet of ERPNext's standard chart. Version 1.2 (`<Industry> (Standard 1.2)`) adds the cash flow lines, and **Complete Cash Flow Lines** fills them into the mappings already in force.
- **Mapping Control**: a report of what blocks a statement:
  - unmapped accounts, including balance sheet accounts with a balance;
  - entries that match no condition;
  - a difference to ERPNext's Profit and Loss;
  - in the first PSAK 118 year, the restated prior year;
  - conditional mappings of the same priority that put an account's balance on different lines;
  - warnings for Other Items above the threshold, and for such conflicting conditions when the account's entries net to nothing.
- **PSAK 118 Profit or Loss**: a report with monthly, quarterly or yearly columns.
  - Comparatives can be the same period last year or the prior year restated with this year's mappings.
  - Filters cover cost center and finance book, with amounts in full, thousands or millions and Indonesian, English or both labels.
  - Clicking an amount opens the General Ledger behind it.
  - Once equity accounts are mapped to other comprehensive income, the statement continues with other comprehensive income and total comprehensive income.
- **PSAK 118 Financial Position**: the statement of financial position on a date, with the prior fiscal year end as comparative.
  - Retained earnings include the profit or loss of the fiscal year so far, before or after a Period Closing Voucher.
  - The report checks that the statement balances and agrees with ERPNext's Balance Sheet, lists unmapped accounts and opens the General Ledger behind an amount.
- **PSAK 118 Cash Flows**: the statement of cash flows by the indirect method for a period, with the same period of the prior year as comparative.
  - Operating cash flows start from operating profit or loss. Balance sheet accounts present their movements on their cash flow line, gross when the mapping names a line for decreases.
  - Non-cash transactions, such as a lease, are left out and listed; the revaluation of cash is the effect of exchange rates.
  - The report checks closing cash against the ledger's cash and cash equivalents, lists accounts without a cash flow line and opens the General Ledger behind an amount.
- **Financial Statement**: a submittable package of PSAK 118 financial statements for one company and period: the statement of financial position, the statement of profit or loss and other comprehensive income, the statement of cash flows (quarterly and annual packages) and the notes.
  - It holds the notes column, the expenses by nature (when presenting by function), the transition reconciliation from PSAK 201 in the first year and the Other Items breakdown.
  - A workflow takes it from Draft to Under Review, Approval CFO and Final.
  - Approval needs the period closed in ERPNext and an unchanged ledger.
  - A Final statement is frozen and locks the mappings it used. Reopen keeps it as a cancelled version and creates an amendment.
- **Export**: a bilingual A4 PDF of the package (each statement on its own pages, letter head, running header, page numbers, DRAFT or CANCELLED watermark, approval sheet), an Excel workbook with a sheet per statement whose subtotals are formulas, and structured data in Excel or CSV.
- **Workspace** "PSAK 118" with number cards and shortcuts, opened from the PSAK ID tile on the apps screen.

Every statement total reconciles with ERPNext's Profit and Loss and Balance Sheet for the same company, period and filters, and the statement shows the differences, which must be zero. PSAK ID never writes to the General Ledger, journal entries or ERPNext's own reports.

## Roles

| Role | Can |
|---|---|
| PSAK ID - Accounting - Staff | Read the policy and mappings, prepare statements and submit them for review |
| PSAK ID - Accounting - Head | Maintain the company policy, report lines, mappings and templates, apply templates, review statements, send them to the CFO or back to draft, reopen a final statement |
| PSAK ID - CFO | Approve statements (Final) or return them to review, reopen a final statement |
| PSAK ID - Auditor | Read everything, including the change history of PSAK ID documents, and print or export |

The Accounting Head reviews what staff prepare, so the role does not create or edit draft statements. In a small company, give one person both the Staff and the Head roles.

The PSAK ID roles grant access to PSAK ID documents only. The statements and reports also read ERPNext's Company, accounts and ledger, so give each user an ERPNext role as well:

- give staff, heads and CFOs **Accounts User** or **Accounts Manager**;
- give auditors **Auditor**.

Limit a user to their companies with a User Permission on Company.

## Getting started

1. As the Accounting Head, create a **PSAK ID Company Policy** for the company: adoption date, main business activities, expense presentation, Other Items threshold, default unit and letter head.
2. Open a **PSAK ID Mapping Template** close to the company's business and choose **Apply to Company**. Pick a version 1.2 template to map the balance sheet and the cash flow lines too. Then map the remaining accounts in **PSAK ID Account Mapping**.
3. Run **PSAK ID Mapping Control** for the period and fix every blocking row.
4. Check the figures in **PSAK 118 Profit or Loss**, **PSAK 118 Financial Position** and **PSAK 118 Cash Flows**.
5. As staff or head, create a **PSAK ID Financial Statement** for the period, add note numbers and explain Other Items above the threshold. Then **Submit for Review**.
6. Close the period in ERPNext (Accounting Period, or a Period Closing Voucher for an annual statement). Then the head sends the statement to the CFO, who approves it.

### Good to know

- **Adjust the ledger, not the statement.** Corrections, including audit adjustments to the prior year, are journal entries in ERPNext. Post the prior year's audit adjustments before preparing the next year's statements, so that the restated comparatives include them.
- **Mappings are dated.** To reclassify an account, add a mapping with a later start date. A mapping used by a final statement cannot be changed. Restated comparatives use the mappings of the reporting period.
- **One statement per company, period and finance book.** To correct a Final statement, use **Reopen**: the final version is kept as cancelled and prints with a CANCELLED watermark.

## Compatibility

| Frappe / ERPNext | Branch | Python |
|---|---|---|
| v16 | `version-16` | 3.14 |
| v15 | `version-15` | 3.11+ |

ERPNext is required.

## Languages

English (source), Indonesian (`id`), Simplified Chinese (`zh`), Japanese (`ja`) and Arabic (`ar`, right-to-left). PSAK ID follows each user's language in Desk. A language must be enabled in **Language** on your site before users can pick it.

## Installation

```bash
# Pick the branch that matches your Frappe version: version-16 or version-15
bench get-app https://github.com/thinkspedia/frappe_psak_id --branch version-16
bench --site your-site.com install-app frappe_psak_id
```

### Uninstalling

```bash
bench --site your-site.com uninstall-app frappe_psak_id
bench remove-app frappe_psak_id
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security problems: see [SECURITY.md](SECURITY.md).

## License

[GNU Affero General Public License v3.0](LICENSE). © Thinkspedia.
