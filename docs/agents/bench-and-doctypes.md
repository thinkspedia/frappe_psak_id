# Bench Commands & DocType Creation

Referenced from AGENTS.md "Technical Environment".

The Dev bench, container and site names are internal and live on Outline (Memory Bank ›
Tech Context). Below, `<container>`, `<bench>` and `<site>` stand for those values.

## Bench commands

```bash
# Migrate after doctype changes
docker exec <container> bash -c "cd <bench> && bench --site <site> migrate"

# Clear cache
docker exec <container> bash -c "cd <bench> && bench --site <site> clear-cache"

# Bench console (Python REPL)
docker exec -it <container> bash -c "cd <bench> && bench --site <site> console"

# Run this app's tests (one module: add --module frappe_psak_id.tests.test_install)
docker exec <container> bash -c "cd <bench> && bench --site <site> run-tests --app frappe_psak_id"

# Build assets
docker exec <container> bash -c "cd <bench> && bench build --app frappe_psak_id"

# Export a doctype to JSON
docker exec <container> bash -c "cd <bench> && bench --site <site> export-doc 'DocType' 'PSAK ID Account Mapping'"

# Refresh translations after changing strings
docker exec <container> bash -c "cd <bench> && bench generate-pot-file --app frappe_psak_id && bench update-po-files --app frappe_psak_id"
```

## Creating a new doctype

Always create it in Desk on the Dev site (developer mode) → DocType, module `PSAK ID`, name
prefixed `PSAK ID`, then export. Specify for every field: label, fieldname, fieldtype,
mandatory, index, unique, link options, default, hidden / read only, in list view / list
filter, permlevel, `mandatory_depends_on` / `read_only_depends_on`, description (plain
language, no technical references), placeholder. Also: permissions per `PSAK ID - …` role,
naming rule, track changes, and whether it is submittable.

**CRITICAL:** after any change in Desk, immediately `bench export-doc` (or
`bench export-fixtures --app frappe_psak_id` for fixtures) so the JSON is in the repo before
the PR. **Never hand-write or hand-edit DocType JSON.**

Accounting data is read-only for this app: a new doctype stores PSAK ID's own policy,
mapping and report documents, never copies of or changes to ERPNext ledger records.
