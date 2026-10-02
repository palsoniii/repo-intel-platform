import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import cytoscape, { type ElementDefinition } from "cytoscape";
import type { Architecture } from "../lib/product";
import { token, useResolvedTheme } from "../lib/theme";
import { LAYER_GROUPS, layerGroup } from "./ui";

const COL_WIDTH = 216;
const ROW_HEIGHT = 36;

// Swimlanes: one row per layer group, top to bottom in request order (setup ->
// routes -> middleware -> services -> data), files wrapping to the container's
// width so the diagram renders close to 1:1. A fixed layout rather than a force
// layout, so it reads like an architecture diagram and is the same every time.
export default function LayeredArchitecture({ graph }: { graph: Architecture["layered"]["graph"] }) {
  const container = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const theme = useResolvedTheme();

  useEffect(() => {
    if (!container.current) return;
    const color = (g: string) => token(`layer-${g}`);
    const ink = token("ink");
    const ink2 = token("ink-2");
    const surface = token("surface");
    const line = token("line-strong");
    const accent = token("accent");

    const width = Math.max(600, container.current.clientWidth - 64);
    const perRow = Math.max(1, Math.floor(width / COL_WIDTH));
    const elements: ElementDefinition[] = [];
    let y = 0;
    for (const g of LAYER_GROUPS) {
      const members = graph.nodes.filter((n) => layerGroup(n.layer) === g.id);
      if (members.length === 0) continue;
      const cols = Math.min(perRow, members.length);
      const offset = ((perRow - cols) * COL_WIDTH) / 2;
      elements.push({ data: { id: `lane:${g.id}`, label: g.label.toUpperCase(), lane: g.id } });
      members.forEach((n, i) => {
        elements.push({
          data: {
            id: n.id,
            parent: `lane:${g.id}`,
            label: n.files > 1 ? `${n.label}  ·  ${n.files}` : n.label,
            group: g.id,
            path: n.path,
          },
          position: { x: offset + (i % perRow) * COL_WIDTH, y: y + Math.floor(i / perRow) * ROW_HEIGHT },
        });
      });
      y += Math.ceil(members.length / perRow) * ROW_HEIGHT + 72;
    }
    for (const l of graph.links) {
      elements.push({ data: { id: `${l.source}->${l.target}`, source: l.source, target: l.target, count: l.count } });
    }
    container.current.style.height = `${Math.min(920, Math.max(320, y + 24))}px`;

    const cy = cytoscape({
      container: container.current,
      elements,
      layout: { name: "preset", padding: 28 },
      minZoom: 0.15,
      maxZoom: 2.5,
      wheelSensitivity: 0.3,
      autoungrabify: true,
      style: [
        {
          selector: "node[lane]",
          style: {
            label: "data(label)",
            "text-valign": "top",
            "text-halign": "center",
            "font-size": 10,
            "font-weight": 600,
            color: ink2,
            "text-margin-y": -8,
            "background-opacity": 0.05,
            "border-width": 1,
            "border-opacity": 0.35,
            shape: "round-rectangle",
            padding: "16px",
            "font-family": "ui-sans-serif, system-ui, sans-serif",
          },
        },
        ...LAYER_GROUPS.map((g) => ({
          selector: `node[lane = "${g.id}"]`,
          style: { "background-color": color(g.id), "border-color": color(g.id) },
        })),
        {
          selector: "node[group]",
          style: {
            label: "data(label)",
            shape: "round-rectangle",
            width: 196,
            height: 26,
            "font-size": 10.5,
            "font-family": "ui-monospace, 'SF Mono', Menlo, monospace",
            "text-valign": "center",
            "text-halign": "center",
            "text-max-width": "180px",
            "text-wrap": "ellipsis",
            color: ink,
            "background-color": surface,
            "border-width": 1,
            "border-color": line,
          },
        },
        ...LAYER_GROUPS.map((g) => ({
          selector: `node[group = "${g.id}"]`,
          style: { "border-color": color(g.id) },
        })),
        {
          selector: "edge",
          style: {
            width: "mapData(count, 1, 10, 1, 3.5)",
            "curve-style": "bezier",
            "line-color": line,
            "target-arrow-color": line,
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.7,
            opacity: 0.45,
          },
        },
        { selector: ".faded", style: { opacity: 0.1 } },
        { selector: "edge.hl", style: { opacity: 1, "line-color": accent, "target-arrow-color": accent, width: 2, "z-index": 9 } },
        { selector: "node.hl[group]", style: { "border-width": 2 } },
      ],
    });

    cy.on("mouseover", "node[group]", (e) => {
      const hood = e.target.closedNeighborhood();
      cy.elements("node[group], edge").not(hood).addClass("faded");
      hood.addClass("hl");
      if (container.current) container.current.style.cursor = e.target.data("path") ? "pointer" : "default";
    });
    cy.on("mouseout", "node[group]", () => {
      cy.elements().removeClass("faded hl");
      if (container.current) container.current.style.cursor = "default";
    });
    cy.on("tap", "node[group]", (e) => {
      const path = e.target.data("path");
      if (path) navigate(`../files?path=${encodeURIComponent(path)}`);
    });
    cy.fit(undefined, 28);
    return () => cy.destroy();
  }, [graph, navigate, theme]);

  return <div ref={container} className="rounded-xl bg-sunken" style={{ height: 480 }} />;
}
