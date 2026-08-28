"""T8 figures. All from data already on disk -- no GPU, no judge runs needed.

fig1_bimodality.png  -- the mistral missing_facts distribution: the cliff that shows
                        format bail-out rather than leniency.
fig2_heatmap.png     -- per-repo 9-cell coverage under mistral vs the oracle. The six
                        all-1.00 repos are the visual proof the metric was not measuring
                        the summaries.
fig3_pareto.png      -- coverage vs input tokens, latency as point size.
fig4_judge_scatter.png -- judge vs oracle, one panel per judge.
"""
from __future__ import annotations

import json
import os
import sqlite3

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

R = "/app/evaluation_results"
OUT = os.path.join(R, "figures")
os.makedirs(OUT, exist_ok=True)

VAR = ["raw", "dependency_graph", "knowledge_graph"]
COL = {"raw": "#c44536", "dependency_graph": "#2a6f97", "knowledge_graph": "#1b998b"}
SHORT = {"raw": "raw", "dependency_graph": "dep_graph", "knowledge_graph": "know_graph"}


def load_v2():
    c = sqlite3.connect(os.path.join(R, "battery_v2.db"))
    df = pd.read_sql_query("SELECT * FROM evaluation_runs WHERE run_status='success'", c)
    c.close()
    return df


def load_oracle():
    return pd.read_csv(os.path.join(R, "oracle_scores.csv"))


def load_rejudge(slug):
    p = os.path.join(R, "rejudge_%s.db" % slug)
    if not os.path.exists(p):
        return None
    c = sqlite3.connect(p)
    try:
        df = pd.read_sql_query("SELECT * FROM rejudged WHERE coverage_judged='1'", c)
    except Exception:
        df = None
    c.close()
    if df is not None and len(df):
        for k in ("coverage_score", "unmatched_verdict_items"):
            df[k] = pd.to_numeric(df[k], errors="coerce")
    return df


# ------------------------------------------------------------------ fig 1
def fig_bimodality(v2):
    m = pd.to_numeric(v2["missing_facts"], errors="coerce").dropna()
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.hist(m, bins=np.arange(0, m.max() + 4, 3), color="#c44536",
            edgecolor="white", linewidth=0.6)
    ax.set_xlabel("missing facts reported by the judge (mistral:7b-instruct)")
    ax.set_ylabel("number of summaries")
    ax.set_title("The judge either flags nothing or flags forty-plus\n"
                 "A lenient grader gives a smooth curve; this is a bail-out cliff",
                 fontsize=10.5, loc="left")
    n0 = int((m == 0).sum())
    ax.annotate("%d of %d summaries\nreport ZERO missing facts" % (n0, len(m)),
                xy=(1.2, n0), xytext=(24, n0 * 0.78), fontsize=9,
                arrowprops=dict(arrowstyle="->", color="#333", lw=1.1))
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig1_bimodality.png"), dpi=200)
    plt.close(fig)
    print("  fig1_bimodality.png")


