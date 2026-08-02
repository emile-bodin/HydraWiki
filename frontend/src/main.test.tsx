import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App, citationLabel, progressValue, runState } from "./main";

const repository = {
  id: "repo-1", source_type: "public_git", source_value: "https://github.com/example/repo.git",
  selected_ref: "main", display_name: "Example", lifecycle_status: "registered", last_error: null,
  last_successful_processing_at: "2026-08-01T10:00:00Z", current_error: null,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("shows durable progress, keeps failed generation separate from published pages, and opens cited indexed source", async () => {
  const fetchMock = vi.fn(async (input: string) => {
    if (input === "/api/repositories") return new Response(JSON.stringify([repository]), { status: 200 });
    if (input === "/api/repositories/repo-1/ingestion-runs") return new Response(JSON.stringify([{
      id: "run-1", status: "running", phase: "Embedding", current_count: 3, total_count: 5, percentage: 60,
      error: null, started_at: "2026-08-01T10:00:00Z", completed_at: null,
    }]), { status: 200 });
    if (input === "/api/repositories/repo-1/generation-runs") return new Response(JSON.stringify([
      { id: "generation-failed", page_path: "failed", status: "failed", error: "provider unavailable", started_at: "2026-08-01T10:00:00Z", completed_at: "2026-08-01T10:01:00Z", diagrams: [{ ordinal: 0, source: "flowchart TD\nA-->B", status: "failed", svg: null, error: "invalid syntax" }] },
      { id: "generation-published", page_path: "overview", status: "succeeded", error: null, started_at: "2026-08-01T10:00:00Z", completed_at: "2026-08-01T10:01:00Z", diagrams: [] },
    ]), { status: 200 });
    if (input === "/api/repositories/repo-1/pages") return new Response(JSON.stringify([
      { path: "overview", title: "Overview", lifecycle_status: "published", generation_run_id: "generation-published" },
    ]), { status: 200 });
    if (input === "/api/repositories/repo-1/pages/overview") return new Response(JSON.stringify({
      id: "page-1", path: "overview", title: "Overview", lifecycle_status: "published", generation_run_id: "generation-published", content: "# Overview",
      citations: [{ path: "src/app.py", line_start: 4, line_end: 8 }], diagrams: [{ ordinal: 0, source: "flowchart TD\nA-->B", status: "safe", svg: "<svg><text>safe</text></svg>", error: null }],
    }), { status: 200 });
    if (input === "/api/repositories/repo-1/sources/src%2Fapp.py") return new Response(JSON.stringify({ path: "src/app.py", line_count: 8, content: "print('indexed')" }), { status: 200 });
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  await screen.findByText("Technical documentation, ready to read.");
  expect(await screen.findByText("# Overview")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Operator dashboard" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Operator dashboard" }));
  await screen.findByText("Operator dashboard");
  await screen.findByText("Example");
  fireEvent.click(screen.getByRole("button", { name: "Example" }));
  await screen.findByText("Embedding: 3 / 5 (60%)");
  expect(screen.getByRole("progressbar", { name: "Embedding progress" })).toHaveAttribute("value", "60");
  expect(screen.getByText("failed: failed")).toBeInTheDocument();
  expect(screen.getByText("Mermaid validation failed: invalid syntax")).toBeInTheDocument();
  expect(screen.getByText((_, element) => element?.tagName === "PRE" && element.textContent === "flowchart TD\nA-->B")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Back to wiki reader" }));
  await screen.findByRole("button", { name: "Overview" });
  fireEvent.click(screen.getByRole("button", { name: "Overview" }));
  await screen.findByText("# Overview");
  expect(screen.getByRole("img", { name: "Validated Mermaid diagram" }).getAttribute("src")).toContain("data:image/svg+xml");
  fireEvent.click(screen.getByRole("button", { name: "src/app.py:4–8" }));
  await screen.findByText("print('indexed')");
  expect(fetchMock.mock.calls.map(([path]) => path)).toContain("/api/repositories/repo-1/sources/src%2Fapp.py");
});

test("formats citations and run states without inventing success", () => {
  expect(citationLabel({ path: "app.py", line_start: 1, line_end: 2 })).toBe("app.py:1–2");
  expect(runState("running")).toBe("running");
  expect(runState("failed")).toBe("failed");
  expect(runState("succeeded")).toBe("available");
  expect(progressValue(125)).toBe(100);
  expect(progressValue(-1)).toBe(0);
});

test("starts ingestion and shows the returned running progress", async () => {
  const runningRun = { id: "run-2", status: "running", phase: "Scanning", current_count: 37, total_count: 61, percentage: 61, error: null, started_at: "2026-08-02T10:00:00Z", completed_at: null };
  let ingestionRuns: typeof runningRun[] = [];
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    if (input === "/api/repositories") return new Response(JSON.stringify([repository]), { status: 200 });
    if (input === "/api/repositories/repo-1/ingestion-runs") return new Response(JSON.stringify(ingestionRuns), { status: 200 });
    if (input === "/api/repositories/repo-1/generation-runs" || input === "/api/repositories/repo-1/pages") return new Response(JSON.stringify([]), { status: 200 });
    if (input === "/api/repositories/repo-1/sync" && init?.method === "POST") { ingestionRuns = [runningRun]; return new Response(JSON.stringify(runningRun), { status: 201 }); }
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Operator dashboard" }));
  await screen.findByRole("button", { name: "Start ingestion" });
  fireEvent.click(screen.getByRole("button", { name: "Start ingestion" }));

  await screen.findByText("Scanning: 37 / 61 (61%)");
  expect(screen.getByRole("progressbar", { name: "Scanning progress" })).toHaveAttribute("value", "61");
  expect(screen.getByRole("button", { name: "Ingestion running" })).toBeDisabled();
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/repositories/repo-1/sync", { method: "POST" }));
});

test("starts generation and refreshes published pages after success", async () => {
  const runningGeneration = { id: "generation-1", repository_id: "repo-1", page_path: "overview", status: "running", source_selection: null, configured_model: "wiki-model", provider_model: null, prompt_version: "v1", error: null, started_at: "2026-08-02T10:00:00Z", completed_at: null, diagrams: [] };
  const succeededGeneration = { ...runningGeneration, status: "succeeded", provider_model: "provider-wiki-model", completed_at: "2026-08-02T10:01:00Z" };
  let generationRuns: object[] = [];
  let pages: object[] = [];
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    if (input === "/api/repositories") return new Response(JSON.stringify([repository]), { status: 200 });
    if (input === "/api/repositories/repo-1/ingestion-runs") return new Response(JSON.stringify([]), { status: 200 });
    if (input === "/api/repositories/repo-1/pages" && init?.method === "POST") {
      generationRuns = [succeededGeneration];
      pages = [{ path: "overview", title: "HydraWiki Overview", lifecycle_status: "published", generation_run_id: "generation-1" }];
      return new Response(JSON.stringify(succeededGeneration), { status: 201 });
    }
    if (input === "/api/repositories/repo-1/generation-runs") return new Response(JSON.stringify(generationRuns), { status: 200 });
    if (input === "/api/repositories/repo-1/pages") return new Response(JSON.stringify(pages), { status: 200 });
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Operator dashboard" }));
  fireEvent.click(screen.getByRole("button", { name: "Generate wiki page" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/repositories/repo-1/pages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: "overview", title: "HydraWiki Overview", source_paths: null }),
  }));
  await screen.findByText("Provider model: provider-wiki-model");
  expect(fetchMock.mock.calls.filter(([path]) => path === "/api/repositories/repo-1/pages").length).toBeGreaterThan(1);
});

