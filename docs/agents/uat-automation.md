# UAT Automation & Auto-Fix Engine

Referenced from AGENTS.md "UAT Automation".

Browser click-throughs use the `agent-browser` CLI, **not** the Playwright MCP tool.

## 1. The Execution Loop

* **Scan & Load:** fetch the feature's `UAT-NNN: <Feature Name>` doc from Outline (`docs › UAT`). Take the first scenario in its Automation section still flagged `[Pending]`.
* **Execute:** open the Dev site (URL in Tech Context on Outline) and go step by step through the listed actions.
* **Test data:** build the Company, Chart of Accounts and postings the scenario needs (or use the fixture set named in the UAT doc). Never edit or post into a real company's books.
* **Auto-Fix Gate:** a step breaks because of an app bug, error boundary or failed `frappe.msgprint`:
  1. Halt immediately.
  2. Locate the responsible JS or Python file and patch it.
  3. `bench --site <site> clear-cache`, and `migrate` if schema changed.
  4. Reset the scenario to `[Pending]` and re-run it from scratch. Don't move on until it is green.

## 2. Token-Efficiency Directives

* **No blanket screenshots:** capture only when an assertion fails and the image helps the fix.
* **DOM text over visuals:** assert on targeted nodes (`data-fieldname`, report cells), not whole-page dumps.
* **Wait on selectors, not sleeps.**
* **Context hygiene:** `/compact` after heavy browser runs; never read the whole Memory Bank folder.

## 3. Strict Verification

A scenario is `[Passed]` only when all of these hold:

1. **URL state:** the browser is on the expected route.
2. **Target nodes:** the expected values are rendered, not placeholders.
3. **Database:** a `bench console` check confirms the document/row state the UI claims.
4. **Reconciliation (statements):** the PSAK ID totals equal ERPNext's Profit and Loss / Trial Balance for the same company, period and filters.

Any 403/404/500 seen in the network log during the run is an immediate **FAILURE**, even if the UI looks fine.
