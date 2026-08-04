# Mermaid

[Index](README.md) · [Previous: Wiki generation](generation.md) · [Next: API reference](api.md)

## Purpose

HydraWiki treats Mermaid as **untrusted model output** until the backend:

1. Extracts fenced Mermaid sources from generated markdown
2. Renders them with a **local pinned Mermaid CLI** (`mmdc` by default)
3. Accepts only an **inert SVG** vocabulary
4. Attaches approved SVG (or durable failure) to the generation run

Client-side Mermaid execution is **not** the trust boundary. The reader displays server-provided SVG as a data-URL image when `status === "safe"`.

## Where it runs

| Concern | Implementation |
|---------|----------------|
| Extraction + orchestration | `WikiStore.validate_mermaid` in `wiki.py` |
| Renderer process + SVG accept | `mermaid.py` (`MermaidRenderer`) |
| Persistence | `generation_diagrams` (migration `006_mermaid_diagrams.sql`) |
| Display | `SafeDiagram` in `frontend/src/main.tsx` |

Generation fails closed if any diagram fails validation: the run does not publish/replace a page.

## Configuration

| Setting | Default | Role |
|---------|---------|------|
| `HYDRAWIKI_MERMAID_RENDERER_COMMAND` | `mmdc` | CLI entrypoint |
| `HYDRAWIKI_MERMAID_TIMEOUT_SECONDS` | 15 | Hard timeout (settings max 60) |
| `HYDRAWIKI_MERMAID_RENDERER_USER` | `hydrawiki-renderer` | Drop privileges to this account |
| `mermaid_max_source_characters` | 50,000 | Input bound |
| `mermaid_max_svg_bytes` | 2,000,000 | Output bound |

A missing renderer account fails rendering closed. Chromium’s sandbox is retained; the process runs as the dedicated renderer user.

## Allowed diagram authoring (prompt policy)

The `wiki-v2` prompt instructs the model to:

- Use standard diagram declarations (for example `flowchart LR`, `sequenceDiagram`)
- Avoid frontmatter `config`, `%%{...}%%` directives, `classDef` / `class` / `style` / `linkStyle`, and `click`
- Emit at most two diagrams in the whole page
- Only draw relationships supported by excerpts

Backend acceptance is stricter than “Mermaid parsed”: presentation and HTML-label oriented features are rejected as part of the trust boundary described in `docs/architecture/api-contract.md`.

## Diagram records

Each diagram row:

| Field | Meaning |
|-------|---------|
| `ordinal` | Order of appearance in the markdown |
| `source` | Original Mermaid text |
| `status` | `safe` or `failed` |
| `svg` | Present only when `safe` |
| `error` | Present only when `failed` |

Check constraint: safe diagrams must have SVG and no error; failed diagrams must have error and no SVG.

## Reader behavior

`SafeDiagram`:

- **safe + svg** → `<img>` with `data:image/svg+xml` encoding of the server SVG
- **otherwise** → error message plus `<pre>` of original source

If markdown contains a `mermaid` fence but no matching approved diagram ordinal, the UI shows a failed diagram card rather than executing Mermaid in the browser.

## Security properties (summary)

From the Phase 7 contract notes:

- Fixed strict site Mermaid configuration (default/classic/Dagre family; presentation keys locked)
- Title-only frontmatter may be accepted; per-diagram configuration is not
- SVG is filtered to a minimal inert vocabulary (no CSS/`style` smuggling except a narrowly parsed root `svg` style exception for CLI `max-width` / white background)
- External `url(...)` references rejected; only local `url(#id)` markers permitted
- Bounded source size, SVG size, and render timeout

## Relationship to publication

```text
generate markdown
      │
      ▼
extract mermaid fences (ordinal order)
      │
      ▼
for each: mmdc render → SVG accept
      │
      ├─ any failure ──► record failed diagram(s), fail run, do not publish
      │
      └─ all safe ─────► record SVGs, continue to publication
```

Failed Mermaid **cannot replace** an existing published page.

## Reproducible check (from API contract)

The contract documents a backend-image check roughly equivalent to building the backend image and invoking `MermaidRenderer` against a trivial flowchart. Use that path for environment validation, not browser rendering.

## Next

- [Wiki generation](generation.md) — full pipeline
- [Frontend](frontend.md) — display details
- [Operations](operations.md) — runtime dependencies
