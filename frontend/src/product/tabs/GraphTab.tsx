import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import fcose from "cytoscape-fcose";
import { api, type GraphElements, type NodeKind } from "../../lib/product";
import { token, useResolvedTheme } from "../../lib/theme";
import { useRepo } from "../RepoLayout";
import { Button, ErrorBox, Icon, LAYER_GROUPS, LayerDot, Loading, PageHeader, SearchInput, groupLabel, layerGroup } from "../ui";

cytoscape.use(fcose);

// Colour = architectural layer (same as every other view). Shape = what the node is.
const KINDS: { kind: NodeKind; label: string; shape: cytoscape.Css.NodeShape; size: [number, number] }[] = [
  { kind: "file", label: "Files", shape: "round-rectangle", size: [20, 13] },
  { kind: "class", label: "Classes", shape: "ellipse", size: [15, 15] },
  { kind: "function", label: "Methods", shape: "ellipse", size: [8, 8] },
  { kind: "endpoint", label: "Endpoints", shape: "round-tag", size: [16, 12] },
  { kind: "entity", label: "Data models", shape: "diamond", size: [20, 20] },
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

function ShapeGlyph({ kind }: { kind: NodeKind }) {
  const common = { fill: "currentColor" };
  return (
    <svg viewBox="0 0 16 16" className="h-3 w-3" aria-hidden="true">
      {kind === "file" && <rect x="1" y="4" width="14" height="8" rx="2" {...common} />}
      {kind === "class" && <circle cx="8" cy="8" r="6" {...common} />}
      {kind === "function" && <circle cx="8" cy="8" r="3.5" {...common} />}
      {kind === "endpoint" && <path d="M2 4h9l3 4-3 4H2z" {...common} />}
      {kind === "entity" && <path d="M8 1l7 7-7 7-7-7z" {...common} />}
    </svg>
  );
}

export default function GraphTab() {
  const { analysis } = useRepo();
  const theme = useResolvedTheme();
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
      ...data.nodes.filter((n) => keep.has(n.data.id)).map((n) => ({ data: { ...n.data, group: layerGroup(n.data.layer) } })),
      ...data.edges.filter((e) => keep.has(e.data.source) && keep.has(e.data.target)),
    ];
  }, [data, visible]);

  useEffect(() => {
    if (!container.current || elements.length === 0) return;
    const line = token("line-strong");
    const accent = token("accent");
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
            "font-family": "ui-sans-serif, system-ui, sans-serif",
            color: token("ink-2"),
            "text-valign": "bottom",
            "text-margin-y": 4,
            "text-max-width": "110px",
            "text-wrap": "ellipsis",
            "border-width": 2,
            "border-color": token("surface"),
            "min-zoomed-font-size": 7,
          },
        },
        ...KINDS.map((k) => ({
          selector: `node[kind = "${k.kind}"]`,
          style: { shape: k.shape, width: k.size[0], height: k.size[1] },
        })),
        ...LAYER_GROUPS.map((g) => ({
          selector: `node[group = "${g.id}"]`,
          style: { "background-color": token(`layer-${g.id}`) },
        })),
        { selector: 'node[kind = "entity"], node[kind = "class"]', style: { "font-weight": 600, color: token("ink") } },
        {
          selector: "edge",
          style: {
            width: 1,
            "line-color": line,
            "target-arrow-color": line,
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.55,
            "curve-style": "bezier",
            opacity: 0.6,
          },
        },
        { selector: 'edge[kind = "injects"]', style: { "line-style": "dashed", width: 1.5, opacity: 0.9 } },
        { selector: ".faded", style: { opacity: 0.1 } },
        { selector: "node.hl", style: { "border-color": accent, "border-width": 3, "font-size": 11, color: token("ink"), "z-index": 10 } },
        { selector: "edge.hl", style: { width: 2, "line-color": accent, "target-arrow-color": accent, opacity: 1, "z-index": 10 } },
      ],
      layout: {
        name: "fcose",
        animate: false,
        quality: "default",
        randomize: true,
        nodeSeparation: 70,
        idealEdgeLength: 64,
        nodeRepulsion: 6500,
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
  }, [elements, theme]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("faded hl");
    if (!selected) return;
    const node = cy.getElementById(selected);
    if (node.empty()) return;
    const hood = node.closedNeighborhood();
    cy.elements().not(hood).addClass("faded");
    hood.addClass("hl");
  }, [selected, elements, theme]);

  function search(q: string) {
    setQuery(q);
    const cy = cyRef.current;
    const needle = q.trim().toLowerCase();
    if (!cy || needle.length < 2) return;
    const match = cy.nodes().filter((n) => {
      const label = String(n.data("label")).toLowerCase();
      const path = String(n.data("path") ?? "").toLowerCase();
      return label.includes(needle) || path.includes(needle);
    });
    if (match.nonempty()) {
      setSelected(match[0].id());
      cy.animate({ center: { eles: match[0] }, zoom: 1.6 }, { duration: 250 });
    }
  }

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!data || !visible) return <Loading label="Building the graph…" />;

  const counts = new Map<NodeKind, number>();
  for (const n of data.nodes) counts.set(n.data.kind, (counts.get(n.data.kind) ?? 0) + 1);
  const selectedNode = data.nodes.find((n) => n.data.id === selected);
  const presentGroups = new Set(data.nodes.map((n) => layerGroup(n.data.layer)));

  return (
    <div>
      <PageHeader
        title="Knowledge graph"
        description="Every file, class, endpoint and data model, and how they connect. This is the graph the AI summary is written from. Click anything to see its connections."
      />
      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <div className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {KINDS.map((k) => {
              const on = visible.has(k.kind);
              return (
                <button
                  key={k.kind}
                  onClick={() => {
                    const next = new Set(visible);
                    if (next.has(k.kind)) next.delete(k.kind);
                    else next.add(k.kind);
                    setVisible(next);
                  }}
                  disabled={!counts.get(k.kind)}
                  aria-pressed={on}
                  className={`flex h-8 items-center gap-2 rounded-lg border px-3 text-xs font-medium transition disabled:opacity-40 ${
                    on ? "border-line-strong bg-surface text-ink shadow-card" : "border-dashed border-line text-muted"
                  }`}
                >
                  <span className={on ? "text-ink-2" : "text-muted"}>
                    <ShapeGlyph kind={k.kind} />
                  </span>
                  {k.label}
                  <span className="tabular-nums text-muted">{counts.get(k.kind) ?? 0}</span>
                </button>
              );
            })}
            <div className="ml-auto flex items-center gap-2">
              <SearchInput value={query} onChange={search} placeholder="Find a node" className="w-48" />
              <Button variant="secondary" onClick={() => cyRef.current?.fit(undefined, 30)} title="Fit to screen">
                <Icon name="fit" className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <div ref={container} className="h-[640px] rounded-2xl border border-line bg-sunken" />
        </div>

        <aside>
          {selectedNode ? (
            <NodeDetails node={selectedNode.data} data={data} onSelect={setSelected} />
          ) : (
            <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">
              <p className="text-sm font-semibold text-ink">Reading the graph</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-2">
                Colour shows which layer something belongs to; shape shows what it is. Dashed lines are
                dependency injection.
              </p>
              <div className="mt-4 space-y-2">
                {LAYER_GROUPS.filter((g) => presentGroups.has(g.id)).map((g) => (
                  <div key={g.id} className="flex items-center gap-2 text-xs text-ink-2">
                    <LayerDot group={g.id} /> {g.label}
                  </div>
                ))}
              </div>
              <div className="mt-4 space-y-2 border-t border-line pt-4">
                {KINDS.map((k) => (
                  <div key={k.kind} className="flex items-center gap-2 text-xs text-ink-2">
                    <span className="text-muted">
                      <ShapeGlyph kind={k.kind} />
                    </span>
                    {k.label}
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>
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
  const group = layerGroup(node.layer);

  const list = (edges: typeof outgoing, side: "source" | "target", heading: string) =>
    edges.length > 0 && (
      <div>
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">{heading}</p>
        <ul className="scroll-quiet max-h-56 space-y-0.5 overflow-y-auto">
          {edges.map((e) => {
            const other = byId.get(e.data[side]);
            if (!other) return null;
            return (
              <li key={e.data.id}>
                <button
                  onClick={() => onSelect(other.id)}
                  className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-xs transition hover:bg-hover"
                >
                  <LayerDot raw={other.layer} className="h-1.5 w-1.5" />
                  <span className="truncate font-mono text-ink">{other.label}</span>
                  <span className="ml-auto shrink-0 text-muted">{EDGE_LABELS[e.data.kind] ?? e.data.kind}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    );

  return (
    <div className="animate-in space-y-5 rounded-2xl border border-line bg-surface p-5 shadow-card">
      <div>
        <p className="flex items-center gap-2 text-xs text-muted">
          <LayerDot group={group} className="h-2 w-2" />
          {kind?.label.replace(/s$/, "")} · {groupLabel(group)}
        </p>
        <p className="mt-1.5 break-all font-mono text-[15px] font-semibold text-ink">{node.label}</p>
        {node.path && (
          <Link
            to={`../files?path=${encodeURIComponent(node.path)}`}
            className="mt-2 inline-flex items-center gap-1 break-all text-xs text-accent-text hover:underline"
          >
            {node.path} <Icon name="arrow" className="h-3 w-3" />
          </Link>
        )}
      </div>
      {list(outgoing, "target", `Uses (${outgoing.length})`)}
      {list(incoming, "source", `Used by (${incoming.length})`)}
    </div>
  );
}
