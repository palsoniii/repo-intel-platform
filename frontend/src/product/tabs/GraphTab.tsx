import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import fcose from "cytoscape-fcose";
import { api, type GraphElements, type NodeKind } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import { ErrorBox, LAYER_COLORS, LAYER_LABELS, Loading } from "../ui";

cytoscape.use(fcose);

const KINDS: { kind: NodeKind; label: string; color: string; shape: string }[] = [
  { kind: "file", label: "Files", color: "#64748b", shape: "round-rectangle" },
  { kind: "class", label: "Classes", color: "#8b5cf6", shape: "ellipse" },
  { kind: "function", label: "Methods & handlers", color: "#14b8a6", shape: "ellipse" },
  { kind: "endpoint", label: "Endpoints", color: "#f59e0b", shape: "round-tag" },
  { kind: "entity", label: "Data models", color: "#ef4444", shape: "diamond" },
];

const EDGE_LABELS: Record<string, string> = {
  imports: "imports",
  defines: "defines",
  has_method: "has method",
  handled_by: "handled by",
  declared_in: "declared in",
  implements: "implements",
  injects: "injects",
  relates_to: "relates to",
};

function isDark() {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

export default function GraphTab() {
  const { analysis } = useRepo();
  const [data, setData] = useState<GraphElements | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visible, setVisible] = useState<Set<NodeKind> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    api.graph(analysis.id).then(setData).catch((e) => setError(String(e.message ?? e)));
  }, [analysis.id]);

  // Methods dominate the node count on class-heavy repos; start with them hidden
  // there so the first view shows structure rather than a hairball.
  useEffect(() => {
    if (!data || visible) return;
    const kinds = new Set<NodeKind>(["file", "class", "function", "endpoint", "entity"]);
    if (data.nodes.length > 160) kinds.delete("function");
    setVisible(kinds);
  }, [data, visible]);

  const elements = useMemo<ElementDefinition[]>(() => {
    if (!data || !visible) return [];
    const keep = new Set(data.nodes.filter((n) => visible.has(n.data.kind)).map((n) => n.data.id));
    return [
      ...data.nodes.filter((n) => keep.has(n.data.id)),
      ...data.edges.filter((e) => keep.has(e.data.source) && keep.has(e.data.target)),
    ];
  }, [data, visible]);

  useEffect(() => {
    if (!container.current || elements.length === 0) return;
    const dark = isDark();
    const cy = cytoscape({
      container: container.current,
      elements,
      minZoom: 0.1,
      maxZoom: 3,
      wheelSensitivity: 0.3,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "font-size": 9,
            color: dark ? "#cbd5e1" : "#334155",
            "text-valign": "bottom",
            "text-margin-y": 3,
            "text-max-width": "110px",
            "text-wrap": "ellipsis",
            width: 14,
            height: 14,
            "border-width": 0,
          },
        },
        ...KINDS.map((k) => ({
          selector: `node[kind = "${k.kind}"]`,
          style: { "background-color": k.color, shape: k.shape as cytoscape.Css.NodeShape },
        })),
        ...Object.entries(LAYER_COLORS).map(([layer, color]) => ({
          selector: `node[kind = "file"][layer = "${layer}"]`,
          style: { "background-color": color },
        })),
        { selector: 'node[kind = "file"]', style: { width: 18, height: 12 } },
        { selector: 'node[kind = "endpoint"]', style: { width: 16, height: 12, "font-size": 8 } },
        { selector: 'node[kind = "entity"]', style: { width: 20, height: 20, "font-weight": "bold" } },
        {
          selector: "edge",
          style: {
            width: 1,
            "line-color": dark ? "#334155" : "#cbd5e1",
            "target-arrow-color": dark ? "#334155" : "#cbd5e1",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.6,
            "curve-style": "bezier",
            opacity: 0.8,
          },
        },
        { selector: 'edge[kind = "injects"]', style: { "line-color": "#8b5cf6", "target-arrow-color": "#8b5cf6", "line-style": "dashed" } },
        { selector: 'edge[kind = "relates_to"]', style: { "line-color": "#ef4444", "target-arrow-color": "#ef4444" } },
        { selector: 'edge[kind = "handled_by"], edge[kind = "declared_in"]', style: { "line-color": "#f59e0b", "target-arrow-color": "#f59e0b" } },
        { selector: ".faded", style: { opacity: 0.12 } },
        { selector: "node.highlight", style: { "border-width": 3, "border-color": "#6366f1", "font-size": 11, "z-index": 10 } },
        { selector: "edge.highlight", style: { width: 2, "line-color": "#6366f1", "target-arrow-color": "#6366f1", opacity: 1, "z-index": 10 } },
      ],
      layout: {
        name: "fcose",
        animate: false,
        quality: "default",
        randomize: true,
        nodeSeparation: 60,
        idealEdgeLength: 60,
        nodeRepulsion: 6000,
        packComponents: true,
      } as cytoscape.LayoutOptions,
    });
    cy.on("tap", "node", (e) => setSelected(e.target.id()));
    cy.on("tap", (e) => {
      if (e.target === cy) setSelected(null);
    });
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [elements]);

  // Highlight the selected node's neighbourhood.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("faded highlight");
    if (!selected) return;
    const node = cy.getElementById(selected);
    if (node.empty()) return;
    const hood = node.closedNeighborhood();
    cy.elements().not(hood).addClass("faded");
    hood.addClass("highlight");
  }, [selected, elements]);

  function search(e: React.FormEvent) {
    e.preventDefault();
    const cy = cyRef.current;
    if (!cy || !query.trim()) return;
    const q = query.trim().toLowerCase();
    const match = cy.nodes().filter((n) => {
      const label = String(n.data("label")).toLowerCase();
      const path = String(n.data("path") ?? "").toLowerCase();
      return label.includes(q) || path.includes(q);
    });
    if (match.nonempty()) {
      setSelected(match[0].id());
      cy.animate({ center: { eles: match[0] }, zoom: 1.6 }, { duration: 300 });
    }
  }

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!data || !visible) return <Loading label="Building the graph…" />;

  const counts = new Map<NodeKind, number>();
  for (const n of data.nodes) counts.set(n.data.kind, (counts.get(n.data.kind) ?? 0) + 1);
  const selectedNode = data.nodes.find((n) => n.data.id === selected);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
      <div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {KINDS.map((k) => (
            <button
              key={k.kind}
              onClick={() => {
                const next = new Set(visible);
                if (next.has(k.kind)) next.delete(k.kind);
                else next.add(k.kind);
                setVisible(next);
              }}
              disabled={!counts.get(k.kind)}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition disabled:opacity-40 ${
                visible.has(k.kind)
                  ? "border-slate-300 bg-white dark:border-slate-600 dark:bg-slate-800"
                  : "border-dashed border-slate-300 text-slate-400 dark:border-slate-700"
              }`}
            >
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: k.color, opacity: visible.has(k.kind) ? 1 : 0.3 }} />
              {k.label} <span className="tabular-nums text-slate-400">{counts.get(k.kind) ?? 0}</span>
            </button>
          ))}
          <form onSubmit={search} className="ml-auto flex gap-1">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find a node…"
              className="w-44 rounded-md border border-slate-300 px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-900"
            />
          </form>
          <button
            onClick={() => cyRef.current?.fit(undefined, 30)}
            className="rounded-md border border-slate-300 px-2 py-1 text-xs dark:border-slate-700"
          >
            Fit
          </button>
        </div>
        <div
          ref={container}
          className="h-[620px] rounded-xl border border-slate-200 bg-slate-50/50 dark:border-slate-800 dark:bg-slate-900/40"
        />
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          {elements.filter((e) => !("source" in e.data)).length} nodes shown. Scroll to zoom, drag to pan,
          click a node to see its connections. Dashed purple edges are dependency injection.
        </p>
      </div>

      <aside className="space-y-4">
        {selectedNode ? (
          <NodeDetails
            node={selectedNode.data}
            data={data}
            onSelect={setSelected}
          />
        ) : (
          <div className="rounded-xl border border-slate-200 p-4 text-sm dark:border-slate-800">
            <p className="font-medium">File colours = architectural layer</p>
            <div className="mt-3 space-y-1.5">
              {Object.entries(LAYER_LABELS)
                .filter(([l]) => data.nodes.some((n) => n.data.kind === "file" && n.data.layer === l))
                .map(([l, label]) => (
                  <div key={l} className="flex items-center gap-2 text-xs">
                    <span className="h-2.5 w-3.5 rounded-sm" style={{ background: LAYER_COLORS[l] }} />
                    {label}
                  </div>
                ))}
            </div>
            <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
              The same graph is stored in Neo4j, keyed by repository, and is what the AI summary is written from.
            </p>
          </div>
        )}
      </aside>
    </div>
  );
}

function NodeDetails({
  node,
  data,
  onSelect,
}: {
  node: GraphElements["nodes"][number]["data"];
  data: GraphElements;
  onSelect: (id: string) => void;
}) {
  const byId = new Map(data.nodes.map((n) => [n.data.id, n.data]));
  const outgoing = data.edges.filter((e) => e.data.source === node.id);
  const incoming = data.edges.filter((e) => e.data.target === node.id);
  const kind = KINDS.find((k) => k.kind === node.kind);

  const list = (edges: typeof outgoing, side: "source" | "target", heading: string) =>
    edges.length > 0 && (
      <div>
        <p className="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">{heading}</p>
        <ul className="max-h-52 space-y-1 overflow-y-auto">
          {edges.map((e) => {
            const other = byId.get(e.data[side]);
            if (!other) return null;
            return (
              <li key={e.data.id}>
                <button onClick={() => onSelect(other.id)} className="flex w-full items-baseline gap-2 text-left text-xs hover:text-indigo-600">
                  <span className="shrink-0 text-slate-400">{EDGE_LABELS[e.data.kind] ?? e.data.kind}</span>
                  <span className="truncate font-mono">{other.label}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    );

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 p-4 dark:border-slate-800">
      <div>
        <p className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-slate-500">
          <span className="h-2 w-2 rounded-full" style={{ background: kind?.color }} /> {node.kind}
          {node.layer && node.kind === "file" && ` · ${LAYER_LABELS[node.layer] ?? node.layer}`}
        </p>
        <p className="mt-1 break-all font-mono text-sm font-medium">{node.label}</p>
        {node.path && (
          <Link
            to={`../files?path=${encodeURIComponent(node.path)}`}
            className="mt-1 block break-all text-xs text-indigo-700 hover:underline dark:text-indigo-300"
          >
            {node.path} →
          </Link>
        )}
      </div>
      {list(outgoing, "target", `Outgoing (${outgoing.length})`)}
      {list(incoming, "source", `Incoming (${incoming.length})`)}
    </div>
  );
}
