<div align="center">

<img src="frappe_psak_id/public/images/psak-id-logo.svg" alt="PSAK ID logo" width="96">

# PSAK ID

**Indonesian financial statement presentation (PSAK 118) for ERPNext.**

Present ERPNext's ledger in the PSAK 118 format, without changing ERPNext's core or its standard reports.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
![Frappe](https://img.shields.io/badge/Frappe-v15%20%7C%20v16-0089FF)
![ERPNext](https://img.shields.io/badge/ERPNext-v15%20%7C%20v16-0089FF)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Status](https://img.shields.io/badge/status-in%20development-orange)

</div>

---

## Why PSAK ID?

PSAK 118 *Penyajian dan Pengungkapan dalam Laporan Keuangan* (the Indonesian adoption of IFRS 18) replaces PSAK 201 and takes effect on 1 January 2027, with 2026 comparatives restated. ERPNext's standard Profit and Loss, Balance Sheet and Cash Flow reports do not present those categories and subtotals.

PSAK ID adds the PSAK 118 presentation on top of ERPNext's General Ledger. It only reads the ledger: posting, closing and ERPNext's own reports stay exactly as they are.

## Scope

> PSAK ID is in development. Nothing below is released yet.

| Release | Scope |
|---|---|
| **1** | Per-company PSAK 118 policy, mapping of the Chart of Accounts to the PSAK 118 categories (with industry templates), a mapping check, the PSAK 118 statement of profit or loss with its three required subtotals and restated comparatives, a review and approval flow, and PDF / Excel export |
| **2** | Statement of financial position, statement of cash flows, statement of changes in equity, management-defined performance measures (MPM) |
| **3** | Compliance calendar and regulatory exports |

## Compatibility

| Frappe / ERPNext | Branch | Python |
|---|---|---|
| v16 | `version-16` | 3.14 |
| v15 | `version-15` | 3.10+ |

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