test("shows running, succeeded, and failed generation details without numeric generation progress", async () => {
  const runningGeneration = { id: "generation-running", repository_id: "repo-1", page_path: "draft", status: "running", source_selection: null, configured_model: "wiki-model", provider_model: null, prompt_version: "v1", error: null, started_at: "2026-08-02T10:00:00Z", completed_at: null, diagrams: [] };
  const succeededGeneration = { ...runningGeneration, id: "generation-succeeded", page_path: "overview", status: "succeeded", provider_model: "provider-wiki-model", completed_at: "2026-08-02T10:01:00Z" };
  const failedGeneration = { id: "generation-failed", repository_id: "repo-1", page_path: "overview", status: "failed", source_selection: null, configured_model: "wiki-model", provider_model: null, prompt_version: "v2", error: "provider unavailable", started_at: "2026-08-02T10:00:00Z", completed_at: "2026-08-02T10:01:00Z", diagrams: [] };
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    if (input === "/api/repositories") return new Response(JSON.stringify([repository]), { status: 200 });
    if (input === "/api/repositories/repo-1/ingestion-runs") return new Response(JSON.stringify([]), { status: 200 });
    if (input === "/api/repositories/repo-1/generation-runs") return new Response(JSON.stringify([runningGeneration, succeededGeneration, failedGeneration]), { status: 200 });
    if (input === "/api/repositories/repo-1/pages") return new Response(JSON.stringify([]), { status: 200 });
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Operator dashboard" }));
  expect(await screen.findByText("draft: running")).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "draft generation is running" })).not.toHaveAttribute("value");
  expect(screen.getByText("overview: succeeded")).toBeInTheDocument();
  expect(screen.getByText("overview: failed")).toBeInTheDocument();
  expect(screen.getAllByText("Configured model: wiki-model")).toHaveLength(3);
  expect(screen.getByText("Prompt version: v2")).toBeInTheDocument();
  expect(screen.getByText("provider unavailable")).toBeInTheDocument();
});

