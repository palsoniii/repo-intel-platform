// Light/dark theme: the viewer's explicit choice wins, otherwise the OS setting.
// Applied as <html data-theme>, which index.css's tokens and Tailwind's dark
// variant both key off. Graph and diagram renderers read it via isDark().

import { useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";
const KEY = "repointel-theme";

function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    // storage unavailable (private mode): fall through to system
  }
  return "system";
}

function resolve(choice: ThemeChoice): "light" | "dark" {
  if (choice !== "system") return choice;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(choice: ThemeChoice = readChoice()) {
  document.documentElement.dataset.theme = resolve(choice);
}

export function isDark(): boolean {
  return document.documentElement.dataset.theme === "dark";
}

export function useTheme(): [ThemeChoice, (c: ThemeChoice) => void, "light" | "dark"] {
  const [choice, setChoice] = useState<ThemeChoice>(readChoice);
  const [resolved, setResolved] = useState<"light" | "dark">(() => resolve(readChoice()));

  useEffect(() => {
    applyTheme(choice);
    setResolved(resolve(choice));
    try {
      localStorage.setItem(KEY, choice);
    } catch {
      // ignore
    }
    if (choice !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      applyTheme("system");
      setResolved(resolve("system"));
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [choice]);

  return [choice, setChoice, resolved];
}

// Renderers that bake colours into a canvas/SVG (Cytoscape, Mermaid) need to know
// when to redraw.
export function useResolvedTheme(): "light" | "dark" {
  const [t, setT] = useState<"light" | "dark">(() => (isDark() ? "dark" : "light"));
  useEffect(() => {
    const obs = new MutationObserver(() => setT(isDark() ? "dark" : "light"));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return t;
}

// Reads a token's current value (for canvas renderers that can't use CSS vars).
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
}
