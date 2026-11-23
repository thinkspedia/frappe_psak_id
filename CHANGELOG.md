# Changelog

All notable changes to PSAK ID are listed here. The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- PSAK ID Account Mapping: maps each income or expense account of a company to a report line, optionally only for one cost center, project, party or accounting dimension value, with a priority, a start date, the expense nature for the by-nature note and a final tax flag. Rejects accounts of another company, group or balance sheet accounts, non-line targets, final tax mapped to Income Tax, operating expenses without a nature and a second identical rule. Changes are tracked.
- PSAK ID Report Line: tree of statement lines with Indonesian and English labels, PSAK 118 category, sequence, subtotal formula (`+PL-OP-REV -PL-OP-COS +CAT:Operating`), Other Items flag, follows-Operating flag and PSAK 201 line. The standard PSAK 118 statement of profit or loss is inserted on install; the three required subtotals cannot be disabled, deleted or redefined, formulas are checked for unknown lines and loops, and a line used in a formula cannot be deleted.
- Four PSAK ID roles (Accounting - Staff, Accounting - Head, CFO, Auditor) shipped as fixtures.
- PSAK ID Company Policy: one per company, with the reporting framework, PSAK 118 adoption date, main business activities, expense presentation, Other Items threshold, default unit and letter head that later statements use.
- Instructions for AI coding assistants (`AGENTS.md`, `CLAUDE.md`, `docs/agents/`, shared slash commands) and pointer stubs to the maintainers' PRDs, UAT docs and Memory Bank.
- gettext translations like ERPNext: `locale/main.pot` plus PO files for Indonesian, Simplified Chinese, Japanese and Arabic (English is the source). CI fails when they are stale.
- App skeleton for Frappe / ERPNext v15 and v16: module `PSAK ID`, CI on both versions, linters and the Frappe Marketplace Semgrep gate.
- PSAK ID logo (`public/images/psak-id-logo.svg`) for the apps screen and README, and a full-bleed square variant (`public/images/psak-id-marketplace.svg`) for the Frappe Marketplace listing that Pilot shows.
