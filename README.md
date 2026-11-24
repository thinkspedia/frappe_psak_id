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

> Release 1 is out as version 1.0.0. Releases 2 and 3 are planned.

| Release | Scope |
|---|---|
| **1** | Per-company PSAK 118 policy, mapping of the Chart of Accounts to the PSAK 118 categories (with industry templates), a mapping check, the PSAK 118 statement of profit or loss with its three required subtotals and restated comparatives, a review and approval flow, and PDF / Excel export |
| **2** | Statement of financial position, statement of cash flows, statement of changes in equity, management-defined performance measures (MPM) |
| **3** | Compliance calendar and regulatory exports |

## Features (release 1)

- **Company Policy**: one per company. It holds the PSAK 118 adoption date, the main business activities (which move investing or financing lines into Operating), expense presentation (by function, by nature or mixed), the Other Items threshold, the default unit and the letter head.
- **Report Lines**: the standard PSAK 118 statement of profit or loss.
  - Lines carry Indonesian and English labels and fall into the categories Operating, Investing, Financing, Income Tax and Discontinued Operations.
  - The three required subtotals are operating profit or loss, profit or loss before financing and income taxes, and profit or loss.
  - Subtotals are formulas. You can add lines; the required subtotals are protected.
- **Account Mapping**: maps each income and expense account to a line from a start date. A mapping can be limited to a cost center, project, party or accounting dimension value, with a priority and an unconditional fallback. Each operating expense also records its nature for the by-nature note.
- **Mapping Templates**: five standard templates (services, trading, manufacturing, property, investment holding) map a company's accounts in one step by name or number pattern, and you can add your own.
- **Mapping Control**: a report of what blocks a statement:
  - unmapped accounts;
  - entries that match no condition;
  - a difference to ERPNext's Profit and Loss;
  - in the first PSAK 118 year, the restated prior year;
  - warnings for Other Items above the threshold and conflicting conditions.
- **PSAK 118 Profit or Loss**: a report with monthly, quarterly or yearly columns.
  - Comparatives can be the same period last year or the prior year restated with this year's mappings.
  - Filters cover cost center and finance book, with amounts in full, thousands or millions and Indonesian, English or both labels.
  - Clicking an amount opens the General Ledger behind it.
- **Financial Statement**: a submittable PSAK 118 statement of profit or loss for one company and period.
  - It holds the notes column, the expenses by nature (when presenting by function), the transition reconciliation from PSAK 201 in the first year and the Other Items breakdown.
  - A workflow takes it from Draft to Under Review, Approval CFO and Final.
  - Approval needs the period closed in ERPNext and an unchanged ledger.
  - A Final statement is frozen and locks the mappings it used. Reopen keeps it as a cancelled version and creates an amendment.
- **Export**: a bilingual A4 PDF (letter head, running header, page numbers, DRAFT or CANCELLED watermark, approval sheet), an Excel workbook whose subtotals are formulas, and structured data in Excel or CSV.
- **Workspace** "PSAK 118" with number cards and shortcuts, opened from the PSAK ID tile on the apps screen.

Every statement total reconciles with ERPNext's Profit and Loss for the same company, period and filters, and the statement shows the difference, which must be zero. PSAK ID never writes to the General Ledger, journal entries or ERPNext's own reports.

## Roles

| Role | Can |
|---|---|
| PSAK ID - Accounting - Staff | Read the policy and mappings, prepare statements and submit them for review |
| PSAK ID - Accounting - Head | Maintain the company policy, report lines, mappings and templates, apply templates, prepare and review statements, send them to the CFO or back to draft, reopen a final statement |
| PSAK ID - CFO | Approve statements (Final) or return them to review, reopen a final statement |
| PSAK ID - Auditor | Read everything, including the change history of PSAK ID documents, and print or export |

The PSAK ID roles grant access to PSAK ID documents only. The statements and reports also read ERPNext's Company, accounts and ledger, so give each user an ERPNext role as well:

- give staff, heads and CFOs **Accounts User** or **Accounts Manager**;
- give auditors **Auditor**.

Limit a user to their companies with a User Permission on Company.

## Getting started

1. As the Accounting Head, create a **PSAK ID Company Policy** for the company: adoption date, main business activities, expense presentation, Other Items threshold, default unit and letter head.
2. Open a **PSAK ID Mapping Template** close to the company's business and choose **Apply to Company**. Then map the remaining accounts in **PSAK ID Account Mapping**.
3. Run **PSAK ID Mapping Control** for the period and fix every blocking row.
4. Check the figures in **PSAK 118 Profit or Loss**.
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
