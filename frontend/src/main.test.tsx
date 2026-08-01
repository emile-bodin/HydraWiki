import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { App, citationLabel, runState } from "./main";

const repository = {
  id: "repo-1", source_type: "public_git", source_value: "https://github.com/example/repo.git",
  selected_ref: "main", display_name: "Example", lifecycle_status: "registered", last_error: null,
  last_successful_processing_at: "2026-08-01T10:00:00Z", current_error: null,
};

test("shows durable progress, keeps failed generation separate from published pages, and opens cited indexed source", async () => {
  const fetchMock = vi.fn(async (input: string) => {
    if (input === "/api/repositories") return new Response(JSON.stringify([repository]), { status: 200 });
    if (input === "/api/repositories/repo-1/ingestion-runs") return new Response(JSON.stringify([{
      id: "run-1", status: "running", phase: "Embedding", current_count: 3, total_count: 5, percentage: 60,
      error: null, started_at: "2026-08-01T10:00:00Z", completed_at: null,
    }]), { status: 200 });
    if (input === "/api/repositories/repo-1/generation-runs") return new Response(JSON.stringify([
      { id: "generation-failed", page_path: "failed", status: "failed", error: "provider unavailable", started_at: "2026-08-01T10:00:00Z", completed_at: "2026-08-01T10:01:00Z" },
      { id: "generation-published", page_path: "overview", status: "succeeded", error: null, started_at: "2026-08-01T10:00:00Z", completed_at: "2026-08-01T10:01:00Z" },
    ]), { status: 200 });
    if (input === "/api/repositories/repo-1/pages") return new Response(JSON.stringify([
      { path: "overview", title: "Overview", lifecycle_status: "published", generation_run_id: "generation-published" },
    ]), { status: 200 });
    if (input === "/api/repositories/repo-1/pages/overview") return new Response(JSON.stringify({
      id: "page-1", path: "overview", title: "Overview", lifecycle_status: "published", generation_run_id: "generation-published", content: "# Overview",
      citations: [{ path: "src/app.py", line_start: 4, line_end: 8 }],
    }), { status: 200 });
    if (input === "/api/repositories/repo-1/sources/src%2Fapp.py") return new Response(JSON.stringify({ path: "src/app.py", line_count: 8, content: "print('indexed')" }), { status: 200 });
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  await screen.findByText("Example");
  fireEvent.click(screen.getByRole("button", { name: "Example" }));
  await screen.findByText("Embedding: 3 / 5 (60%)");
  expect(screen.getByText("failed: failed")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Overview published/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /failed published/ })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Overview published/ }));
  await screen.findByText("# Overview");
  fireEvent.click(screen.getByRole("button", { name: "src/app.py:4–8" }));
  await screen.findByText("print('indexed')");
  expect(fetchMock.mock.calls.map(([path]) => path)).toContain("/api/repositories/repo-1/sources/src%2Fapp.py");
});

test("formats citations and run states without inventing success", () => {
  expect(citationLabel({ path: "app.py", line_start: 1, line_end: 2 })).toBe("app.py:1–2");
  expect(runState("running")).toBe("running");
  expect(runState("failed")).toBe("failed");
  expect(runState("succeeded")).toBe("available");
});
