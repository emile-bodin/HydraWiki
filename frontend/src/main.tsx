import { FormEvent, JSX, useEffect, useRef, useState } from "react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Repository = {
  id: string;
  source_type: "local" | "public_git";
  source_value: string;
  selected_ref: string | null;
  display_name: string;
  lifecycle_status: string;
  last_error: string | null;
  last_successful_processing_at: string | null;
  current_error: string | null;
};

type IngestionRun = { id: string; status: "running" | "succeeded" | "failed"; phase: string; current_count: number; total_count: number; percentage: number; error: string | null; started_at: string; completed_at: string | null };
type MermaidDiagram = { ordinal: number; source: string; status: "safe" | "failed"; svg: string | null; error: string | null };
type GenerationRun = { id: string; repository_id: string; page_path: string; status: "running" | "succeeded" | "failed"; source_selection: object | null; configured_model: string | null; provider_model: string | null; prompt_version: string; error: string | null; failure_stage: string | null; started_at: string; completed_at: string | null; diagrams: MermaidDiagram[] };
type GenerationRequest = { path: string; title: string; source_paths: null };
type WikiPageSummary = { path: string; title: string; lifecycle_status: "published"; generation_run_id: string };
type Citation = { path: string; line_start: number; line_end: number };
type WikiPage = WikiPageSummary & { id: string; content: string; citations: Citation[]; diagrams: MermaidDiagram[] };
type IndexedSource = { path: string; content: string; line_count: number };
type View = "reader" | "operator";

const API = "";

export function citationLabel(citation: Citation) {
  return `${citation.path}:${citation.line_start}–${citation.line_end}`;
}

export function runState(status: "running" | "succeeded" | "failed") {
  return status === "succeeded" ? "available" : status;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init);
  if (response.ok) return response.json() as Promise<T>;
  const body = await response.json().catch(() => null);
  throw new Error(body?.detail ?? `Request failed (${response.status})`);
}

export function startIngestion(repositoryId: string) {
  return request<IngestionRun>(`/api/repositories/${repositoryId}/sync`, { method: "POST" });
}

export function startGeneration(repositoryId: string, payload: GenerationRequest) {
  return request<GenerationRun>(`/api/repositories/${repositoryId}/pages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function timestamp(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not available";
}

export function progressValue(percentage: number) {
  return Number.isFinite(percentage) ? Math.min(100, Math.max(0, percentage)) : 0;
}

export function SafeDiagram({ diagram }: { diagram: MermaidDiagram }) {
  if (diagram.status !== "safe" || !diagram.svg) return <section className="diagram-card diagram-failed"><p className="error">Mermaid validation failed: {diagram.error ?? "diagram was not approved"}</p><pre>{diagram.source}</pre></section>;
  return <figure className="diagram-card"><figcaption>Architecture diagram</figcaption><img className="diagram" alt="Validated Mermaid diagram" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(diagram.svg)}`} /></figure>;
}

