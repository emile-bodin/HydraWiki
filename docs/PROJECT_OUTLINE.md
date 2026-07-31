# HydraWiki Project Outline

## Vision

HydraWiki is a self-hosted documentation platform for local and private repositories. It combines repository ingestion, persistent indexing, incremental updates, source-linked documentation, architecture diagrams, and AI-powered Q&A.

The system must keep repository data and model traffic under operator control while remaining usable with LiteLLM and local Ollama services.

## Goals

- Index local, private, and Git-based repositories.
- Persist repository metadata, file fingerprints, indexes, generated pages, and run history.
- Re-index only added, changed, or deleted files when possible.
- Reuse cached results for unchanged content.
- Generate navigable wiki pages with source-file and line references.
- Provide searchable Q&A grounded in indexed repository content.
- Support LiteLLM for generation and Ollama for local embeddings.
- Show truthful ingestion state, numeric progress, errors, partial results, retry, cancel, and delete actions.
- Run as a self-hosted Docker deployment.

## Non-goals

- No arbitrary remote command execution.
- No requirement for a hosted OpenAI API key.
- No replacement of the existing LiteLLM or Ollama infrastructure.
- No claim that a wiki is complete when indexing or generation failed.

## Planned architecture

1. **Repository adapter**
   - Accept local paths, Git URLs, and private repositories.
   - Detect repository identity and revision where available.
   - Apply configurable ignore rules.

2. **Persistent storage**
   - SQLite for repository records, ingestion runs, file fingerprints, generated pages, source references, and index metadata.
   - Versioned schema migrations.
   - Backup and restore support.
   - Cascading delete for a repository and all derived data.

3. **Incremental ingestion**
   - Hash file contents and relevant configuration.
   - Compare the current snapshot with the latest successful snapshot.
   - Process added and changed files.
   - Remove deleted-file records and invalidate affected pages.
   - Rebuild only impacted modules and dependent pages.
   - Trigger a full rebuild when parser, prompt, embedding model, schema, or indexing rules change.

4. **AI and retrieval**
   - Provider-neutral model adapter.
   - LiteLLM Responses API support for generation, including model aliases such as `chatgpt`.
   - Ollama embedding support with model and dimension validation.
   - Content-hash cache for repeatable analysis.
   - Retrieval citations pointing to source files and line ranges.

5. **Web interface and API**
   - Repository and wiki overview on the home page.
   - Persistent list of indexed repositories.
   - Ingestion status with phase, current item, total items, percentage, and timestamps.
   - Retry, cancel, open, and delete flows.
   - Explicit states: queued, scanning, indexing, generating, complete, partial, failed, cancelled.
   - No placeholder content after model or indexing errors.

6. **Documentation output**
   - Repository overview and architecture.
   - Module and component pages.
   - Configuration and operational guides.
   - Source references and line-level evidence.
   - Mermaid diagrams validated before display.

## Delivery phases

### Phase 0: Baseline and contracts

- Confirm repository scope, supported inputs, output types, and privacy boundary.
- Define API schemas and ingestion state machine.
- Define storage schema and migration policy.
- Add a minimal end-to-end health check.

### Phase 1: Persistent project storage

- Add SQLite schema and repository/run records.
- Persist successful and failed ingestion runs.
- Restore indexed wikis after restart.
- Implement safe repository deletion and data cleanup.

### Phase 2: Reliable full ingestion

- Implement deterministic file discovery and ignore rules.
- Store file hashes, metadata, extracted chunks, embeddings, and page provenance.
- Add explicit failure and partial-result handling.
- Add tests for restart, failure, retry, and delete behaviour.

### Phase 3: Delta ingestion

- Compare snapshots using file content hashes.
- Reprocess only changed, added, or deleted files.
- Track dependency and page invalidation.
- Add full-rebuild invalidation for configuration and model changes.
- Report the delta decision in the UI and API.

### Phase 4: Retrieval and model adapters

- Stabilize LiteLLM generation through the configured model alias.
- Add Ollama embedding configuration and dimension checks.
- Add provider capability reporting.
- Add citation-grounded Q&A and source navigation.

### Phase 5: UI and operational workflow

- Add numeric progress and server-sent progress events.
- Add live run details, retry, cancel, and delete.
- Add repository filters and last-indexed revision.
- Add backup/restore and operator diagnostics.

### Phase 6: Quality and deployment

- Add integration tests for local and Git repositories.
- Validate Mermaid output and source citations.
- Add Docker health checks, volume documentation, migrations, and upgrade procedures.
- Document LiteLLM and Ollama configuration without embedding secrets.

## MVP acceptance criteria

- A local repository can be indexed in Docker.
- The indexed wiki remains available after a container restart.
- A second run with no file changes performs no unnecessary model work.
- A run with one changed file processes the affected file and dependent output.
- Deleted files disappear from the derived wiki after a successful run.
- Generation and embedding failures produce explicit failed or partial status.
- The UI shows repository status and numeric progress.
- The UI can open and delete an indexed wiki.
- LiteLLM generation and Ollama embeddings can be configured independently.
- Every generated claim/page has source references or is marked as unsupported.

## Initial technical decisions

- Keep the existing LiteLLM gateway and Ollama GPU host external to HydraWiki.
- Prefer SQLite for the first persistent implementation; keep storage interfaces replaceable.
- Use content hashes as the primary delta mechanism, with Git revision metadata as additional evidence.
- Treat model, embedding, prompt, parser, and ignore-rule versions as cache invalidation inputs.
- Build the smallest complete vertical slice first: persist one repository, ingest it, restore it, and show its status.