test("shows a visible generation API error", async () => {
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    if (input === "/api/repositories") return new Response(JSON.stringify([repository]), { status: 200 });
    if (input === "/api/repositories/repo-1/pages" && init?.method === "POST") return new Response(JSON.stringify({ detail: "A generation run is already running" }), { status: 409 });
    if (input === "/api/repositories/repo-1/ingestion-runs" || input === "/api/repositories/repo-1/generation-runs" || input === "/api/repositories/repo-1/pages") return new Response(JSON.stringify([]), { status: 200 });
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Operator dashboard" }));
  fireEvent.click(screen.getByRole("button", { name: "Generate wiki page" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("A generation run is already running");
});

test("shows an operator error when ingestion is already running", async () => {
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    if (input === "/api/repositories") return new Response(JSON.stringify([repository]), { status: 200 });
    if (input === "/api/repositories/repo-1/ingestion-runs" || input === "/api/repositories/repo-1/generation-runs" || input === "/api/repositories/repo-1/pages") return new Response(JSON.stringify([]), { status: 200 });
    if (input === "/api/repositories/repo-1/sync" && init?.method === "POST") return new Response(JSON.stringify({ detail: "An ingestion run is already running" }), { status: 409 });
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Operator dashboard" }));
  fireEvent.click(await screen.findByRole("button", { name: "Start ingestion" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("An ingestion run is already running");
});

test("registers a Public Git repository and refreshes the registered list", async () => {
  const createdRepository = {
    ...repository,
    id: "repo-2",
    display_name: "HydraWiki",
    source_value: "https://github.com/emile-bodin/HydraWiki.git",
  };
  let repositories: typeof repository[] = [];
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    if (input === "/api/repositories" && !init) return new Response(JSON.stringify(repositories), { status: 200 });
    if (input === "/api/repositories" && init?.method === "POST") {
      repositories = [createdRepository];
      return new Response(JSON.stringify(createdRepository), { status: 201 });
    }
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Operator dashboard" }));
  await screen.findByText("No repositories are registered.");
  fireEvent.change(screen.getByLabelText("Source type"), { target: { value: "public_git" } });
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "HydraWiki" } });
  fireEvent.change(screen.getByLabelText("HTTPS Git URL"), { target: { value: createdRepository.source_value } });
  fireEvent.change(screen.getByLabelText("Ref"), { target: { value: "main" } });
  fireEvent.click(screen.getByRole("button", { name: "Register repository" }));

  await screen.findByRole("button", { name: "HydraWiki" });
  expect(screen.queryByText("No repositories are registered.")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/repositories", expect.objectContaining({ method: "POST" }));
  expect(screen.getByLabelText("HTTPS Git URL")).toHaveValue("");
});

test("shows a registration error without a runtime exception", async () => {
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    if (input === "/api/repositories" && !init) return new Response(JSON.stringify([]), { status: 200 });
    if (input === "/api/repositories" && init?.method === "POST") return new Response(JSON.stringify({ detail: "Repository URL is not reachable" }), { status: 422 });
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Operator dashboard" }));
  await screen.findByText("No repositories are registered.");
  fireEvent.change(screen.getByLabelText("Source type"), { target: { value: "public_git" } });
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Broken repository" } });
  fireEvent.change(screen.getByLabelText("HTTPS Git URL"), { target: { value: "https://github.com/example/missing.git" } });
  fireEvent.change(screen.getByLabelText("Ref"), { target: { value: "main" } });
  fireEvent.click(screen.getByRole("button", { name: "Register repository" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Repository URL is not reachable");
  expect(screen.getByRole("button", { name: "Register repository" })).toBeInTheDocument();
});

test("uses the reader empty state to direct operators to setup", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })));
  render(<App />);

  await screen.findByText("Choose a repository to read its wiki");
  fireEvent.click(screen.getByRole("button", { name: "Open operator dashboard" }));
  expect(await screen.findByText("Operator dashboard")).toBeInTheDocument();
});