function safeMarkdownUrl(value: string | undefined) {
  const url = value?.trim() ?? "";
  return /^(https?:|mailto:|\/|#)/i.test(url) ? url : undefined;
}

function renderInline(value: string, keyPrefix: string): JSX.Element[] {
  const token = /!\[([^\]]*)\]\((\S+?)(?:\s+["']([^"']*)["'])?\)|\[([^\]]+)\]\((\S+?)(?:\s+["']([^"']*)["'])?\)|`([^`]+)`|\*\*([^*]+)\*\*|__([^_]+)__|~~([^~]+)~~|\*([^*]+)\*|_([^_]+)_/g;
  const result: JSX.Element[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  let index = 0;
  while ((match = token.exec(value))) {
    if (match.index > cursor) result.push(<span key={`${keyPrefix}-text-${index++}`}>{value.slice(cursor, match.index)}</span>);
    const imageUrl = safeMarkdownUrl(match[2]);
    const linkUrl = safeMarkdownUrl(match[5]);
    if (match[1] && imageUrl) result.push(<img key={`${keyPrefix}-image-${index++}`} src={imageUrl} alt={match[1]} title={match[3]} />);
    else if (match[4] && linkUrl) result.push(<a key={`${keyPrefix}-link-${index++}`} href={linkUrl} title={match[6]} target={/^https?:/i.test(linkUrl) ? "_blank" : undefined} rel={/^https?:/i.test(linkUrl) ? "noreferrer" : undefined}>{match[4]}</a>);
    else if (match[7]) result.push(<code key={`${keyPrefix}-code-${index++}`}>{match[7]}</code>);
    else if (match[8] || match[9]) result.push(<strong key={`${keyPrefix}-strong-${index++}`}>{match[8] ?? match[9]}</strong>);
    else if (match[10]) result.push(<del key={`${keyPrefix}-del-${index++}`}>{match[10]}</del>);
    else if (match[11] || match[12]) result.push(<em key={`${keyPrefix}-em-${index++}`}>{match[11] ?? match[12]}</em>);
    else result.push(<span key={`${keyPrefix}-literal-${index++}`}>{match[0]}</span>);
    cursor = match.index + match[0].length;
  }
  if (cursor < value.length) result.push(<span key={`${keyPrefix}-text-${index}`}>{value.slice(cursor)}</span>);
  return result;
}

function renderList(items: string[], ordered: boolean, key: string) {
  const List = ordered ? "ol" : "ul";
  return <List key={key}>{items.map((item, index) => {
    const task = item.match(/^\[([ xX])\]\s+(.*)$/);
    return <li key={`${key}-${index}`}>{task && <input type="checkbox" checked={task[1].toLowerCase() === "x"} readOnly aria-label={task[2]} />}{renderInline(task?.[2] ?? item, `${key}-${index}`)}</li>;
  })}</List>;
}

export function documentOutline(content: string) {
  return content.replace(/\r\n?/g, "\n").split("\n").flatMap((line) => {
    const heading = line.match(/^\s*(#{2,3})\s+(.+?)\s*#*\s*$/);
    return heading ? [{ level: heading[1].length, title: heading[2] }] : [];
  });
}

export function renderDocument(content: string, diagrams: MermaidDiagram[] = []) {
  const lines = content.replace(/\r\n?/g, "\n").split("\n");
  const blocks: JSX.Element[] = [];
  let index = 0;
  let diagramOrdinal = 0;
  let sectionOrdinal = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    const fence = line.match(/^\s*(```+|~~~+)\s*([^ ]*)\s*$/);
    if (fence) {
      const fenceMarker = fence[1][0];
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !new RegExp(`^\\s*${fenceMarker}{3,}\\s*$`).test(lines[index])) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      if (fence[2].toLowerCase() === "mermaid") {
        const diagram = diagrams.find((item) => item.ordinal === diagramOrdinal++);
        blocks.push(diagram ? <SafeDiagram key={`diagram-${blocks.length}`} diagram={diagram} /> : <section className="diagram-card diagram-failed" key={`diagram-${blocks.length}`}><p className="error">Mermaid validation failed: diagram was not approved</p><pre>{code.join("\n")}</pre></section>);
      } else blocks.push(<pre className="reader-code" data-language={fence[2] || undefined} key={`code-${blocks.length}`}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    const heading = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      const Heading = `h${heading[1].length}` as keyof JSX.IntrinsicElements;
      const sectionId = heading[1].length >= 2 && heading[1].length <= 3 ? `section-${sectionOrdinal++}` : undefined;
      blocks.push(<Heading id={sectionId} key={`heading-${blocks.length}`}>{renderInline(heading[2], `heading-${blocks.length}`)}</Heading>);
      index += 1;
      continue;
    }
    if (/^\s*((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$/.test(line)) {
      blocks.push(<hr key={`rule-${blocks.length}`} />); index += 1; continue;
    }
    if (/^\s*>/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^\s*>/.test(lines[index])) quote.push(lines[index++].replace(/^\s*>\s?/, ""));
      blocks.push(<blockquote key={`quote-${blocks.length}`}>{renderInline(quote.join(" "), `quote-${blocks.length}`)}</blockquote>);
      continue;
    }
    const listMatch = line.match(/^\s*([-*+] |\d+[.)] )(.*)$/);
    if (listMatch) {
      const ordered = /^\d/.test(listMatch[1]);
      const items: string[] = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*([-*+] |\d+[.)] )(.*)$/);
        if (!item || /^\d/.test(item[1]) !== ordered) break;
        items.push(item[2]); index += 1;
      }
      blocks.push(renderList(items, ordered, `list-${blocks.length}`));
      continue;
    }
    if (index + 1 < lines.length && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1])) {
      const cells = (value: string) => value.replace(/^\s*\|\s*|\s*\|\s*$/g, "").split(/\s*\|\s*/);
      const header = cells(line); index += 2;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].includes("|")) { rows.push(cells(lines[index++])); }
      blocks.push(<table key={`table-${blocks.length}`}><thead><tr>{header.map((cell, cellIndex) => <th key={cellIndex}>{renderInline(cell, `table-head-${cellIndex}`)}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{header.map((_, cellIndex) => <td key={cellIndex}>{renderInline(row[cellIndex] ?? "", `table-${rowIndex}-${cellIndex}`)}</td>)}</tr>)}</tbody></table>);
      continue;
    }
    const paragraph: string[] = [line.trim()]; index += 1;
    while (index < lines.length && lines[index].trim() && !/^\s*(#{1,6})\s+|^\s*```|^\s*~~~|^\s*>|^\s*([-*+] |\d+[.)] )/.test(lines[index])) paragraph.push(lines[index++].trim());
    blocks.push(<p key={`paragraph-${blocks.length}`}>{renderInline(paragraph.join(" "), `paragraph-${blocks.length}`)}</p>);
  }
  return blocks;
}

