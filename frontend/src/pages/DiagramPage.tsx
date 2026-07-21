import { useParams } from "react-router-dom";
import { mockAnalysis } from "../lib/mockData";

export default function DiagramPage() {
  const { repoName } = useParams();

  return (
    <div>
      <h2 className="mb-2 text-2xl font-semibold">{repoName} -- architecture diagram</h2>
      <p className="mb-6 text-sm text-slate-600 dark:text-slate-400">
        Placeholder: this shows the raw Mermaid source the Neo4j graph would produce.
        Real Mermaid rendering is a Week 3 task (diagram generation branches off the
        graph directly, not the LLM).
      </p>
      <pre className="overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm dark:border-slate-800 dark:bg-slate-900">
        <code>{mockAnalysis.diagramMermaid}</code>
      </pre>
    </div>
  );
}