# ------------------------------------------------------------------ fig 2
def fig_heatmap(v2, orc):
    def grid(df, val, jcol=None):
        d = df.copy()
        if jcol:
            d = d[d[jcol] == "1"] if d[jcol].dtype == object else d
        p = d.pivot_table(index="repo_name", columns=["model", "context_variant"],
                          values=val, aggfunc="mean")
        return p

    gm = grid(v2.assign(cs=pd.to_numeric(v2["coverage_score"], errors="coerce")), "cs")
    go = grid(orc, "oracle_coverage_strict")
    order = go.mean(axis=1).sort_values().index
    gm, go = gm.reindex(order), go.reindex(order)

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.4), sharey=True)
    for ax, g, title in [(axes[0], gm, "mistral:7b-instruct  (LLM judge)"),
                         (axes[1], go, "oracle  (deterministic)")]:
        im = ax.imshow(g.values, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
        ax.set_xticks(range(g.shape[1]))
        ax.set_xticklabels(["%s\n%s" % (m.split(":")[0][:9], SHORT.get(v, v))
                            for m, v in g.columns], fontsize=6.6, rotation=0)
        ax.set_title(title, fontsize=11)
        for i in range(g.shape[0]):
            for j in range(g.shape[1]):
                val = g.values[i, j]
                if not np.isnan(val):
                    ax.text(j, i, "%.2f" % val, ha="center", va="center", fontsize=5.6,
                            color="#111")
    axes[0].set_yticks(range(len(order)))
    axes[0].set_yticklabels([r[:34] for r in order], fontsize=7.2)
    fig.colorbar(im, ax=axes, fraction=0.02, pad=0.02, label="coverage")
    fig.suptitle("Same 157 summaries. Left: six repos score 1.00 in ALL NINE cells across "
                 "3 writers x 3 representations.\nRight: the deterministic oracle on the "
                 "identical summaries.", fontsize=10.5, x=0.01, ha="left")
    fig.savefig(os.path.join(OUT, "fig2_heatmap.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  fig2_heatmap.png")


# ------------------------------------------------------------------ fig 3
def fig_pareto(orc):
    fig, ax = plt.subplots(figsize=(7.6, 5.0))
    for v in VAR:
        d = orc[orc["context_variant"] == v]
        ax.scatter(d["input_tokens"], d["oracle_coverage_strict"],
                   s=d["latency_ms"] / 1400.0, alpha=0.55, color=COL[v],
                   edgecolor="white", linewidth=0.5, label=SHORT[v])
        ax.scatter([d["input_tokens"].mean()], [d["oracle_coverage_strict"].mean()],
                   marker="X", s=190, color=COL[v], edgecolor="black", linewidth=1.3,
                   zorder=5)
    ax.set_xlabel("input tokens  (lower is cheaper)")
    ax.set_ylabel("oracle coverage, strict  (higher is better)")
    ax.set_title("Structured context is Pareto-dominant: more coverage, fewer tokens\n"
                 "point size = latency;  X = group mean", fontsize=10.5, loc="left")
    ax.legend(frameon=False, title="representation")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig3_pareto.png"), dpi=200)
    plt.close(fig)
    print("  fig3_pareto.png")


# ------------------------------------------------------------------ fig 4
def fig_judge_scatter(orc, judges):
    n = len(judges)
    fig, axes = plt.subplots(1, n, figsize=(4.6 * n, 4.4), squeeze=False)
    key = ["repo_name", "model", "context_variant"]
    for ax, (label, df, col) in zip(axes[0], judges):
        m = orc.merge(df[key + [col]], on=key, how="inner")
        x, y = m["oracle_coverage_strict"], pd.to_numeric(m[col], errors="coerce")
        ok = y.notna()
        x, y = x[ok], y[ok]
        ax.scatter(x, y, alpha=0.5, s=26, color="#2a6f97", edgecolor="white", linewidth=0.4)
        ax.plot([0, 1], [0, 1], ls="--", color="#888", lw=1)
        rho = x.corr(y, method="spearman")
        ax.set_title("%s\nSpearman rho = %+.3f   (n=%d)" % (label, rho, len(x)), fontsize=10)
        ax.set_xlabel("oracle coverage (deterministic)")
        ax.set_xlim(-0.03, 1.03); ax.set_ylim(-0.03, 1.03)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0][0].set_ylabel("judge coverage score")
    fig.suptitle("Judge vs deterministic oracle, identical summaries. Dashed = perfect agreement.",
                 fontsize=10.5, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig4_judge_scatter.png"), dpi=200)
    plt.close(fig)
    print("  fig4_judge_scatter.png")


def main():
    v2, orc = load_v2(), load_oracle()
    print("figures ->", OUT)
    fig_bimodality(v2)
    fig_heatmap(v2, orc)
    fig_pareto(orc)

    judges = []
    v2j = v2.copy()
    v2j["coverage_score"] = pd.to_numeric(v2j["coverage_score"], errors="coerce")
    judges.append(("mistral:7b-instruct (original harness)",
                   v2j[v2j["coverage_judged"] == 1], "coverage_score"))
    g = load_rejudge("gemma2_9b")
    if g is not None:
        judges.append(("gemma2:9b (fixed harness)", g, "coverage_score"))
    m = load_rejudge("mistral_7b-instruct")
    # Guard on length as well as None: the chained run creates its db immediately, so an
    # in-progress run yields an empty frame that would render a blank panel.
    if m is not None and len(m) >= 20:
        judges.append(("mistral:7b-instruct (fixed harness)", m, "coverage_score"))
    fig_judge_scatter(orc, judges)
    print("done -- %d judge panels" % len(judges))


if __name__ == "__main__":
    main()
