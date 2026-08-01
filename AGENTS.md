# HydraWiki Repository Instructions

## Product boundary

HydraWiki is an open-source platform that creates traceable documentation for explicitly registered local and public code repositories.

Keep the product simple, practical, inventive only where it provides clear user value, and maintainable. Do not add features because reference projects have them.

## Approved MVP constraints

HydraWiki must support:

- Docker deployment for HydraWiki-owned services.
- The existing external LiteLLM service for generation.
- The existing external Ollama service for embeddings.
- Persistent repository, ingestion, wiki, and index lifecycle data.
- Hash-based reuse of unchanged content.
- Delta handling for new, changed, and deleted files.
- Source attribution with file paths and line ranges.
- Truthful, visible ingestion and generation failures.
- No placeholder, fallback, or fabricated wiki content after a failed generation.
- Safe repository deletion including related metadata, chunks, vectors, wiki data, and workspace data.
- Server-side Mermaid validation and safe rendering.

Do not install, replace, reconfigure, or containerize LiteLLM or Ollama unless an approved issue explicitly requires it.

## Sources of truth

- Linear is the source of truth for issue scope, status, priority, dependencies, and task context.
- GitHub is the source of truth for code, branches, commits, pull requests, and CI.
- Repository implementation, tests, and versioned documentation take precedence over assumptions.
- Reference repositories are learning sources only; their behavior is not a HydraWiki requirement unless explicitly approved.

## Change discipline

- Implement only the approved issue scope.
- Do not invent features, requirements, bugs, architecture, follow-up tasks, or acceptance criteria.
- Do not silently expand scope.
- Prefer the smallest complete design that satisfies the approved requirement.
- Do not add speculative abstractions, dependencies, infrastructure, configuration, or cleanup.
- Preserve existing public behavior unless the approved issue explicitly changes it.
- Do not develop directly on `main`.
- Do not merge pull requests unless explicitly requested.
- Work only on the active Linear issue. Its acceptance criteria are the contract; do not invent scope.
- Do not change Linear status, priority, or scope unless explicitly authorized.

## Codex workflow

- Use English for all repository artefacts, commits, pull-request text, and Codex work.
- Never commit secrets, credentials, tokens, real `.env` files, passwords, or private host addresses.
- Do not deploy unless explicitly authorized.
- Do not put changing phase scope or acceptance criteria into `AGENTS.md`; keep those in the active Linear issue.
- Individual task prompts must state the session type, exact Codex profile, Git sync commands, branch, active issue, issue-specific scope and acceptance criteria, task-specific validation, and any deviation from `AGENTS.md`.

## Documentation and language

- Keep all repository documentation, issues, pull-request text, commits, and Codex prompts in English.
- Keep durable architecture decisions in versioned documentation.
- Do not document commands, interfaces, or behavior that do not exist.

## Validation and completion

Before reporting a change as complete:

1. Run focused tests proving the changed behavior.
2. Run applicable regression, lint, type, documentation, Docker, and integration checks when configured and relevant.
3. Run `git diff --check`.
4. Review the complete diff for scope drift and unintended changes.
5. Report every check that was not run and why.

Changes involving persistence, ingestion, caching, deletion, source attribution, external adapters, or Mermaid require relevant integration-level evidence. Unit tests alone are insufficient for lifecycle behavior.

Run the narrowest relevant tests plus required build and configuration checks. Always run `git diff --check`. Report exact commands and results, limitations, blockers, and unverified checks.

## Standard handoff

- Commit the agreed change, push the branch, create or update a draft pull request, post factual validation and blocker notes to the active Linear issue, then stop.

## Completion report

Report:

- Issue or agreed objective.
- Branch.
- Changed files.
- Verified behavior implemented.
- Commands run and exact results.
- Checks not run and why.
- Remaining risks or blockers.
- Commit status.
- Pull-request status.

Stop after the agreed implementation and validation. Do not begin adjacent or follow-up work.
