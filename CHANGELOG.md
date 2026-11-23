# Changelog

All notable changes to PSAK ID are listed here. The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Four PSAK ID roles (Accounting - Staff, Accounting - Head, CFO, Auditor) shipped as fixtures.
- PSAK ID Company Policy: one per company, with the reporting framework, PSAK 118 adoption date, main business activities, expense presentation, Other Items threshold, default unit and letter head that later statements use.
- Instructions for AI coding assistants (`AGENTS.md`, `CLAUDE.md`, `docs/agents/`, shared slash commands) and pointer stubs to the maintainers' PRDs, UAT docs and Memory Bank.
- gettext translations like ERPNext: `locale/main.pot` plus PO files for Indonesian, Simplified Chinese, Japanese and Arabic (English is the source). CI fails when they are stale.
- App skeleton for Frappe / ERPNext v15 and v16: module `PSAK ID`, CI on both versions, linters and the Frappe Marketplace Semgrep gate.
- PSAK ID logo (`public/images/psak-id-logo.svg`) for the apps screen and README, and a full-bleed square variant (`public/images/psak-id-marketplace.svg`) for the Frappe Marketplace listing that Pilot shows.