function RepositorySelect({ repositories, selectedRepository, select }: { repositories: Repository[]; selectedRepository: Repository | null; select: (repository: Repository) => void }) {
  return <label className="repository-select">Repository
    <select aria-label="Repository" value={selectedRepository?.id ?? ""} onChange={(event) => {
      const repository = repositories.find((item) => item.id === event.target.value);
      if (repository) void select(repository);
    }}>
      <option value="" disabled>{repositories.length ? "Choose a repository" : "No repositories registered"}</option>
      {repositories.map((repository) => <option key={repository.id} value={repository.id}>{repository.display_name}</option>)}
    </select>
  </label>;
}

function ReaderView({ repositories, selectedRepository, pages, page, source, loading, select, openPage, openSource, openOperator }: {
  repositories: Repository[]; selectedRepository: Repository | null; pages: WikiPageSummary[]; page: WikiPage | null;
  source: IndexedSource | null; loading: boolean; select: (repository: Repository) => void; openPage: (page: WikiPageSummary) => void; openSource: (citation: Citation) => void; openOperator: () => void;
}) {
  return <main className="reader-shell">
    <header className="reader-header"><div><p className="eyebrow">HydraWiki</p><h1>Technical documentation, ready to read.</h1></div><button className="quiet-button" onClick={openOperator}>Operator dashboard</button></header>
    <section className="repository-bar" aria-label="Repository status"><RepositorySelect repositories={repositories} selectedRepository={selectedRepository} select={select} />{selectedRepository && <p><strong>{selectedRepository.display_name}</strong><span> · {selectedRepository.lifecycle_status}</span>{selectedRepository.last_successful_processing_at ? ` · updated ${timestamp(selectedRepository.last_successful_processing_at)}` : ""}</p>}</section>
    {loading ? <section className="reader-empty" aria-live="polite"><p className="eyebrow">Reader</p><h2>Loading your documentation</h2><p>Fetching repositories and published pages.</p></section> : !selectedRepository ? <section className="reader-empty"><p className="eyebrow">Get started</p><h2>Choose a repository to read its wiki</h2><p>Register a repository, index its files, and generate a page from the operator dashboard.</p><button onClick={openOperator}>Open operator dashboard</button></section> : pages.length === 0 ? <section className="reader-empty"><p className="eyebrow">{selectedRepository.display_name}</p><h2>No published pages yet</h2><p>Once ingestion is complete, generate a wiki page from the operator dashboard to see it here.</p><button onClick={openOperator}>Open operator dashboard</button></section> : <section className="wiki-layout">
      <nav className="page-navigation" aria-label="Published pages"><p className="eyebrow">In this wiki</p><h2>{selectedRepository.display_name}</h2><p className="navigation-help">Published pages</p>{pages.map((summary) => <button className={`page-link ${page?.path === summary.path ? "active" : ""}`} key={summary.path} onClick={() => void openPage(summary)}>{summary.title}<span>{summary.path}</span></button>)}</nav>
      <article className="reader-page">{page ? <><p className="eyebrow">{selectedRepository.display_name} / {page.path}</p><h2>{page.title}</h2><div className="reader-content">{renderDocument(page.content, page.diagrams)}</div>{page.citations.length > 0 && <footer className="citations"><div><p className="eyebrow">Traceability</p><h3>Sources</h3><p>Open a citation to inspect the indexed lines behind this page.</p></div><div className="citation-list">{page.citations.map((citation, index) => <button className="citation" key={`${citationLabel(citation)}-${index}`} onClick={() => void openSource(citation)}><span>{citation.path}</span><small>Lines {citation.line_start}–{citation.line_end}</small></button>)}</div></footer>}{source && <aside className="source-drawer" aria-label="Indexed source"><div><p className="eyebrow">Indexed source</p><h3>{source.path}</h3><p>{source.line_count} indexed lines</p></div><pre>{source.content}</pre></aside>}</> : <><h2>Select a page</h2><p>Choose a published page from the navigation to start reading.</p></>}</article>
      {page && documentOutline(page.content).length > 0 && <nav className="page-outline" aria-label="On this page"><p className="eyebrow">On this page</p>{documentOutline(page.content).map((heading, index) => <button className={`outline-link level-${heading.level}`} key={`${heading.title}-${index}`} onClick={() => document.getElementById(`section-${index}`)?.scrollIntoView({ behavior: "smooth" })}>{heading.title}</button>)}</nav>}
    </section>}
  </main>;
}

