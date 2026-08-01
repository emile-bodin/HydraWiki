import { FormEvent, useEffect, useState } from "react";
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

type IngestionRun = {
  id: string;
  status: "running" | "succeeded" | "failed";
  phase: string;
  current_count: number;
  total_count: number;
  percentage: number;
  error: string | null;
  started_at: string;
  completed_at: string | null;
};

type GenerationRun = {
  id: string;
  page_path: string;
  status: "running" | "succeeded" | "failed";
  error: string | null;
  started_at: string;
  completed_at: string | null;
  diagrams: MermaidDiagram[];
};

type WikiPageSummary = { path: string; title: string; lifecycle_status: "published"; generation_run_id: string };
type Citation = { path: string; line_start: number; line_end: number };
type MermaidDiagram = { ordinal: number; source: string; status: "safe" | "failed"; svg: string | null; error: string | null };
type WikiPage = WikiPageSummary & { id: string; content: string; citations: Citation[]; diagrams: MermaidDiagram[] };
type IndexedSource = { path: string; content: string; line_count: number };

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

function timestamp(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not available";
}

export function SafeDiagram({ diagram }: { diagram: MermaidDiagram }) {
  if (diagram.status !== "safe" || !diagram.svg) return <><p className="error">Mermaid validation failed: {diagram.error ?? "diagram was not approved"}</p><pre>{diagram.source}</pre></>;
  return <img className="diagram" alt="Validated Mermaid diagram" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(diagram.svg)}`} />;
}

export function App() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [sourceType, setSourceType] = useState<"local" | "public_git">("local");
  const [selectedRepository, setSelectedRepository] = useState<Repository | null>(null);
  const [ingestionRuns, setIngestionRuns] = useState<IngestionRun[]>([]);
  const [generationRuns, setGenerationRuns] = useState<GenerationRun[]>([]);
  const [pages, setPages] = useState<WikiPageSummary[]>([]);
  const [page, setPage] = useState<WikiPage | null>(null);
  const [source, setSource] = useState<IndexedSource | null>(null);
  const [error, setError] = useState("");

  async function loadRepositories() {
    try {
      setRepositories(await request<Repository[]>("/api/repositories"));
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not load repositories");
    }
  }

  async function select(repository: Repository) {
    setError("");
    setSelectedRepository(repository);
    setPage(null);
    setSource(null);
    try {
      const [runs, generations, publishedPages] = await Promise.all([
        request<IngestionRun[]>(`/api/repositories/${repository.id}/ingestion-runs`),
        request<GenerationRun[]>(`/api/repositories/${repository.id}/generation-runs`),
        request<WikiPageSummary[]>(`/api/repositories/${repository.id}/pages`),
      ]);
      setIngestionRuns(runs);
      setGenerationRuns(generations);
      setPages(publishedPages);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not load repository details");
    }
  }

  useEffect(() => { void loadRepositories(); }, []);

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const data = new FormData(event.currentTarget);
    const payload = sourceType === "local"
      ? { source_type: "local", path: data.get("path"), display_name: data.get("display_name") }
      : { source_type: "public_git", url: data.get("url"), ref: data.get("ref"), display_name: data.get("display_name") };
    try {
      await request<Repository>("/api/repositories", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      event.currentTarget.reset();
      await loadRepositories();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Registration failed");
    }
  }

  async function remove(id: string) {
    setError("");
    try {
      await request<Repository>(`/api/repositories/${id}`, { method: "DELETE" });
      if (selectedRepository?.id === id) setSelectedRepository(null);
      await loadRepositories();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Deletion failed");
    }
  }

  async function openPage(summary: WikiPageSummary) {
    if (!selectedRepository) return;
    setError("");
    setSource(null);
    try {
      setPage(await request<WikiPage>(`/api/repositories/${selectedRepository.id}/pages/${encodeURIComponent(summary.path)}`));
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not load wiki page");
    }
  }

  async function openSource(citation: Citation) {
    if (!selectedRepository) return;
    setError("");
    try {
      setSource(await request<IndexedSource>(`/api/repositories/${selectedRepository.id}/sources/${encodeURIComponent(citation.path)}`));
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not load indexed source");
    }
  }

  return <main>
    <p className="eyebrow">HydraWiki</p>
    <h1>Repositories</h1>
    <form onSubmit={register}>
      <label>Name <input name="display_name" required /></label>
      <label>Source type <select value={sourceType} onChange={(event) => setSourceType(event.target.value as "local" | "public_git")}><option value="local">Local mount</option><option value="public_git">Public Git</option></select></label>
      {sourceType === "local" ? <label>Path below LOCAL_REPOSITORIES_ROOT <input name="path" required placeholder="project" /></label> : <><label>HTTPS Git URL <input name="url" type="url" required placeholder="https://github.com/org/repo.git" /></label><label>Ref <input name="ref" required placeholder="main" /></label></>}
      <button type="submit">Register repository</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    <section><h2>Registered repositories</h2>{repositories.length === 0 ? <p>No repositories are registered.</p> : repositories.map((repository) => <article key={repository.id} className={selectedRepository?.id === repository.id ? "selected" : ""}><div><button className="repository-name" onClick={() => void select(repository)}>{repository.display_name}</button><p>{repository.source_type}: {repository.source_value}{repository.selected_ref ? ` @ ${repository.selected_ref}` : ""}</p><p>Status: <strong>{repository.lifecycle_status}</strong></p><p>Last successful processing: {timestamp(repository.last_successful_processing_at)}</p>{(repository.current_error ?? repository.last_error) && <p className="error">Current error: {repository.current_error ?? repository.last_error}</p>}</div><button onClick={() => void remove(repository.id)}>Delete</button></article>)}</section>
    {selectedRepository && <section className="operator"><h2>{selectedRepository.display_name} operator view</h2>
      <div className="panels"><div><h3>Ingestion runs</h3>{ingestionRuns.length === 0 ? <p>No ingestion runs recorded.</p> : ingestionRuns.map((run) => <article className={`run ${runState(run.status)}`} key={run.id}><strong>{runState(run.status)}</strong><p>{run.phase}: {run.current_count} / {run.total_count} ({run.percentage}%)</p><p>Started: {timestamp(run.started_at)}{run.completed_at ? `; completed: ${timestamp(run.completed_at)}` : ""}</p>{run.error && <p className="error">{run.error}</p>}<a href={`/api/ingestion-runs/${run.id}/entries`} target="_blank" rel="noreferrer">Recorded manifest entries</a></article>)}</div>
      <div><h3>Wiki pages</h3>{pages.length === 0 ? <p>No published wiki pages are available.</p> : <nav>{pages.map((summary) => <button className="page-link" key={summary.path} onClick={() => void openPage(summary)}>{summary.title} <small>published</small></button>)}</nav>}<h3>Generation runs</h3>{generationRuns.length === 0 ? <p>No generation runs recorded.</p> : generationRuns.map((run) => <article className={`run ${runState(run.status)}`} key={run.id}><strong>{run.page_path}: {runState(run.status)}</strong>{run.error && <p className="error">{run.error}</p>}{run.diagrams.map((diagram) => <SafeDiagram key={diagram.ordinal} diagram={diagram} />)}</article>)}</div></div>
      {page && <article className="page"><h3>{page.title}</h3><pre>{page.content}</pre>{page.diagrams.map((diagram) => <SafeDiagram key={diagram.ordinal} diagram={diagram} />)}<h4>Sources</h4>{page.citations.map((citation) => <button className="citation" key={citationLabel(citation)} onClick={() => void openSource(citation)}>{citationLabel(citation)}</button>)}</article>}
      {source && <article className="source"><h3>{source.path}</h3><p>{source.line_count} indexed lines</p><pre>{source.content}</pre></article>}
    </section>}
  </main>;
}

const rootElement = document.getElementById("root");
if (rootElement) createRoot(rootElement).render(<StrictMode><App /></StrictMode>);
