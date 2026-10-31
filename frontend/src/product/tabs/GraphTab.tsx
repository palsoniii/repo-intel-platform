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

// Colour of each relationship. Structural links (defines, has method) stay quiet so
// the dependencies between things stand out.
const EDGE_STYLES: { kinds: string[]; label: string; color: string; dashed?: boolean }[] = [
  { kinds: ["imports"], label: "Imports", color: "muted" },
  { kinds: ["injects"], label: "Injects (dependency injection)", color: "accent", dashed: true },
  { kinds: ["handled_by"], label: "Endpoint → handler", color: "layer-route" },
  { kinds: ["relates_to"], label: "Data model relation", color: "layer-data" },
  { kinds: ["implements"], label: "Implements", color: "layer-middleware" },
  { kinds: ["defines", "has_method", "declared_in"], label: "Defines / has method", color: "line-strong" },
];

// Folders that hold features rather than being one (src/modules/auth -> auth).
const CONTAINER_DIRS = new Set(["src", "app", "lib", "libs", "modules", "module", "features", "feature", "api", "server", "source"]);

function featureOf(path: string | undefined): string | null {
  if (!path) return null;
  const dirs = path.split("/").slice(0, -1);
  while (dirs.length && CONTAINER_DIRS.has(dirs[0].toLowerCase())) dirs.shift();
  return dirs[0] ?? null;
}

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

    // Each node joins the cluster of its feature folder. Endpoints have no file of
    // their own, so they join their handler's (even when methods are hidden).
    const pathOf = new Map(data.nodes.map((n) => [n.data.id, n.data.path]));
    const handler = new Map(data.edges.filter((e) => e.data.kind === "handled_by").map((e) => [e.data.source, e.data.target]));
    const feature = new Map<string, string | null>();
    for (const n of data.nodes) {
      const path = n.data.path ?? pathOf.get(handler.get(n.data.id) ?? "");
      feature.set(n.data.id, featureOf(path));
    }
    const sizes = new Map<string, number>();
    for (const id of keep) {
      const f = feature.get(id);
      if (f) sizes.set(f, (sizes.get(f) ?? 0) + 1);
    }
    // A box around a single node is noise.
    const clusters = [...sizes].filter(([, size]) => size > 1).map(([f]) => f);
    const clustered = new Set(clusters);

    return [
      ...clusters.map((f) => ({ data: { id: `cluster:${f}`, label: f, kind: "cluster" } })),
      ...data.nodes
        .filter((n) => keep.has(n.data.id))
        .map((n) => {
          const f = feature.get(n.data.id);
          return {
            data: { ...n.data, group: layerGroup(n.data.layer), parent: f && clustered.has(f) ? `cluster:${f}` : undefined },
          };
        }),
      ...data.edges
        .filter((e) => keep.has(e.data.source) && keep.has(e.data.target))
        .map((e) => ({ data: { ...e.data, cross: feature.get(e.data.source) !== feature.get(e.data.target) } })),
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
          selector: 'node[kind = "cluster"]',
          style: {
            shape: "round-rectangle",
            label: "data(label)",
            "text-valign": "top",
            "text-halign": "center",
            "text-margin-y": -8,
            // Readable at the zoom that fits the whole graph, where node labels hide.
            "font-size": 26,
            "min-zoomed-font-size": 0,
            "font-weight": 600,
            color: token("ink"),
            "text-max-width": "400px",
            "background-color": token("surface"),
            "background-opacity": 0.85,
            "border-width": 1,
            "border-color": token("line-strong"),
            padding: "18px",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.4,
            "line-color": line,
            "target-arrow-color": line,
            "target-arrow-shape": "triangle",
            "arrow-scale": 1.1,
            "curve-style": "bezier",
            opacity: 0.75,
          },
        },
        ...EDGE_STYLES.flatMap((s) =>
          s.kinds.map((kind) => ({
            selector: `edge[kind = "${kind}"]`,
            style: {
              "line-color": token(s.color),
              "target-arrow-color": token(s.color),
              ...(s.dashed ? { "line-style": "dashed" as const, width: 1.8, opacity: 0.95 } : {}),
            },
          })),
        ),
        { selector: 'edge[kind = "defines"], edge[kind = "has_method"], edge[kind = "declared_in"]', style: { width: 1, "arrow-scale": 0.8 } },
        // Links between features are many and long; quiet until a node is selected.
        { selector: "edge[?cross]", style: { opacity: 0.22 } },
        { selector: ".faded", style: { opacity: 0.1 } },
        { selector: "node.hl", style: { "border-color": accent, "border-width": 3, "font-size": 11, color: token("ink"), "z-index": 10 } },
        // Highlighted edges keep their relationship colour, just stronger.
        { selector: "edge.hl", style: { width: 2.6, "arrow-scale": 1.3, opacity: 1, "z-index": 10 } },
      ],
      layout: { name: "preset" },
    });
    layoutByFeature(cy);
    cy.fit(undefined, 30);
    cy.on("tap", "node[kind != 'cluster']", (e) => setSelected(e.target.id()));
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
    // Not the cluster boxes: a compound's opacity also fades everything inside it.
    cy.elements().not(hood).not('node[kind = "cluster"]').addClass("faded");
    hood.addClass("hl");
  }, [selected, elements, theme]);

  function search(q: string) {
    setQuery(q);
    const cy = cyRef.current;
    const needle = q.trim().toLowerCase();
    if (!cy || needle.length < 2) return;
    const match = cy.nodes('[kind != "cluster"]').filter((n) => {
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
  const presentEdges = new Set(data.edges.map((e) => e.data.kind));

  return (
    <div>
      <PageHeader
        title="Knowledge graph"
        description="Every file, class, endpoint and data model, grouped by feature folder, and how they connect. This is the graph the AI summary is written from. Click anything to see its connections."
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
                Boxes are feature folders. A node's colour shows its layer, its shape what it is, and a
                line's colour the kind of link. Links between features are faint until you click a node.
                Arrows point from the thing that depends to what it uses.
              </p>
              <div className="mt-4 space-y-2">
                {LAYER_GROUPS.filter((g) => presentGroups.has(g.id)).map((g) => (
                  <div key={g.id} className="flex items-center gap-2 text-xs text-ink-2">
                    <LayerDot group={g.id} /> {g.label}
                  </div>
                ))}
              </div>
              <div className="mt-4 space-y-2 border-t border-line pt-4">
                {EDGE_STYLES.filter((s) => s.kinds.some((k) => presentEdges.has(k))).map((s) => (
                  <div key={s.label} className="flex items-center gap-2 text-xs text-ink-2">
                    <EdgeGlyph color={s.color} dashed={s.dashed} />
                    {s.label}
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

type Box = { nodes: cytoscape.NodeCollection; bb: cytoscape.BoundingBox12 & cytoscape.BoundingBoxWH };

// Lays out each feature cluster on its own, then places the clusters. One force
// layout over everything lets cross-feature imports drag the boxes over each other;
// separately, each box is tidy and none overlap. Unclustered nodes (root files,
// one-node features) form one more group, without a box.
function layoutByFeature(cy: Core) {
  const groups: cytoscape.NodeCollection[] = [];
  cy.nodes('[kind = "cluster"]').forEach((c) => {
    groups.push(c.children());
  });
  const loose = cy.nodes('[kind != "cluster"]').filter((n) => !n.isChild());
  if (loose.nonempty()) groups.push(loose);

  const boxes: Box[] = groups.map((nodes) => {
    nodes
      .union(nodes.edgesWith(nodes))
      .layout({
        name: nodes.length > 2 ? "fcose" : "grid",
        animate: false,
        randomize: true,
        quality: "default",
        nodeSeparation: 60,
        idealEdgeLength: 55,
        nodeRepulsion: 5000,
        packComponents: true,
        fit: false,
      } as cytoscape.LayoutOptions)
      .run();
    return { nodes, bb: nodes.boundingBox({ includeLabels: true }) };
  });
  placeGroups(cy, boxes);
}

// Places the groups so features that link to each other sit side by side: a force
// layout over one node per group (sized to its box, edges weighted by the links
// between groups), then a pass that pushes apart any boxes still overlapping.
function placeGroups(cy: Core, boxes: Box[]) {
  const GAP = 60;
  const groupOf = new Map<string, number>();
  boxes.forEach((b, i) => b.nodes.forEach((n) => void groupOf.set(n.id(), i)));
  const weights = new Map<string, number>();
  cy.edges().forEach((e) => {
    const a = groupOf.get(e.source().id());
    const b = groupOf.get(e.target().id());
    if (a === undefined || b === undefined || a === b) return;
    const key = a < b ? `${a}-${b}` : `${b}-${a}`;
    weights.set(key, (weights.get(key) ?? 0) + 1);
  });

  const meta = cytoscape({
    headless: true,
    styleEnabled: true,
    elements: [
      ...boxes.map((b, i) => ({ data: { id: `g${i}`, w: b.bb.w + GAP, h: b.bb.h + GAP } })),
      ...[...weights].map(([key, weight]) => {
        const [a, b] = key.split("-");
        return { data: { id: `m${key}`, source: `g${a}`, target: `g${b}`, weight } };
      }),
    ],
    style: [{ selector: "node", style: { width: "data(w)", height: "data(h)", shape: "rectangle" } }],
  });
  meta
    .layout({
      name: "fcose",
      animate: false,
      randomize: true,
      quality: "proof",
      nodeSeparation: GAP,
      idealEdgeLength: (e: cytoscape.EdgeSingular) => 120 / Math.sqrt(e.data("weight")),
      edgeElasticity: (e: cytoscape.EdgeSingular) => Math.min(0.9, 0.3 + 0.05 * e.data("weight")),
      nodeRepulsion: 40000,
      packComponents: true,
      fit: false,
    } as unknown as cytoscape.LayoutOptions)
    .run();

  // Centre of each group's box, then nudge apart whatever still overlaps.
  const centres = boxes.map((b, i) => ({ ...meta.getElementById(`g${i}`).position(), w: b.bb.w + GAP, h: b.bb.h + GAP }));
  meta.destroy();
  for (let pass = 0; pass < 300; pass++) {
    let moved = false;
    for (let i = 0; i < centres.length; i++) {
      for (let j = i + 1; j < centres.length; j++) {
        const a = centres[i];
        const b = centres[j];
        const ox = (a.w + b.w) / 2 - Math.abs(a.x - b.x);
        const oy = (a.h + b.h) / 2 - Math.abs(a.y - b.y);
        if (ox <= 0 || oy <= 0) continue;
        moved = true;
        // Separate along the axis that needs the smaller move.
        if (ox < oy) {
          const d = (ox / 2 + 1) * (a.x <= b.x ? -1 : 1);
          a.x += d;
          b.x -= d;
        } else {
          const d = (oy / 2 + 1) * (a.y <= b.y ? -1 : 1);
          a.y += d;
          b.y -= d;
        }
      }
    }
    if (!moved) break;
  }

  boxes.forEach(({ nodes, bb }, i) => {
    const dx = centres[i].x - (bb.x1 + bb.w / 2);
    const dy = centres[i].y - (bb.y1 + bb.h / 2);
    nodes.positions((n) => ({ x: n.position("x") + dx, y: n.position("y") + dy }));
  });
}

function EdgeGlyph({ color, dashed }: { color: string; dashed?: boolean }) {
  return (
    <svg viewBox="0 0 24 10" className="h-2.5 w-6 shrink-0" aria-hidden="true" style={{ color: `var(--${color})` }}>
      <line x1="1" y1="5" x2="16" y2="5" stroke="currentColor" strokeWidth="1.8" strokeDasharray={dashed ? "3 2" : undefined} />
      <path d="M15 1l8 4-8 4z" fill="currentColor" />
    </svg>
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
