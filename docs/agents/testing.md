# Running Tests

Referenced from AGENTS.md "Tests".

| When | What to run | Where |
|---|---|---|
| Every PR | The test modules you changed or that import changed code, then `run-tests --app frappe_psak_id` | Dev bench (see Tech Context on Outline) |
| Every PR (automatic) | Whole suite on Frappe/ERPNext v15 and v16, plus the translation-file check on v16 | GitHub Actions `CI` |
| Before a release | Green CI on `develop` for both versions, and the UAT doc for the release `[Passed]` | — |

Rules:

- Tests use `IntegrationTestCase` from `frappe_psak_id.tests.utils` (it maps to `FrappeTestCase` on v15).
- Statement tests build their own Company, Accounts and GL postings (Journal Entries) in the test, then assert the PSAK ID totals equal ERPNext's own report for the same filters. Never depend on data that happens to exist on a site.
- Never `frappe.db.commit()` in code that tests reach; it leaks data across test classes.
- Don't run two suites on the same Dev site at once, and don't use the site in the browser while a suite runs.
- State what you ran and the result in the PR's Test section.