function OperatorView({ repositories, selectedRepository, sourceType, error, ingestionRuns, generationRuns, startingIngestion, startingGeneration, page, source, formRef, generationFormRef, setSourceType, select, register, remove, start, generate, openReader }: {
  repositories: Repository[]; selectedRepository: Repository | null; sourceType: "local" | "public_git"; error: string; ingestionRuns: IngestionRun[]; generationRuns: GenerationRun[]; startingIngestion: boolean; startingGeneration: boolean; page: WikiPage | null; source: IndexedSource | null; formRef: React.RefObject<HTMLFormElement | null>; generationFormRef: React.RefObject<HTMLFormElement | null>;
  setSourceType: (value: "local" | "public_git") => void; select: (repository: Repository) => void; register: (event: FormEvent<HTMLFormElement>) => void; remove: (id: string) => void; start: () => void; generate: (event: FormEvent<HTMLFormElement>) => void; openReader: () => void;
}) {
  const ingestionRunning = ingestionRuns.some((run) => run.status === "running");
  const generationRunning = generationRuns[0]?.status === "running";
  const canGenerate = Boolean(selectedRepository?.last_successful_processing_at) || ingestionRuns.some((run) => run.status === "succeeded");
  return <main className="operator-shell"><header className="operator-header"><div><p className="eyebrow">HydraWiki</p><h1>Operator dashboard</h1><p>Manage repositories and inspect processing details.</p></div><button className="quiet-button" onClick={openReader}>Back to wiki reader</button></header>
    {error && <p className="error" role="alert">{error}</p>}
    <section className="dashboard-section"><h2>Register repository</h2><form ref={formRef} onSubmit={register}><label>Name <input name="display_name" required /></label><label>Source type <select value={sourceType} onChange={(event) => setSourceType(event.target.value as "local" | "public_git")}><option value="local">Local mount</option><option value="public_git">Public Git</option></select></label>{sourceType === "local" ? <label>Path below LOCAL_REPOSITORIES_ROOT <input name="path" required placeholder="project" /></label> : <><label>HTTPS Git URL <input name="url" type="url" required placeholder="https://github.com/org/repo.git" /></label><label>Ref <input name="ref" required placeholder="main" /></label></>}<button type="submit">Register repository</button></form></section>
    <section className="dashboard-section"><h2>Registered repositories</h2>{repositories.length === 0 ? <p>No repositories are registered.</p> : repositories.map((repository) => <article key={repository.id} className={`repository-card ${selectedRepository?.id === repository.id ? "selected" : ""}`}><div><button className="repository-name" onClick={() => void select(repository)}>{repository.display_name}</button><p>{repository.source_type}: {repository.source_value}{repository.selected_ref ? ` @ ${repository.selected_ref}` : ""}</p><p>Status: <strong>{repository.lifecycle_status}</strong></p><p>Last successful processing: {timestamp(repository.last_successful_processing_at)}</p>{(repository.current_error ?? repository.last_error) && <p className="error">Current error: {repository.current_error ?? repository.last_error}</p>}</div><button onClick={() => void remove(repository.id)}>Delete</button></article>)}</section>
    {selectedRepository && <section className="dashboard-section"><h2>{selectedRepository.display_name} details</h2><button onClick={start} disabled={startingIngestion || ingestionRunning}>{startingIngestion ? "Starting ingestion" : ingestionRunning ? "Ingestion running" : "Start ingestion"}</button>{canGenerate ? <form ref={generationFormRef} onSubmit={generate}><h3>Generate wiki page</h3><label>Page path <input name="path" required defaultValue="overview" /></label><label>Page title <input name="title" required defaultValue="HydraWiki Overview" /></label><button type="submit" disabled={startingGeneration || generationRunning}>{startingGeneration ? "Starting generation" : generationRunning ? "Generation running" : "Generate wiki page"}</button></form> : <p>Complete ingestion before generating a wiki page.</p>}<div className="panels"><div><h3>Ingestion runs</h3>{ingestionRuns.length === 0 ? <p>No ingestion runs recorded.</p> : ingestionRuns.map((run) => <article className={`run ${runState(run.status)}`} key={run.id}><strong>{runState(run.status)}</strong><p>{run.phase}: {run.current_count} / {run.total_count} ({progressValue(run.percentage)}%)</p><progress aria-label={`${run.phase} progress`} value={progressValue(run.percentage)} max={100}>{progressValue(run.percentage)}%</progress><p>Started: {timestamp(run.started_at)}{run.completed_at ? `; completed: ${timestamp(run.completed_at)}` : ""}</p>{run.error && <p className="error">{run.error}</p>}<a href={`/api/ingestion-runs/${run.id}/entries`} target="_blank" rel="noreferrer">Recorded manifest entries</a></article>)}</div><div><h3>Generation runs</h3>{generationRuns.length === 0 ? <p>No generation runs recorded.</p> : generationRuns.map((run) => <article className={`run ${runState(run.status)}`} key={run.id}><strong>{run.page_path}: {run.status}</strong>{run.status === "running" && <progress aria-label={`${run.page_path} generation is running`}>Generation is running</progress>}<p>Configured model: {run.configured_model ?? "Not available"}</p>{run.provider_model && <p>Provider model: {run.provider_model}</p>}<p>Prompt version: {run.prompt_version}</p>{run.failure_stage && <p>Failure stage: {run.failure_stage}</p>}<p>Started: {timestamp(run.started_at)}{run.completed_at ? `; completed: ${timestamp(run.completed_at)}` : ""}</p>{run.error && <p className="error">{run.error}</p>}{run.diagrams.map((diagram) => <SafeDiagram key={diagram.ordinal} diagram={diagram} />)}</article>)}</div></div>{page && <article className="page-preview"><h3>Selected page: {page.title}</h3><pre>{page.content}</pre><p>Sources: {page.citations.map(citationLabel).join(", ") || "None"}</p></article>}{source && <article className="source"><h3>{source.path}</h3><p>{source.line_count} indexed lines</p><pre>{source.content}</pre></article>}</section>}
  </main>;
}

