import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { getArchitectureDiagram, ApiError, type DiagramResponse } from "../lib/api";
import MermaidDiagram from "../components/MermaidDiagram";

export default function DiagramPage() {
  const { repoName } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const real = (location.state as { real?: DiagramResponse } | null)?.real;

  const [url, setUrl] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await getArchitectureDiagram(url);
      navigate(`/repo/${encodeURIComponent(result.repoName)}/diagram`, {
        state: { real: result },
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  const displayName = real?.repoName ?? repoName;
  const diagramMermaid = real?.diagramMermaid ?? null;

  return (
    <div>
      <h2 className="mb-2 text-2xl font-semibold">{displayName} -- architecture diagram</h2>
      <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
        Generated directly from the Neo4j graph -- no LLM call. Rendered below; the
        raw Mermaid source is available under the diagram.
      </p>

      <form onSubmit={handleSubmit} className="mb-6 flex gap-2">
        <input
          type="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/repo"
          disabled={isSubmitting}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900"
        />
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
        >
          {isSubmitting ? "Generating..." : "Generate diagram"}
        </button>
      </form>
      {error && (
        <p className="mb-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}

      {diagramMermaid ? (
        <MermaidDiagram chart={diagramMermaid} />
      ) : (
        <EmptyDiagram />
      )}
    </div>
  );
}

// Shown until a real diagram exists. This page previously fell back to a hand-written
// Mermaid graph for a repo the user never submitted; it fabricated no metrics, but it
// did present invented structure as though the parser had extracted it.
function EmptyDiagram() {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center dark:border-slate-700">
      <h3 className="mb-2 text-base font-medium text-slate-700 dark:text-slate-300">
        No diagram yet
      </h3>
      <p className="mx-auto max-w-lg text-sm text-slate-500 dark:text-slate-400">
        Submit a repository URL above. The diagram is generated deterministically from the
        parser's output, so there is no meaningful sample to show without a real parse.
      </p>
    </div>
  );
}
