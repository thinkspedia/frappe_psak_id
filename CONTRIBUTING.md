# Contributing to PSAK ID

Thanks for helping. Bug reports, fixes, account-mapping templates and translations are all welcome.

## Before you start

- For anything larger than a small fix, open an issue first so we can agree on the approach.
- Security problems: see [SECURITY.md](SECURITY.md), not a public issue.

## Development setup

```bash
cd frappe-bench
bench get-app erpnext --branch version-16
bench get-app https://github.com/thinkspedia/frappe_psak_id --branch develop
bench --site dev.localhost install-app erpnext
bench --site dev.localhost install-app frappe_psak_id
cd apps/frappe_psak_id
pre-commit install
```

Run the tests:

```bash
bench --site dev.localhost set-config allow_tests true
bench --site dev.localhost run-tests --app frappe_psak_id
```

## Rules for changes

- Target the `develop` branch. `version-15` and `version-16` are release branches.
- The code must work on **Frappe / ERPNext v15 and v16** and stay **Python 3.10 compatible**. Put anything version-specific in `frappe_psak_id/compat.py`. CI runs every test on both versions; a pull request is merged only when both pass.
- Never change ERPNext's core, ledger postings or standard reports. PSAK ID only reads the ledger and presents it.
- Totals must reconcile with ERPNext's own reports for the same company, period and filters; add a test that proves it.
- Nothing client-specific: behaviour is driven by settings and mapping documents, not hard-coded values.
- Create and change DocTypes in Desk on a developer-mode site and commit the exported JSON; never hand-edit DocType JSON.
- Add or update tests with the change, bump `__version__` in `frappe_psak_id/__init__.py` per [Semantic Versioning](https://semver.org/), and keep pull requests small and focused on one thing.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:` …).

## Releasing

For maintainers:

1. Open a `chore: Release vX.Y.Z` PR into `develop` that bumps `__version__`, dates the CHANGELOG entry and updates the README. Merge it once CI passes.
2. Fast-forward `version-15` and `version-16` to `develop`.
3. Publish the GitHub release `vX.Y.Z` on that commit.

## License

By contributing you agree that your contributions are licensed under the [GNU Affero General Public License v3.0](LICENSE).
