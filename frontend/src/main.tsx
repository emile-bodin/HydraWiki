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
};

const API = "";

function App() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [sourceType, setSourceType] = useState<"local" | "public_git">("local");
  const [error, setError] = useState("");

  async function load() {
    const response = await fetch(`${API}/api/repositories`);
    if (response.ok) setRepositories(await response.json());
  }

  useEffect(() => { void load(); }, []);

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const data = new FormData(event.currentTarget);
    const payload = sourceType === "local"
      ? { source_type: "local", path: data.get("path"), display_name: data.get("display_name") }
      : { source_type: "public_git", url: data.get("url"), ref: data.get("ref"), display_name: data.get("display_name") };
    const response = await fetch(`${API}/api/repositories`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!response.ok) { setError((await response.json()).detail ?? "Registration failed"); return; }
    event.currentTarget.reset();
    await load();
  }

  async function remove(id: string) {
    const response = await fetch(`${API}/api/repositories/${id}`, { method: "DELETE" });
    if (!response.ok) { setError((await response.json()).detail ?? "Deletion failed"); return; }
    await load();
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
    {error && <p className="error">{error}</p>}
    <section><h2>Registered repositories</h2>{repositories.map((repository) => <article key={repository.id}><div><strong>{repository.display_name}</strong><p>{repository.source_type}: {repository.source_value}{repository.selected_ref ? ` @ ${repository.selected_ref}` : ""}</p><span>{repository.lifecycle_status}</span>{repository.last_error && <p className="error">{repository.last_error}</p>}</div><button onClick={() => void remove(repository.id)}>Delete</button></article>)}</section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
