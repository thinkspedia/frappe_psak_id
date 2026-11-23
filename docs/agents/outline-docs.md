# Outline Docs: PRDs, UAT, References, Memory Bank

Procedures referenced from AGENTS.md "Docs live on Outline".

Everything below lives under `ORGANISATION › 01 Thinkspedia › Projects › Active ›
frappe_psak_id` on Outline (find it via `search_documents`/`list_collections` with query
`'frappe_psak_id'`). This repo is public: it holds only pointer stubs, never the content.
If Outline is unreachable, halt and tell the user — never improvise from memory or write a
local `.md` fallback.

## PRDs (`docs › PRDs`)

Pointer stub: `docs/prd/README.md`.

**Creating a PRD:**

1. Find `docs › PRDs` under the `frappe_psak_id` node.
2. Start from `PRD-TEMPLATE` in that folder (no local template exists).
3. `create_document` titled `PRD-NNN: <Judul>` (next number), prose in Bahasa Indonesia.
4. Status `Draft`. Implementation starts only when the product owner sets it `Approved`.

When a PRD is implemented, set its status to `Implemented` and link the PR(s).

## UAT docs (`docs › UAT`)

Pointer stub: `docs/UAT/README.md`. One doc per feature, `UAT-NNN: <Feature Name>`, next
free number. Two sections in the same doc:

1. **Automation results** — per scenario `[Pending]` / `[Passed]` / `[Failed]`, with the
   proof (URL, DOM, DB row, reconciliation to ERPNext's report) and real bugs found.
2. **Manual re-run guide** — step by step, with the company, period, accounts and
   expected figures, using dates that don't collide with the automation run.

## References (`docs › references`)

BRDs, regulation excerpts (PSAK texts), client inputs and sample statements. Binary files
(PDF, XLSX) are Outline attachments linked from a short doc: `create_attachment`, then
upload to the returned URL. Never commit these files to the repo.

## Memory Bank (`Memory Bank`)

Docs: Active Context, Progress, Project Brief, Product Context, System Patterns, Tech
Context, Changelog. `.memory-bank/*.md` are pointer stubs holding each doc's URL and ID.

1. Session start: fetch **Active Context** only.
2. Before making changes: fetch **Progress**.
3. Fetch Project Brief / Product Context / System Patterns / Tech Context / Changelog only
   when the task needs that doc — never the whole folder.
4. **Updating:** `update_document` with `editMode: "patch"` for a targeted change, or
   `prepend` a dated section (`**DD-MM-YYYY**`) for a new session's findings. When Active
   Context or Progress passes ~300 lines, move the oldest sections into Changelog.
5. Environment details (bench, container, site, URLs, test data) go in **Tech Context**,
   because the repo is public.
6. Never write real content into `.memory-bank/*.md`. If a doc moves, update the stub's
   pointer, not its content.
7. Approved implementation plans: child doc of Memory Bank, titled
   `Plan YYYY-MM-DD: <feature>`.