export function App() {
  const [view, setView] = useState<View>("reader");
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [sourceType, setSourceType] = useState<"local" | "public_git">("local");
  const [selectedRepository, setSelectedRepository] = useState<Repository | null>(null);
  const [ingestionRuns, setIngestionRuns] = useState<IngestionRun[]>([]);
  const [startingIngestion, setStartingIngestion] = useState(false);
  const [generationRuns, setGenerationRuns] = useState<GenerationRun[]>([]);
  const [startingGeneration, setStartingGeneration] = useState(false);
  const [pages, setPages] = useState<WikiPageSummary[]>([]);
  const [page, setPage] = useState<WikiPage | null>(null);
  const [source, setSource] = useState<IndexedSource | null>(null);
  const [loadingRepositories, setLoadingRepositories] = useState(true);
  const [error, setError] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  const generationFormRef = useRef<HTMLFormElement>(null);

  async function loadIngestionRuns(repositoryId: string) { setIngestionRuns(await request<IngestionRun[]>(`/api/repositories/${repositoryId}/ingestion-runs`)); }
  async function loadGenerationRuns(repositoryId: string) { setGenerationRuns(await request<GenerationRun[]>(`/api/repositories/${repositoryId}/generation-runs`)); }
  async function loadPublishedPages(repositoryId: string) { setPages(await request<WikiPageSummary[]>(`/api/repositories/${repositoryId}/pages`)); }
  async function select(repository: Repository) { setError(""); setSelectedRepository(repository); setPage(null); setSource(null); try { const [runs, generations, publishedPages] = await Promise.all([request<IngestionRun[]>(`/api/repositories/${repository.id}/ingestion-runs`), request<GenerationRun[]>(`/api/repositories/${repository.id}/generation-runs`), request<WikiPageSummary[]>(`/api/repositories/${repository.id}/pages`)]); setIngestionRuns(runs); setGenerationRuns(generations); setPages(publishedPages); if (publishedPages[0]) setPage(await request<WikiPage>(`/api/repositories/${repository.id}/pages/${encodeURIComponent(publishedPages[0].path)}`)); } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not load repository details"); } }
  async function loadRepositories() { try { const loaded = await request<Repository[]>("/api/repositories"); setRepositories(loaded); if (!selectedRepository && loaded[0]) await select(loaded[0]); } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not load repositories"); } finally { setLoadingRepositories(false); } }
  useEffect(() => { void loadRepositories(); }, []);
  useEffect(() => {
    if (!selectedRepository || (!startingIngestion && ingestionRuns[0]?.status !== "running")) return;
    const timer = window.setInterval(() => { void loadIngestionRuns(selectedRepository.id).catch((exception: unknown) => setError(exception instanceof Error ? exception.message : "Could not refresh ingestion progress")); }, 1500);
    return () => window.clearInterval(timer);
  }, [selectedRepository?.id, ingestionRuns[0]?.status, startingIngestion]);
  useEffect(() => {
    if (!selectedRepository || (!startingGeneration && generationRuns[0]?.status !== "running")) return;
    const timer = window.setInterval(() => { void loadGenerationRuns(selectedRepository.id).catch((exception: unknown) => setError(exception instanceof Error ? exception.message : "Could not refresh generation status")); }, 1500);
    return () => window.clearInterval(timer);
  }, [selectedRepository?.id, generationRuns[0]?.status, startingGeneration]);
  useEffect(() => {
    if (!selectedRepository || generationRuns[0]?.status !== "succeeded") return;
    void loadPublishedPages(selectedRepository.id).catch((exception: unknown) => setError(exception instanceof Error ? exception.message : "Could not refresh published pages"));
  }, [selectedRepository?.id, generationRuns[0]?.id, generationRuns[0]?.status]);
  async function register(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setError(""); const data = new FormData(event.currentTarget); const payload = sourceType === "local" ? { source_type: "local", path: data.get("path"), display_name: data.get("display_name") } : { source_type: "public_git", url: data.get("url"), ref: data.get("ref"), display_name: data.get("display_name") }; try { await request<Repository>("/api/repositories", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); formRef.current?.reset(); await loadRepositories(); } catch (exception) { setError(exception instanceof Error ? exception.message : "Registration failed"); } }
  async function remove(id: string) { setError(""); try { await request<Repository>(`/api/repositories/${id}`, { method: "DELETE" }); if (selectedRepository?.id === id) { setSelectedRepository(null); setPages([]); setPage(null); setSource(null); } await loadRepositories(); } catch (exception) { setError(exception instanceof Error ? exception.message : "Deletion failed"); } }
  async function start() { if (!selectedRepository) return; setError(""); setStartingIngestion(true); try { const run = await startIngestion(selectedRepository.id); setIngestionRuns((runs) => [run, ...runs.filter((existing) => existing.id !== run.id)]); await loadIngestionRuns(selectedRepository.id); } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not start ingestion"); } finally { setStartingIngestion(false); } }
  async function generate(event: FormEvent<HTMLFormElement>) { if (!selectedRepository) return; event.preventDefault(); setError(""); setStartingGeneration(true); const data = new FormData(event.currentTarget); try { const run = await startGeneration(selectedRepository.id, { path: String(data.get("path")), title: String(data.get("title")), source_paths: null }); setGenerationRuns((runs) => [run, ...runs.filter((existing) => existing.id !== run.id)]); await loadGenerationRuns(selectedRepository.id); if (run.status === "succeeded") await loadPublishedPages(selectedRepository.id); } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not start generation"); } finally { setStartingGeneration(false); } }
  async function openPage(summary: WikiPageSummary) { if (!selectedRepository) return; setError(""); setSource(null); try { setPage(await request<WikiPage>(`/api/repositories/${selectedRepository.id}/pages/${encodeURIComponent(summary.path)}`)); } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not load wiki page"); } }
  async function openSource(citation: Citation) { if (!selectedRepository) return; setError(""); try { setSource(await request<IndexedSource>(`/api/repositories/${selectedRepository.id}/sources/${encodeURIComponent(citation.path)}`)); } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not load indexed source"); } }

  return view === "reader" ? <ReaderView repositories={repositories} selectedRepository={selectedRepository} pages={pages} page={page} source={source} loading={loadingRepositories} select={select} openPage={openPage} openSource={openSource} openOperator={() => setView("operator")} /> : <OperatorView repositories={repositories} selectedRepository={selectedRepository} sourceType={sourceType} error={error} ingestionRuns={ingestionRuns} generationRuns={generationRuns} startingIngestion={startingIngestion} startingGeneration={startingGeneration} page={page} source={source} formRef={formRef} generationFormRef={generationFormRef} setSourceType={setSourceType} select={select} register={register} remove={remove} start={start} generate={generate} openReader={() => setView("reader")} />;
}

const rootElement = document.getElementById("root");
if (rootElement) createRoot(rootElement).render(<StrictMode><App /></StrictMode>);
