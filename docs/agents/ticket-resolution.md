# Ticket & Issue Resolution (Mandatory)

No silent closes. Every ticket/issue/task gets a resolution comment posted before or at
the moment it's marked resolved/closed:

* **Helpdesk tickets** — before/at closing an `HD Ticket`, post an `HD Ticket Comment`
  with the resolution. Customer-visible replies go through the ticket's email reply, in
  formal Indonesian.
* **GitHub issues** — before/at `gh issue close`, post a closing comment. A merged PR's
  `Fixes #N` counts only if that PR's description states root cause + fix.
* **GitHub Project tasks** — comment with what changed and why before moving to Done.

**Minimum comment content:** root cause (one line), what changed, links to the PR(s),
commit(s) and issue(s). Cross-link: a helpdesk comment links the GitHub PR; a GitHub issue
links back to the helpdesk ticket number only (never paste ticket contents, client names or
data into this public repo's issues or PRs).
