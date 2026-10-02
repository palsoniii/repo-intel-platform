import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import cytoscape, { type ElementDefinition } from "cytoscape";
import type { Architecture } from "../lib/product";
import { LAYER_COLORS, LAYER_LABELS } from "./ui";

const COL_WIDTH = 230;
const ROW_HEIGHT = 34;

// Swimlanes: one column per layer, left to right in request order (entry -> routes
// -> services -> data), files stacked inside, imports drawn between them. A fixed
// layout rather than a force layout, so the picture reads like an architecture
// diagram and is the same every time.
export default function LayeredArchitecture({ graph }: { graph: Architecture["layered"]["graph"] }) {
  const container = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!container.current) return;
    const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
    const lanes: string[] = [];
    for (const n of graph.nodes) if (!lanes.includes(n.layer)) lanes.push(n.layer);

    // Lanes run top to bottom (entry points first, data last); inside a lane, files
    // wrap to the container's width so the diagram renders close to 1:1.
    const width = Math.max(600, container.current.clientWidth - 80);
    const perRow = Math.max(1, Math.floor(width / COL_WIDTH));
    const elements: ElementDefinition[] = [];
    let y = 0;
    for (const lane of lanes) {
      const members = graph.nodes.filter((n) => n.layer === lane);
      const cols = Math.min(perRow, members.length);
      const offset = ((perRow - cols) * COL_WIDTH) / 2;
      elements.push({ data: { id: `lane:${lane}`, label: LAYER_LABELS[lane] ?? lane, lane } });
      members.forEach((n, i) => {
        elements.push({
          data: {
            id: n.id,
            parent: `lane:${lane}`,
            label: n.files > 1 ? `${n.label}  (${n.files})` : n.label,
            layer: lane,
            path: n.path,
            title: n.title,
          },
          position: { x: offset + (i % perRow) * COL_WIDTH, y: y + Math.floor(i / perRow) * ROW_HEIGHT },
        });
      });
      y += Math.ceil(members.length / perRow) * ROW_HEIGHT + 64;
    }
    container.current.style.height = `${Math.min(900, Math.max(320, y + 40))}px`;
    for (const l of graph.links) {
      elements.push({ data: { id: `${l.source}->${l.target}`, source: l.source, target: l.target, count: l.count } });
    }

    const ink = dark ? "#e2e8f0" : "#1e293b";
    const cy = cytoscape({
      container: container.current,
      elements,
      layout: { name: "preset", padding: 24 },
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
            "font-size": 12,
            "font-weight": "bold",
            color: ink,
            "text-margin-y": -6,
            "background-opacity": 0.07,
            "border-width": 1,
            "border-style": "dashed",
            "border-opacity": 0.6,
            shape: "round-rectangle",
            padding: "14px",
          },
        },
        ...Object.entries(LAYER_COLORS).map(([layer, color]) => ({
          selector: `node[lane = "${layer}"]`,
          style: { "background-color": color, "border-color": color },
        })),
        {
          selector: "node[layer]",
          style: {
            label: "data(label)",
            shape: "round-rectangle",
            width: 200,
            height: 24,
            "font-size": 10.5,
            "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
            "text-valign": "center",
            "text-halign": "center",
            "text-max-width": "188px",
            "text-wrap": "ellipsis",
            color: ink,
            "background-color": dark ? "#0f172a" : "#ffffff",
            "border-width": 1.5,
          },
        },
        ...Object.entries(LAYER_COLORS).map(([layer, color]) => ({
          selector: `node[layer = "${layer}"]`,
          style: { "border-color": color },
        })),
        {
          selector: "edge",
          style: {
            width: "mapData(count, 1, 10, 1, 4)",
            "curve-style": "bezier",
            "line-color": dark ? "#475569" : "#94a3b8",
            "target-arrow-color": dark ? "#475569" : "#94a3b8",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.7,
            opacity: 0.35,
          },
        },
        { selector: ".faded", style: { opacity: 0.08 } },
        { selector: "edge.hl", style: { opacity: 1, "line-color": "#6366f1", "target-arrow-color": "#6366f1", "z-index": 9 } },
        { selector: "node.hl", style: { "border-width": 2.5, "background-color": dark ? "#1e1b4b" : "#eef2ff" } },
      ],
    });

    cy.on("mouseover", "node[layer]", (e) => {
      const n = e.target;
      const hood = n.closedNeighborhood();
      cy.elements("node[layer], edge").not(hood).addClass("faded");
      hood.addClass("hl");
    });
    cy.on("mouseout", "node[layer]", () => cy.elements().removeClass("faded hl"));
    cy.on("tap", "node[layer]", (e) => {
      const path = e.target.data("path");
      if (path) navigate(`../files?path=${encodeURIComponent(path)}`);
    });
    cy.fit(undefined, 24);
    return () => cy.destroy();
  }, [graph, navigate]);

  return (
    <div
      ref={container}
      className="rounded-lg border border-slate-200 bg-slate-50/40 dark:border-slate-800 dark:bg-slate-900/30"
      style={{ height: 480 }}
    />
  );
}
