"""Publication-quality visualization module for DTA400 Server Scaling Simulation.

Generates all 10 required analytical figures from actual simulation CSV outputs,
styled for readability at IEEE two-column conference paper dimensions (300 DPI).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import VARIABLE_BASELINE_PROFILE


STRATEGY_LABELS: Dict[str, str] = {
    "vertical": "Vertical (1x1..4)",
    "horizontal": "Horizontal (1..4x1)",
    "hybrid": "Hybrid (1x1->1x2->2x2)",
    "hybrid_adaptive": "Hybrid-Adaptive (Fine)",
    "static_1": "Static-1 (1x1)",
    "static_2": "Static-2 (1x2)",
    "static_4": "Static-4 (1x4)",
}

STRATEGY_COLORS: Dict[str, str] = {
    "vertical": "#1f77b4",
    "horizontal": "#ff7f0e",
    "hybrid": "#2ca02c",
    "hybrid_adaptive": "#9467bd",
    "static_1": "#d62728",
    "static_2": "#8c564b",
    "static_4": "#7f7f7f",
}

STRATEGY_MARKERS: Dict[str, str] = {
    "vertical": "o",
    "horizontal": "s",
    "hybrid": "^",
    "hybrid_adaptive": "D",
    "static_1": "v",
    "static_2": "P",
    "static_4": "X",
}


def _apply_ieee_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "figure.dpi": 300,
            "savefig.dpi": 300,
            "axes.grid": True,
            "grid.alpha": 0.3,
            "grid.linestyle": "--",
        }
    )


def plot_fig01_workload_over_time(df_ts: pd.DataFrame, figures_dir: Path) -> Path:
    """Fig 1: Workload over time (target piecewise Poisson rate vs observed rate)."""
    _apply_ieee_style()
    fig, ax = plt.subplots(figsize=(6.5, 3.2))

    # Plot observed arrival rate from one strategy's time-series (smoothed 30s rolling + raw 5s)
    sub = df_ts[df_ts["strategy"] == "vertical"].sort_values("time_s")
    t_min = sub["time_s"] / 60.0
    ax.plot(
        t_min,
        sub["arrival_rate_window"],
        color="#aec7e8",
        linewidth=0.8,
        alpha=0.75,
        label="Observed rate (5 s window)",
    )
    rolling_rate = sub["arrival_rate_window"].rolling(window=6, min_periods=1).mean()
    ax.plot(
        t_min,
        rolling_rate,
        color="#1f77b4",
        linewidth=1.5,
        label="Observed rate (30 s moving average)",
    )

    # Target step profile
    step_x: List[float] = []
    step_y: List[float] = []
    for seg in VARIABLE_BASELINE_PROFILE:
        step_x.extend([seg.start_time / 60.0, seg.end_time / 60.0])
        step_y.extend([seg.arrival_rate, seg.arrival_rate])
    ax.plot(
        step_x,
        step_y,
        color="#d62728",
        linestyle="--",
        linewidth=1.8,
        label="Target Poisson rate λ(t)",
    )

    ax.set_title("Incoming Web Application Workload Profile Over Time (60 Minutes)")
    ax.set_xlabel("Simulated Time (minutes)")
    ax.set_ylabel("Arrival Intensity (requests/s)")
    ax.set_xlim(0, 60)
    ax.set_ylim(0, 26)
    ax.legend(loc="upper left", frameon=True)
    fig.tight_layout()

    out = figures_dir / "fig01_workload_over_time.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_fig02_avg_response_time(df_summary: pd.DataFrame, figures_dir: Path) -> Path:
    """Fig 2: Average response time by scaling strategy."""
    _apply_ieee_style()
    primary = ["vertical", "horizontal", "hybrid", "hybrid_adaptive", "static_4"]
    sub = df_summary[df_summary["strategy"].isin(primary)].copy()
    sub["order"] = sub["strategy"].map({k: i for i, k in enumerate(primary)})
    sub = sub.sort_values("order")

    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    x = np.arange(len(sub))
    labels = [STRATEGY_LABELS.get(s, s) for s in sub["strategy"]]
    colors = [STRATEGY_COLORS.get(s, "#333333") for s in sub["strategy"]]
    means = sub["avg_response_time_s_mean"].to_numpy()
    cis = sub["avg_response_time_s_ci95"].to_numpy()

    bars = ax.bar(x, means, yerr=cis, capsize=4, color=colors, edgecolor="black", linewidth=0.7, width=0.58)
    for bar, val in zip(bars, means):
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            bar.get_height() + 0.006,
            f"{val:.3f} s",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    ax.set_title("Mean End-to-End Response Time by Scaling Strategy (N=10 Runs)")
    ax.set_xlabel("Scaling Strategy")
    ax.set_ylabel("Mean Response Time (s)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylim(0, max(means + cis) * 1.25)
    fig.tight_layout()

    out = figures_dir / "fig02_avg_response_time_by_strategy.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_fig03_p95_response_time(df_summary: pd.DataFrame, figures_dir: Path) -> Path:
    """Fig 3: P95 response time by scaling strategy relative to the 1.0 s SLO target."""
    _apply_ieee_style()
    primary = ["vertical", "horizontal", "hybrid", "hybrid_adaptive", "static_4"]
    sub = df_summary[df_summary["strategy"].isin(primary)].copy()
    sub["order"] = sub["strategy"].map({k: i for i, k in enumerate(primary)})
    sub = sub.sort_values("order")

    fig, ax = plt.subplots(figsize=(5.5, 3.4))
    x = np.arange(len(sub))
    labels = [STRATEGY_LABELS.get(s, s) for s in sub["strategy"]]
    colors = [STRATEGY_COLORS.get(s, "#333333") for s in sub["strategy"]]
    means = sub["p95_response_time_s_mean"].to_numpy()
    cis = sub["p95_response_time_s_ci95"].to_numpy()

    bars = ax.bar(x, means, yerr=cis, capsize=4, color=colors, edgecolor="black", linewidth=0.7, width=0.58)
    for bar, val in zip(bars, means):
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            bar.get_height() + 0.015,
            f"{val:.3f} s",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    ax.axhline(1.0, color="#d62728", linestyle="--", linewidth=1.4, label="SLO Target (P95 <= 1.0 s)")
    ax.axhline(0.35, color="#2ca02c", linestyle=":", linewidth=1.2, label="Strict Target (P95 <= 0.35 s)")

    ax.set_title("95th Percentile (P95) Response Time by Strategy (N=10 Runs)")
    ax.set_xlabel("Scaling Strategy")
    ax.set_ylabel("P95 Response Time (s)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylim(0, 1.15)
    ax.legend(loc="upper right", frameon=True)
    fig.tight_layout()

    out = figures_dir / "fig03_p95_response_time_by_strategy.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_fig04_total_cost(df_summary: pd.DataFrame, figures_dir: Path) -> Path:
    """Fig 4: Total modeled operating cost by strategy (broken down by state)."""
    _apply_ieee_style()
    order_list = [
        "vertical",
        "horizontal",
        "hybrid",
        "hybrid_adaptive",
        "static_1",
        "static_2",
        "static_4",
    ]
    sub = df_summary[df_summary["strategy"].isin(order_list)].copy()
    sub["order"] = sub["strategy"].map({k: i for i, k in enumerate(order_list)})
    sub = sub.sort_values("order")

    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    x = np.arange(len(sub))
    labels = [STRATEGY_LABELS.get(s, s) for s in sub["strategy"]]

    act = sub["active_cost_mean"].to_numpy()
    prov = sub["provisioning_cost_mean"].to_numpy()
    stby = sub["standby_cost_mean"].to_numpy()
    tot = sub["total_cost_mean"].to_numpy()
    cis = sub["total_cost_ci95"].to_numpy()

    ax.bar(x, act, label="Active Capacity Cost", color="#4c72b0", edgecolor="black", linewidth=0.6, width=0.58)
    ax.bar(
        x,
        prov,
        bottom=act,
        label="Startup / Upgrade Provisioning Cost",
        color="#dd8452",
        edgecolor="black",
        linewidth=0.6,
        width=0.58,
    )
    ax.bar(
        x,
        stby,
        bottom=act + prov,
        yerr=cis,
        capsize=3,
        label="Standby Cost",
        color="#55a868",
        edgecolor="black",
        linewidth=0.6,
        width=0.58,
    )

    for xi, val, slo in zip(x, tot, sub["slo_met_all_runs"]):
        tag = f"{val:.2f}" if slo else f"{val:.2f} (SLO X)"
        ax.text(xi, val + 0.06, tag, ha="center", va="bottom", fontsize=7.5)

    ax.set_title("Modeled Operating Cost Breakdown Over 60-Minute Workload (N=10 Runs)")
    ax.set_xlabel("Scaling Strategy")
    ax.set_ylabel("Operating Cost (normalized cost units)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=18, ha="right")
    ax.set_ylim(0, 4.55)
    ax.legend(loc="upper left", frameon=True)
    fig.tight_layout()

    out = figures_dir / "fig04_total_cost_by_strategy.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_fig05_active_servers_over_time(df_ts: pd.DataFrame, figures_dir: Path) -> Path:
    """Fig 5: Active server instance count over simulation time."""
    _apply_ieee_style()
    fig, ax = plt.subplots(figsize=(6.5, 3.2))

    strategies = ["vertical", "horizontal", "hybrid", "hybrid_adaptive"]
    linestyles = ["-", "--", "-.", ":"]
    offsets = [-0.04, 0.0, 0.04, 0.08]  # Slight visual offset to prevent exact line overlap

    for strat, ls, off in zip(strategies, linestyles, offsets):
        sub = df_ts[df_ts["strategy"] == strat].sort_values("time_s")
        ax.step(
            sub["time_s"] / 60.0,
            sub["active_servers"] + off,
            where="post",
            label=STRATEGY_LABELS[strat],
            color=STRATEGY_COLORS[strat],
            linestyle=ls,
            linewidth=1.6,
        )

    ax.set_title("Active Server Instance Count Over Time (Variable Workload)")
    ax.set_xlabel("Simulated Time (minutes)")
    ax.set_ylabel("Number of Active Servers")
    ax.set_xlim(0, 60)
    ax.set_yticks([1, 2, 3, 4])
    ax.set_ylim(0.5, 4.5)
    ax.legend(loc="upper left", frameon=True)
    fig.tight_layout()

    out = figures_dir / "fig05_active_servers_over_time.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_fig06_available_capacity_over_time(df_ts: pd.DataFrame, figures_dir: Path) -> Path:
    """Fig 6: Effective provisioned processing capacity over simulation time."""
    _apply_ieee_style()
    fig, ax = plt.subplots(figsize=(6.5, 3.3))

    # Plot theoretical mean CPU demand rate = lambda(t) * 0.13 CPU-s
    step_x: List[float] = []
    step_y: List[float] = []
    for seg in VARIABLE_BASELINE_PROFILE:
        step_x.extend([seg.start_time / 60.0, seg.end_time / 60.0])
        step_y.extend([seg.arrival_rate * 0.13, seg.arrival_rate * 0.13])
    ax.fill_between(
        step_x,
        0,
        step_y,
        color="#d62728",
        alpha=0.15,
        label="Mean CPU Demand Rate λ(t)·E[W]",
    )

    strategies = ["vertical", "horizontal", "hybrid", "hybrid_adaptive"]
    linestyles = ["-", "--", "-.", ":"]
    offsets = [-0.05, 0.0, 0.05, 0.10]

    for strat, ls, off in zip(strategies, linestyles, offsets):
        sub = df_ts[df_ts["strategy"] == strat].sort_values("time_s")
        ax.step(
            sub["time_s"] / 60.0,
            sub["active_capacity"] + off,
            where="post",
            label=STRATEGY_LABELS[strat],
            color=STRATEGY_COLORS[strat],
            linestyle=ls,
            linewidth=1.6,
        )

    ax.set_title("Provisioned Active Processing Capacity Over Time")
    ax.set_xlabel("Simulated Time (minutes)")
    ax.set_ylabel("Processing Capacity (capacity units)")
    ax.set_xlim(0, 60)
    ax.set_yticks([0, 1, 2, 3, 4])
    ax.set_ylim(0, 4.5)
    ax.legend(loc="upper left", frameon=True)
    fig.tight_layout()

    out = figures_dir / "fig06_available_capacity_over_time.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_fig07_queue_length_over_time(df_ts: pd.DataFrame, figures_dir: Path) -> Path:
    """Fig 7: Time-weighted queue length over simulation time."""
    _apply_ieee_style()
    fig, ax = plt.subplots(figsize=(6.5, 3.2))

    strategies = ["vertical", "horizontal", "hybrid", "hybrid_adaptive"]
    for strat in strategies:
        sub = df_ts[df_ts["strategy"] == strat].sort_values("time_s")
        # Plot 15-second (3-sample) rolling mean of window queue length for visual clarity
        q_smooth = sub["avg_queue_length_window"].rolling(window=3, min_periods=1).mean()
        ax.plot(
            sub["time_s"] / 60.0,
            q_smooth,
            label=STRATEGY_LABELS[strat],
            color=STRATEGY_COLORS[strat],
            linewidth=1.3,
            alpha=0.9,
        )

    ax.set_title("FIFO Waiting Queue Length Over Time (15 s Moving Average)")
    ax.set_xlabel("Simulated Time (minutes)")
    ax.set_ylabel("Waiting Queue Length (requests)")
    ax.set_xlim(0, 60)
    ax.legend(loc="upper right", frameon=True)
    fig.tight_layout()

    out = figures_dir / "fig07_queue_length_over_time.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_fig08_cost_vs_response_time(df_summary: pd.DataFrame, figures_dir: Path) -> Path:
    """Fig 8: Operating Cost vs P95 Response Time Pareto trade-off chart."""
    _apply_ieee_style()
    fig, ax = plt.subplots(figsize=(6.0, 3.6))

    # Plot SLO-compliant strategies + static_2 (exclude static_1 at P95=500s from main axis, note in caption/inset)
    plotted = df_summary[df_summary["strategy"] != "static_1"].copy()

    ax.axvspan(0.0, 1.0, color="#2ca02c", alpha=0.08, label="SLO-Compliant Region (P95 <= 1.0 s)")
    ax.axvline(1.0, color="#d62728", linestyle="--", linewidth=1.3, label="SLO Boundary (1.0 s)")
    ax.axvline(0.35, color="#2ca02c", linestyle=":", linewidth=1.1, label="Strict Latency Regime (0.35 s)")

    for _, row in plotted.iterrows():
        strat = str(row["strategy"])
        x_val = float(row["p95_response_time_s_mean"])
        y_val = float(row["total_cost_mean"])
        x_err = float(row["p95_response_time_s_ci95"])
        y_err = float(row["total_cost_ci95"])

        # Cap x_val for static_2 display on a broken/annotated scale if needed, or use log x-axis
        ax.errorbar(
            x_val,
            y_val,
            xerr=x_err,
            yerr=y_err,
            fmt=STRATEGY_MARKERS.get(strat, "o"),
            color=STRATEGY_COLORS.get(strat, "#333333"),
            markersize=7,
            capsize=3,
            label=STRATEGY_LABELS.get(strat, strat),
        )
        label_offsets = {
            "vertical": (-42, 8),
            "hybrid": (7, 7),
            "hybrid_adaptive": (-82, -2),
            "horizontal": (7, -9),
            "static_2": (-38, 7),
            "static_4": (7, -4),
        }
        ax.annotate(
            STRATEGY_LABELS.get(strat, strat).split(" (")[0],
            (x_val, y_val),
            textcoords="offset points",
            xytext=label_offsets.get(strat, (6, 4)),
            fontsize=7.5,
        )

    ax.set_xscale("log")
    ax.set_title("Operating Cost vs. P95 Response Time Trade-Off (Log Latency Scale)")
    ax.set_xlabel("P95 Response Time (s, log scale)")
    ax.set_ylabel("Total Operating Cost (cost units)")
    ax.set_xlim(0.08, 35.0)
    ax.set_ylim(1.5, 4.3)
    ax.legend(loc="upper right", frameon=True, fontsize=7.5)
    fig.tight_layout()

    out = figures_dir / "fig08_cost_vs_response_time_tradeoff.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_fig09_cold_start_impact(df_exp2: pd.DataFrame, figures_dir: Path) -> Path:
    """Fig 9: Effect of startup/upgrade delay (0 s to 30 s) on P95 latency and cost."""
    _apply_ieee_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.8, 3.2))

    for ax, scen, title_tag in [
        (ax1, "variable_baseline", "Variable Baseline Workload"),
        (ax2, "sudden_spike", "Sudden Traffic Spike (6 -> 20 req/s)"),
    ]:
        sub = df_exp2[df_exp2["scenario_name"] == scen]
        for strat in ["vertical", "horizontal", "hybrid"]:
            s_df = sub[sub["strategy"] == strat].sort_values("startup_delay_s")
            ax.errorbar(
                s_df["startup_delay_s"],
                s_df["p95_response_time_s_mean"],
                yerr=s_df["p95_response_time_s_ci95"],
                marker=STRATEGY_MARKERS[strat],
                color=STRATEGY_COLORS[strat],
                linewidth=1.5,
                capsize=3,
                label=STRATEGY_LABELS[strat],
            )
        ax.axhline(1.0, color="#d62728", linestyle="--", linewidth=1.2, label="1.0 s SLO")
        ax.set_title(title_tag)
        ax.set_xlabel("Provisioning Startup Delay (s)")
        ax.set_ylabel("P95 Response Time (s)")

    ax1.legend(loc="upper left", frameon=True, fontsize=7.5)
    fig.suptitle("Impact of Cold-Start / Upgrade Delay on P95 Response Time", fontsize=10, y=1.01)
    fig.tight_layout()

    out = figures_dir / "fig09_cold_start_impact.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_fig10_standby_and_shutdown_sensitivity(
    df_exp3: pd.DataFrame,
    df_exp4: pd.DataFrame,
    figures_dir: Path,
) -> Path:
    """Fig 10: Sensitivity to warm standby (Panel A) and shutdown delay (Panel B)."""
    _apply_ieee_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 3.3))

    # Panel A: Standby Enabled vs Disabled under recurring_spikes (sd=30s and sd=60s)
    sub3 = df_exp3[df_exp3["scenario_name"] == "recurring_spikes"].copy()
    groups = [
        ("horizontal", 60.0, "Horiz\n(SD=60s)"),
        ("hybrid", 60.0, "Hybrid\n(SD=60s)"),
        ("horizontal", 30.0, "Horiz\n(SD=30s)"),
        ("hybrid", 30.0, "Hybrid\n(SD=30s)"),
    ]
    x = np.arange(len(groups))
    width = 0.34
    off_vals = []
    on_vals = []
    for strat, sd_val, _ in groups:
        r_off = sub3[
            (sub3["strategy"] == strat)
            & (sub3["shutdown_delay_s"] == sd_val)
            & (~sub3["enable_standby"])
        ]
        r_on = sub3[
            (sub3["strategy"] == strat)
            & (sub3["shutdown_delay_s"] == sd_val)
            & (sub3["enable_standby"])
        ]
        off_vals.append(float(r_off["p95_response_time_s_mean"].iloc[0]) if len(r_off) else 0.0)
        on_vals.append(float(r_on["p95_response_time_s_mean"].iloc[0]) if len(r_on) else 0.0)

    ax1.bar(x - width / 2, off_vals, width, label="Standby Disabled (Cold 10-15s)", color="#dd8452", edgecolor="black", linewidth=0.6)
    ax1.bar(x + width / 2, on_vals, width, label="Standby Enabled (Warm 2s)", color="#55a868", edgecolor="black", linewidth=0.6)
    ax1.axhline(1.0, color="#d62728", linestyle="--", linewidth=1.2, label="1.0 s SLO")
    ax1.set_title("(a) Standby Impact on Recurring Spikes")
    ax1.set_xlabel("Strategy & Scale-Down Window")
    ax1.set_ylabel("P95 Response Time (s)")
    ax1.set_xticks(x)
    ax1.set_xticklabels([g[2] for g in groups])
    ax1.legend(loc="upper left", frameon=True, fontsize=7)

    # Panel B: Shutdown delay (30s, 60s, 120s) on recurring_spikes (P95 vs Cost dual view or P95 lines)
    sub4 = df_exp4[df_exp4["scenario_name"] == "recurring_spikes"]
    for strat in ["vertical", "horizontal", "hybrid"]:
        s_df = sub4[sub4["strategy"] == strat].sort_values("shutdown_delay_s")
        ax2.errorbar(
            s_df["shutdown_delay_s"],
            s_df["p95_response_time_s_mean"],
            yerr=s_df["p95_response_time_s_ci95"],
            marker=STRATEGY_MARKERS[strat],
            color=STRATEGY_COLORS[strat],
            linewidth=1.5,
            capsize=3,
            label=f"{STRATEGY_LABELS[strat].split(' (')[0]} (P95)",
        )
    ax2.axhline(1.0, color="#d62728", linestyle="--", linewidth=1.2, label="1.0 s SLO")
    ax2.set_title("(b) Shutdown Delay (Recurring Spikes)")
    ax2.set_xlabel("Scale-Down Observation Delay (s)")
    ax2.set_ylabel("P95 Response Time (s)")
    ax2.set_xticks([30, 60, 120])
    ax2.legend(loc="upper right", frameon=True, fontsize=7)

    fig.tight_layout()
    out = figures_dir / "fig10_standby_and_shutdown_sensitivity.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def generate_all_figures(
    results_dir: Path = Path("results"),
    figures_dir: Path = Path("figures"),
) -> List[Path]:
    """Load CSV experiment outputs from results_dir and generate all 10 figures."""
    figures_dir.mkdir(parents=True, exist_ok=True)

    df_exp1_sum = pd.read_csv(results_dir / "exp1_strategy_summary.csv")
    df_exp1_ts = pd.read_csv(results_dir / "exp1_timeseries_seed42.csv")
    df_exp2_sum = pd.read_csv(results_dir / "exp2_startup_delay_summary.csv")
    df_exp3_sum = pd.read_csv(results_dir / "exp3_standby_summary.csv")
    df_exp4_sum = pd.read_csv(results_dir / "exp4_shutdown_delay_summary.csv")

    generated = [
        plot_fig01_workload_over_time(df_exp1_ts, figures_dir),
        plot_fig02_avg_response_time(df_exp1_sum, figures_dir),
        plot_fig03_p95_response_time(df_exp1_sum, figures_dir),
        plot_fig04_total_cost(df_exp1_sum, figures_dir),
        plot_fig05_active_servers_over_time(df_exp1_ts, figures_dir),
        plot_fig06_available_capacity_over_time(df_exp1_ts, figures_dir),
        plot_fig07_queue_length_over_time(df_exp1_ts, figures_dir),
        plot_fig08_cost_vs_response_time(df_exp1_sum, figures_dir),
        plot_fig09_cold_start_impact(df_exp2_sum, figures_dir),
        plot_fig10_standby_and_shutdown_sensitivity(df_exp3_sum, df_exp4_sum, figures_dir),
    ]
    return generated
