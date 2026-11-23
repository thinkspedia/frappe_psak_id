# Changelog

All notable changes to PSAK ID are listed here. The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- gettext translations like ERPNext: `locale/main.pot` plus PO files for Indonesian, Simplified Chinese, Japanese and Arabic (English is the source). CI fails when they are stale.
- App skeleton for Frappe / ERPNext v15 and v16: module `PSAK ID`, CI on both versions, linters and the Frappe Marketplace Semgrep gate.
- PSAK ID logo (`public/images/psak-id-logo.svg`) for the apps screen and README, and a full-bleed square variant (`public/images/psak-id-marketplace.svg`) for the Frappe Marketplace listing that Pilot shows.
