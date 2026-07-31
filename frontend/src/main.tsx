import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function App() {
  return (
    <main>
      <p className="eyebrow">HydraWiki</p>
      <h1>Traceable documentation for your repositories.</h1>
      <p className="status">Foundation ready. Repository workflows arrive in a later phase.</p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
