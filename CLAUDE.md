# Claude Code Entry Point
Memory Bank System

@AGENTS.md
@.memory-bank/activeContext.md

Note: `.memory-bank/*.md` files are thin pointer stubs, not the real content —
see AGENTS.md's "Docs live on Outline" section. The stub above gives the
Outline doc ID/URL for Active Context; fetch it via the Outline MCP, don't
expect the content inline in this file.

## Strict Token & Context Control (Mandatory)
*   **Targeted Rules Only:** DO NOT bulk-fetch every Outline rule doc at startup. Fetch a specific rule doc (e.g., `04-python-backend`) only when actively modifying code that falls under that exact scope (see AGENTS.md "Coding Rules on Outline").
*   **Context Compression:** If the context window starts bloating or if you detect performance degradation, you MUST explicitly ask the user to run `/compact` before proceeding with the next instruction.
*   **No File Dumps:** Prohibited from doing broad file reads or directory listings unless strictly necessary to locate a missing asset. Trust the paths provided in `activeContext.md` and `AGENTS.md`.

## Public Repository (Mandatory)
This repository is **public**. Never commit client names, ticket contents, real company or
ledger data, internal hostnames, container or site names, credentials, or Outline content.
Those live on Outline (Tech Context for environments); the repo only points to it.
Personal machine-specific notes go in `CLAUDE.local.md` (git-ignored).
