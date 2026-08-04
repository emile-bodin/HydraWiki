import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App, renderDocument, SafeDiagram } from "./main";

const repository = {
  id: "repo-1",
  source_type: "public_git",
  source_value: "https://github.com/example/repository.git",
  selected_ref: "main",
  display_name: "Example repository",
  lifecycle_status: "ready",
  last_error: null,
  current_error: null,
  last_successful_processing_at: "2026-08-04T10:00:00Z",
};
const empty = () => new Response(JSON.stringify([]), { status: 200 });

beforeEach(() => {
  window.history.replaceState({}, "", "/");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function api(overrides: Record<string, unknown> = {}) {
  return vi.fn(async (path: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${path}`;
    const responses: Record<string, Response> = {
      "GET /api/repositories": new Response(JSON.stringify([repository])),
      "GET /api/repositories/repo-1/ingestion-runs": empty(),
      "GET /api/repositories/repo-1/generation-runs": empty(),
      "GET /api/repositories/repo-1/pages": empty(),
    };
    return (
      (overrides[key] as Response | undefined) ??
      responses[key] ??
      new Response(JSON.stringify({ detail: "not found" }), { status: 404 })
    );
  });
}

test("renders the compact landing page and navigates through direct routes", async () => {
  vi.stubGlobal("fetch", api());
  render(<App />);
  expect(
    screen.getByRole("heading", { name: /documentation that stays/i }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Explore repositories" }));
  expect(
    await screen.findByRole("heading", { name: "Repositories" }),
  ).toBeInTheDocument();
  expect(window.location.pathname).toBe("/repositories");
  fireEvent.click(screen.getByRole("link", { name: "Operator" }));
  expect(
    await screen.findByRole("heading", { name: /generate traceable/i }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Register repository" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Register repository" }),
  ).toBeVisible();
  expect(window.location.pathname).toBe("/operator");
});

test("shows normal, missing, and long repository values without losing the wiki action", async () => {
  const long = {
    ...repository,
    id: "repo-2",
    display_name: "A very long repository name ".repeat(10),
    source_value: "https://example.test/" + "long/".repeat(80),
    selected_ref: null,
    last_successful_processing_at: null,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) =>
      path === "/api/repositories"
        ? new Response(JSON.stringify([repository, long]))
        : empty(),
    ),
  );
  window.history.replaceState({}, "", "/repositories");
  render(<App />);
  expect((await screen.findAllByText("Not available")).length).toBeGreaterThan(
    0,
  );
  expect(screen.getAllByRole("button", { name: "Open wiki" })).toHaveLength(2);
  expect(
    screen.getByRole("heading", { name: /A very long repository name/ }),
  ).toBeInTheDocument();
});

test("renders Markdown and preserves a Mermaid failure without breaking the document", () => {
  render(
    <article className="reader-content">
      {renderDocument(
        "# Guide\n\n## Details\n\n[Docs](https://example.com) and `code`.\n\n| Key | Value |\n| --- | --- |\n| A | B |\n\n```ts\nconst value = 1;\n```\n\n```mermaid\ninvalid\n```",
        [
          {
            ordinal: 0,
            source: "invalid",
            status: "failed",
            svg: null,
            error: "invalid syntax",
          },
        ],
      )}
    </article>,
  );
  expect(screen.getByRole("heading", { name: "Guide" })).toBeInTheDocument();
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByText("const value = 1;")).toBeInTheDocument();
  expect(
    screen.getByText("Mermaid diagram could not be rendered"),
  ).toBeInTheDocument();
  expect(screen.getByText("invalid syntax")).toBeInTheDocument();
});

test("renders validated Mermaid SVG", () => {
  render(
    <SafeDiagram
      diagram={{
        ordinal: 0,
        source: "flowchart LR",
        status: "safe",
        svg: "<svg><text>safe</text></svg>",
        error: null,
      }}
    />,
  );
  expect(
    screen.getByRole("img", { name: "Validated Mermaid diagram" }),
  ).toHaveAttribute("src", expect.stringContaining("data:image/svg+xml"));
});

test("runs ingest then generation and exposes the generated documentation link", async () => {
  const ingest = {
    id: "i1",
    status: "succeeded",
    phase: "Complete",
    current_count: 1,
    total_count: 1,
    percentage: 100,
    error: null,
    started_at: "2026-08-04T10:00:00Z",
    completed_at: "2026-08-04T10:01:00Z",
  };
  const generation = {
    id: "g1",
    repository_id: "repo-1",
    page_path: "overview",
    status: "succeeded",
    configured_model: "model",
    provider_model: "model",
    prompt_version: "v2",
    error: null,
    failure_stage: null,
    started_at: "2026-08-04T10:01:00Z",
    completed_at: "2026-08-04T10:02:00Z",
    diagrams: [],
  };
  const fetchMock = api({
    "POST /api/repositories/repo-1/sync": new Response(JSON.stringify(ingest), {
      status: 201,
    }),
    "POST /api/repositories/repo-1/pages": new Response(
      JSON.stringify(generation),
      { status: 201 },
    ),
    "GET /api/repositories/repo-1/pages": new Response(
      JSON.stringify([
        {
          path: "overview",
          title: "HydraWiki Overview",
          lifecycle_status: "published",
          generation_run_id: "g1",
        },
      ]),
    ),
  });
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState({}, "", "/operator");
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Repository"), {
    target: { value: "repo-1" },
  });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Generate wiki" }),
    ).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Generate wiki" }));
  await waitFor(() =>
    expect(fetchMock.mock.calls.map(([path]) => path)).toContain(
      "/api/repositories/repo-1/pages",
    ),
  );
  expect(
    await screen.findByRole("button", { name: "Open generated documentation" }),
  ).toBeInTheDocument();
  const posts = fetchMock.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")
    .map(([path]) => path);
  expect(posts).toEqual([
    "/api/repositories/repo-1/sync",
    "/api/repositories/repo-1/pages",
  ]);
});

test("does not generate after an ingestion error and keeps the failure visible", async () => {
  const ingest = {
    id: "i1",
    status: "failed",
    phase: "Scanning",
    current_count: 0,
    total_count: 1,
    percentage: 0,
    error: "source unavailable",
    started_at: "2026-08-04T10:00:00Z",
    completed_at: "2026-08-04T10:01:00Z",
  };
  const fetchMock = api({
    "POST /api/repositories/repo-1/sync": new Response(JSON.stringify(ingest), {
      status: 201,
    }),
  });
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState({}, "", "/operator");
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Repository"), {
    target: { value: "repo-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate wiki" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "source unavailable",
  );
  expect(
    fetchMock.mock.calls
      .filter(
        ([, init]) => (init as RequestInit | undefined)?.method === "POST",
      )
      .map(([path]) => path),
  ).not.toContain("/api/repositories/repo-1/pages");
});

test("keeps a generation error visible", async () => {
  const ingest = {
    id: "i1",
    status: "succeeded",
    phase: "Complete",
    current_count: 1,
    total_count: 1,
    percentage: 100,
    error: null,
    started_at: "2026-08-04T10:00:00Z",
    completed_at: "2026-08-04T10:01:00Z",
  };
  const generation = {
    id: "g1",
    repository_id: "repo-1",
    page_path: "overview",
    status: "failed",
    configured_model: "model",
    provider_model: null,
    prompt_version: "v2",
    error: "provider unavailable",
    failure_stage: "provider",
    started_at: "2026-08-04T10:01:00Z",
    completed_at: "2026-08-04T10:02:00Z",
    diagrams: [],
  };
  vi.stubGlobal(
    "fetch",
    api({
      "POST /api/repositories/repo-1/sync": new Response(
        JSON.stringify(ingest),
        { status: 201 },
      ),
      "POST /api/repositories/repo-1/pages": new Response(
        JSON.stringify(generation),
        { status: 201 },
      ),
    }),
  );
  window.history.replaceState({}, "", "/operator");
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Repository"), {
    target: { value: "repo-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate wiki" }));
  expect(
    (await screen.findAllByText("provider unavailable")).length,
  ).toBeGreaterThan(0);
});

test("registers a repository and resets the registration form after the API call", async () => {
  const created = { ...repository, id: "repo-2", display_name: "New repository", source_type: "local", source_value: "new-project", selected_ref: null };
  let repositories: unknown[] = [];
  const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === "/api/repositories" && init?.method === "POST") { repositories = [created]; return new Response(JSON.stringify(created), { status: 201 }); }
    if (path === "/api/repositories") return new Response(JSON.stringify(repositories));
    return empty();
  });
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState({}, "", "/operator");
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "New repository" } });
  fireEvent.change(screen.getByLabelText("Source path"), { target: { value: "new-project" } });
  fireEvent.click(screen.getByRole("button", { name: "Register repository" }));
  expect((await screen.findAllByText("New repository")).length).toBeGreaterThan(0);
  expect(screen.getByLabelText("Name")).toHaveValue("");
  expect(fetchMock).toHaveBeenCalledWith("/api/repositories", expect.objectContaining({ method: "POST" }));
});
