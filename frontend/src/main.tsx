import { FormEvent, useEffect, useRef, useState } from "react";
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
type GenerationRun = { id: string; repository_id: string; page_path: string; status: "running" | "succeeded" | "failed"; source_selection: object | null; configured_model: string | null; provider_model: string | null; prompt_version: string; error: string | null; started_at: string; completed_at: string | null; diagrams: MermaidDiagram[] };
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
  if (diagram.status !== "safe" || !diagram.svg) return <><p className="error">Mermaid validation failed: {diagram.error ?? "diagram was not approved"}</p><pre>{diagram.source}</pre></>;
  return <img className="diagram" alt="Validated Mermaid diagram" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(diagram.svg)}`} />;
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

function ReaderView({ repositories, selectedRepository, pages, page, select, openPage, openSource, openOperator }: {
  repositories: Repository[]; selectedRepository: Repository | null; pages: WikiPageSummary[]; page: WikiPage | null;
  select: (repository: Repository) => void; openPage: (page: WikiPageSummary) => void; openSource: (citation: Citation) => void; openOperator: () => void;
}) {
  return <main className="reader-shell">
    <header className="reader-header"><div><p className="eyebrow">HydraWiki</p><h1>Technical documentation, ready to read.</h1></div><button className="quiet-button" onClick={openOperator}>Operator dashboard</button></header>
    <section className="repository-bar" aria-label="Repository status"><RepositorySelect repositories={repositories} selectedRepository={selectedRepository} select={select} />{selectedRepository && <p><strong>{selectedRepository.lifecycle_status}</strong>{selectedRepository.last_successful_processing_at ? ` · updated ${timestamp(selectedRepository.last_successful_processing_at)}` : ""}</p>}</section>
    {!selectedRepository ? <section className="reader-empty"><h2>Choose a repository to read its wiki</h2><p>Register and process a repository from the operator dashboard.</p><button onClick={openOperator}>Open operator dashboard</button></section> : pages.length === 0 ? <section className="reader-empty"><h2>No published pages yet</h2><p>{selectedRepository.display_name} does not have documentation ready to read.</p><button onClick={openOperator}>Open operator dashboard</button></section> : <section className="wiki-layout">
      <nav className="page-navigation" aria-label="Published pages"><p className="eyebrow">Published pages</p>{pages.map((summary) => <button className={`page-link ${page?.path === summary.path ? "active" : ""}`} key={summary.path} onClick={() => void openPage(summary)}>{summary.title}</button>)}</nav>
      <article className="reader-page">{page ? <><p className="eyebrow">{selectedRepository.display_name}</p><h2>{page.title}</h2><pre>{page.content}</pre>{page.diagrams.map((diagram) => <SafeDiagram key={diagram.ordinal} diagram={diagram} />)}{page.citations.length > 0 && <footer className="citations"><h3>Sources</h3>{page.citations.map((citation) => <button className="citation" key={citationLabel(citation)} onClick={() => void openSource(citation)}>{citationLabel(citation)}</button>)}</footer>}</> : <><h2>Select a page</h2><p>Choose a published page from the navigation to start reading.</p></>}</article>
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
    {selectedRepository && <section className="dashboard-section"><h2>{selectedRepository.display_name} details</h2><button onClick={start} disabled={startingIngestion || ingestionRunning}>{startingIngestion ? "Starting ingestion" : ingestionRunning ? "Ingestion running" : "Start ingestion"}</button>{canGenerate ? <form ref={generationFormRef} onSubmit={generate}><h3>Generate wiki page</h3><label>Page path <input name="path" required defaultValue="overview" /></label><label>Page title <input name="title" required defaultValue="HydraWiki Overview" /></label><button type="submit" disabled={startingGeneration || generationRunning}>{startingGeneration ? "Starting generation" : generationRunning ? "Generation running" : "Generate wiki page"}</button></form> : <p>Complete ingestion before generating a wiki page.</p>}<div className="panels"><div><h3>Ingestion runs</h3>{ingestionRuns.length === 0 ? <p>No ingestion runs recorded.</p> : ingestionRuns.map((run) => <article className={`run ${runState(run.status)}`} key={run.id}><strong>{runState(run.status)}</strong><p>{run.phase}: {run.current_count} / {run.total_count} ({progressValue(run.percentage)}%)</p><progress aria-label={`${run.phase} progress`} value={progressValue(run.percentage)} max={100}>{progressValue(run.percentage)}%</progress><p>Started: {timestamp(run.started_at)}{run.completed_at ? `; completed: ${timestamp(run.completed_at)}` : ""}</p>{run.error && <p className="error">{run.error}</p>}<a href={`/api/ingestion-runs/${run.id}/entries`} target="_blank" rel="noreferrer">Recorded manifest entries</a></article>)}</div><div><h3>Generation runs</h3>{generationRuns.length === 0 ? <p>No generation runs recorded.</p> : generationRuns.map((run) => <article className={`run ${runState(run.status)}`} key={run.id}><strong>{run.page_path}: {run.status}</strong>{run.status === "running" && <progress aria-label={`${run.page_path} generation is running`}>Generation is running</progress>}<p>Configured model: {run.configured_model ?? "Not available"}</p>{run.provider_model && <p>Provider model: {run.provider_model}</p>}<p>Prompt version: {run.prompt_version}</p><p>Started: {timestamp(run.started_at)}{run.completed_at ? `; completed: ${timestamp(run.completed_at)}` : ""}</p>{run.error && <p className="error">{run.error}</p>}{run.diagrams.map((diagram) => <SafeDiagram key={diagram.ordinal} diagram={diagram} />)}</article>)}</div></div>{page && <article className="page-preview"><h3>Selected page: {page.title}</h3><pre>{page.content}</pre><p>Sources: {page.citations.map(citationLabel).join(", ") || "None"}</p></article>}{source && <article className="source"><h3>{source.path}</h3><p>{source.line_count} indexed lines</p><pre>{source.content}</pre></article>}</section>}
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
  const [error, setError] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  const generationFormRef = useRef<HTMLFormElement>(null);

  async function loadIngestionRuns(repositoryId: string) { setIngestionRuns(await request<IngestionRun[]>(`/api/repositories/${repositoryId}/ingestion-runs`)); }
  async function loadGenerationRuns(repositoryId: string) { setGenerationRuns(await request<GenerationRun[]>(`/api/repositories/${repositoryId}/generation-runs`)); }
  async function loadPublishedPages(repositoryId: string) { setPages(await request<WikiPageSummary[]>(`/api/repositories/${repositoryId}/pages`)); }
  async function select(repository: Repository) { setError(""); setSelectedRepository(repository); setPage(null); setSource(null); try { const [runs, generations, publishedPages] = await Promise.all([request<IngestionRun[]>(`/api/repositories/${repository.id}/ingestion-runs`), request<GenerationRun[]>(`/api/repositories/${repository.id}/generation-runs`), request<WikiPageSummary[]>(`/api/repositories/${repository.id}/pages`)]); setIngestionRuns(runs); setGenerationRuns(generations); setPages(publishedPages); if (publishedPages[0]) setPage(await request<WikiPage>(`/api/repositories/${repository.id}/pages/${encodeURIComponent(publishedPages[0].path)}`)); } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not load repository details"); } }
  async function loadRepositories() { try { const loaded = await request<Repository[]>("/api/repositories"); setRepositories(loaded); if (!selectedRepository && loaded[0]) await select(loaded[0]); } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not load repositories"); } }
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
  async function openSource(citation: Citation) { if (!selectedRepository) return; setError(""); setView("operator"); try { setSource(await request<IndexedSource>(`/api/repositories/${selectedRepository.id}/sources/${encodeURIComponent(citation.path)}`)); } catch (exception) { setError(exception instanceof Error ? exception.message : "Could not load indexed source"); } }

  return view === "reader" ? <ReaderView repositories={repositories} selectedRepository={selectedRepository} pages={pages} page={page} select={select} openPage={openPage} openSource={openSource} openOperator={() => setView("operator")} /> : <OperatorView repositories={repositories} selectedRepository={selectedRepository} sourceType={sourceType} error={error} ingestionRuns={ingestionRuns} generationRuns={generationRuns} startingIngestion={startingIngestion} startingGeneration={startingGeneration} page={page} source={source} formRef={formRef} generationFormRef={generationFormRef} setSourceType={setSourceType} select={select} register={register} remove={remove} start={start} generate={generate} openReader={() => setView("reader")} />;
}

const rootElement = document.getElementById("root");
if (rootElement) createRoot(rootElement).render(<StrictMode><App /></StrictMode>);
