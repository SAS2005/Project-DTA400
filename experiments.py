"""Scientific experiment runner and multi-seed statistical aggregation.

Executes paired discrete-event simulation experiments across identical pre-generated
workloads for:
- Experiment 1: Strategy comparison (Vertical, Horizontal, Hybrid, Static baselines)
- Experiment 2: Startup delay sensitivity (0 s, 5 s, 10 s, 20 s, 30 s)
- Experiment 3: Warm standby operation (Enabled vs. Disabled)
- Experiment 4: Shutdown / scale-down observation delay (30 s, 60 s, 120 s)
- Experiment 5: Traffic spike scenarios and RQ3 hybrid cost-effectiveness regimes
"""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence
import numpy as np
import pandas as pd

from config import (
    AutoscalingConfig,
    SimulationConfig,
    TRAFFIC_SCENARIOS,
)
from scaling import SimulationResult, run_simulation
from workload import generate_workload


DEFAULT_SEEDS: Tuple[int, ...] = (42, 43, 44, 45, 46, 47, 48, 49, 50, 51)


def aggregate_runs(
    df_runs: pd.DataFrame,
    group_cols: Sequence[str],
) -> pd.DataFrame:
    """Compute mean, std, 95% confidence interval half-width, and per-run SLO compliance."""
    numeric_metrics = [
        "last_arrival_time_s",
        "last_completion_time_s",
        "total_elapsed_s",
        "drain_duration_s",
        "completed_in_window_requests",
        "completed_in_drain_requests",
        "avg_response_time_s",
        "p50_response_time_s",
        "p95_response_time_s",
        "p99_response_time_s",
        "max_response_time_s",
        "avg_waiting_time_s",
        "p95_waiting_time_s",
        "avg_processing_time_s",
        "arrival_window_throughput_req_per_s",
        "end_to_end_completion_rate_req_per_s",
        "throughput_req_per_s",
        "avg_queue_length",
        "max_queue_length",
        "avg_utilization",
        "avg_active_servers",
        "avg_active_capacity",
        "scale_up_count",
        "scale_down_count",
        "total_scaling_events",
        "active_cost",
        "provisioning_cost",
        "standby_cost",
        "total_cost",
        "cost_per_1k_requests",
        "cost_per_request",
        "slo_violation_fraction",
    ]

    records: List[Dict[str, object]] = []
    grouped = df_runs.groupby(list(group_cols), sort=False)

    for keys, group in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)
        row: Dict[str, object] = {col: val for col, val in zip(group_cols, keys)}
        n_runs = len(group)
        row["n_runs"] = n_runs
        # t-critical approximation for 95% CI (2.262 for n=10, 4.303 for n=3, 1.96 otherwise)
        if n_runs == 10:
            t_crit = 2.262
        elif n_runs == 5:
            t_crit = 2.776
        elif n_runs == 3:
            t_crit = 4.303
        else:
            t_crit = 1.960

        for m in numeric_metrics:
            if m not in group.columns:
                continue
            vals = group[m].to_numpy(dtype=float)
            mean_val = float(np.mean(vals))
            std_val = float(np.std(vals, ddof=1)) if n_runs > 1 else 0.0
            ci95_val = float(t_crit * std_val / np.sqrt(n_runs)) if n_runs > 1 else 0.0
            row[f"{m}_mean"] = mean_val
            row[f"{m}_std"] = std_val
            row[f"{m}_ci95"] = ci95_val

        if "p95_response_time_s" in group.columns:
            p95_arr = group["p95_response_time_s"].to_numpy(dtype=float)
            row["p95_response_time_s_max"] = float(np.max(p95_arr))

        slo_vals = group["slo_met"].to_numpy(dtype=bool)
        row["slo_pass_count"] = int(np.sum(slo_vals))
        row["slo_pass_rate"] = float(np.mean(slo_vals))
        row["slo_met_all_runs"] = bool(np.all(slo_vals))
        row["slo_met_majority"] = bool(np.mean(slo_vals) >= 0.5)

        if "slo_035_met" in group.columns:
            slo_035_vals = group["slo_035_met"].to_numpy(dtype=bool)
        else:
            slo_035_vals = (
                (group["p95_response_time_s"].to_numpy(dtype=float) <= 0.35)
                & (group["unfinished_requests"].to_numpy(dtype=int) == 0)
            )
        row["slo_035_pass_count"] = int(np.sum(slo_035_vals))
        row["slo_035_pass_rate"] = float(np.mean(slo_035_vals))
        row["slo_035_met_all_runs"] = bool(np.all(slo_035_vals))
        records.append(row)

    return pd.DataFrame(records)



def run_experiment_1_strategy_comparison(
    seeds: Sequence[int] = DEFAULT_SEEDS,
    output_dir: Optional[Path] = None,
) -> Dict[str, pd.DataFrame]:
    """Experiment 1: Compare Vertical, Horizontal, Hybrid, Adaptive Hybrid, and Static baselines."""
    strategies = [
        "vertical",
        "horizontal",
        "hybrid",
        "hybrid_adaptive",
        "static_1",
        "static_2",
        "static_4",
    ]
    profile = TRAFFIC_SCENARIOS["variable_baseline"]
    run_rows: List[Dict[str, object]] = []
    ts_frames: List[pd.DataFrame] = []
    evt_frames: List[pd.DataFrame] = []

    for seed in seeds:
        workload = generate_workload(traffic_profile=profile, seed=seed)
        for strat in strategies:
            cfg = SimulationConfig(
                strategy=strat,
                scenario_name="variable_baseline",
                traffic_profile=profile,
                random_seed=seed,
            )
            res = run_simulation(cfg, pregenerated_requests=workload)
            run_rows.append(res.summary.to_dict())

            if seed == seeds[0]:
                df_ts = pd.DataFrame([asdict(pt) for pt in res.metrics.time_series])
                df_ts["strategy"] = strat
                df_ts["seed"] = seed
                ts_frames.append(df_ts)

                if res.metrics.scaling_events:
                    df_ev = pd.DataFrame([asdict(ev) for ev in res.metrics.scaling_events])
                    df_ev["strategy"] = strat
                    df_ev["seed"] = seed
                    evt_frames.append(df_ev)

    df_runs = pd.DataFrame(run_rows)
    df_summary = aggregate_runs(df_runs, group_cols=["strategy", "scenario_name"])
    df_timeseries = pd.concat(ts_frames, ignore_index=True) if ts_frames else pd.DataFrame()
    df_events = pd.concat(evt_frames, ignore_index=True) if evt_frames else pd.DataFrame()

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        df_runs.to_csv(output_dir / "exp1_strategy_runs.csv", index=False)
        df_summary.to_csv(output_dir / "exp1_strategy_summary.csv", index=False)
        df_timeseries.to_csv(output_dir / "exp1_timeseries_seed42.csv", index=False)
        df_events.to_csv(output_dir / "exp1_scaling_events_seed42.csv", index=False)

    return {
        "runs": df_runs,
        "summary": df_summary,
        "timeseries": df_timeseries,
        "events": df_events,
    }


def run_experiment_2_startup_delay(
    seeds: Sequence[int] = DEFAULT_SEEDS,
    output_dir: Optional[Path] = None,
) -> Dict[str, pd.DataFrame]:
    """Experiment 2: Startup delay sensitivity (0 s, 5 s, 10 s, 20 s, 30 s)."""
    strategies = ["vertical", "horizontal", "hybrid"]
    delays = [0.0, 5.0, 10.0, 20.0, 30.0]
    scenarios = ["variable_baseline", "sudden_spike"]
    run_rows: List[Dict[str, object]] = []

    for scen in scenarios:
        profile = TRAFFIC_SCENARIOS[scen]
        for seed in seeds:
            workload = generate_workload(traffic_profile=profile, seed=seed)
            for delay in delays:
                for strat in strategies:
                    # In primary mode, horizontal_startup_delay=delay and vertical_upgrade_delay=delay
                    # so we compare identical provisioning latencies as well as realistic 1:2 ratios
                    auto_cfg = AutoscalingConfig(
                        horizontal_startup_delay=delay,
                        vertical_upgrade_delay=delay,
                    )
                    cfg = SimulationConfig(
                        strategy=strat,
                        scenario_name=scen,
                        traffic_profile=profile,
                        autoscaling=auto_cfg,
                        random_seed=seed,
                    )
                    res = run_simulation(cfg, pregenerated_requests=workload)
                    row = res.summary.to_dict()
                    row["startup_delay_s"] = delay
                    run_rows.append(row)

    df_runs = pd.DataFrame(run_rows)
    df_summary = aggregate_runs(
        df_runs, group_cols=["scenario_name", "strategy", "startup_delay_s"]
    )

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        df_runs.to_csv(output_dir / "exp2_startup_delay_runs.csv", index=False)
        df_summary.to_csv(output_dir / "exp2_startup_delay_summary.csv", index=False)

    return {"runs": df_runs, "summary": df_summary}


def run_experiment_3_standby(
    seeds: Sequence[int] = DEFAULT_SEEDS,
    output_dir: Optional[Path] = None,
) -> Dict[str, pd.DataFrame]:
    """Experiment 3: Warm standby enabled vs. disabled across traffic patterns."""
    strategies = ["horizontal", "hybrid"]
    standby_options = [False, True]
    # Test under recurring_spikes (with both 30s and 60s scale-down window) and variable_baseline
    configs_to_test = [
        ("variable_baseline", 60.0, 10.0),
        ("recurring_spikes", 60.0, 10.0),
        ("recurring_spikes", 30.0, 15.0),
    ]
    run_rows: List[Dict[str, object]] = []

    for scen, sd_window, cold_delay in configs_to_test:
        profile = TRAFFIC_SCENARIOS[scen]
        condition_label = f"{scen}_sd{int(sd_window)}s_cold{int(cold_delay)}s"
        for seed in seeds:
            workload = generate_workload(traffic_profile=profile, seed=seed)
            for strat in strategies:
                for stby in standby_options:
                    auto_cfg = AutoscalingConfig(
                        enable_standby=stby,
                        scale_down_observation_window=sd_window,
                        horizontal_startup_delay=cold_delay,
                        standby_startup_delay=2.0,
                    )
                    cfg = SimulationConfig(
                        strategy=strat,
                        scenario_name=scen,
                        traffic_profile=profile,
                        autoscaling=auto_cfg,
                        random_seed=seed,
                    )
                    res = run_simulation(cfg, pregenerated_requests=workload)
                    row = res.summary.to_dict()
                    row["enable_standby"] = stby
                    row["shutdown_delay_s"] = sd_window
                    row["cold_startup_delay_s"] = cold_delay
                    row["condition_label"] = condition_label
                    run_rows.append(row)

    df_runs = pd.DataFrame(run_rows)
    df_summary = aggregate_runs(
        df_runs,
        group_cols=[
            "condition_label",
            "scenario_name",
            "shutdown_delay_s",
            "cold_startup_delay_s",
            "strategy",
            "enable_standby",
        ],
    )

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        df_runs.to_csv(output_dir / "exp3_standby_runs.csv", index=False)
        df_summary.to_csv(output_dir / "exp3_standby_summary.csv", index=False)

    return {"runs": df_runs, "summary": df_summary}


def run_experiment_4_shutdown_delay(
    seeds: Sequence[int] = DEFAULT_SEEDS,
    output_dir: Optional[Path] = None,
) -> Dict[str, pd.DataFrame]:
    """Experiment 4: Scale-down observation / shutdown delay sensitivity (30 s, 60 s, 120 s)."""
    strategies = ["vertical", "horizontal", "hybrid"]
    shutdown_delays = [30.0, 60.0, 120.0]
    scenarios = ["recurring_spikes", "variable_baseline"]
    run_rows: List[Dict[str, object]] = []

    for scen in scenarios:
        profile = TRAFFIC_SCENARIOS[scen]
        for seed in seeds:
            workload = generate_workload(traffic_profile=profile, seed=seed)
            for sd in shutdown_delays:
                for strat in strategies:
                    auto_cfg = AutoscalingConfig(scale_down_observation_window=sd)
                    cfg = SimulationConfig(
                        strategy=strat,
                        scenario_name=scen,
                        traffic_profile=profile,
                        autoscaling=auto_cfg,
                        random_seed=seed,
                    )
                    res = run_simulation(cfg, pregenerated_requests=workload)
                    row = res.summary.to_dict()
                    row["shutdown_delay_s"] = sd
                    run_rows.append(row)

    df_runs = pd.DataFrame(run_rows)
    df_summary = aggregate_runs(
        df_runs, group_cols=["scenario_name", "strategy", "shutdown_delay_s"]
    )

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        df_runs.to_csv(output_dir / "exp4_shutdown_delay_runs.csv", index=False)
        df_summary.to_csv(output_dir / "exp4_shutdown_delay_summary.csv", index=False)

    return {"runs": df_runs, "summary": df_summary}


def run_experiment_5_workload_and_hybrid_regimes(
    seeds: Sequence[int] = DEFAULT_SEEDS,
    output_dir: Optional[Path] = None,
) -> Dict[str, pd.DataFrame]:
    """Experiment 5: Multi-scenario workload evaluation and RQ3 hybrid regime analysis."""
    strategies = ["vertical", "horizontal", "hybrid", "hybrid_adaptive"]
    scenarios = [
        "steady_low",
        "steady_normal",
        "steady_high",
        "variable_baseline",
        "sudden_spike",
        "recurring_spikes",
    ]
    run_rows: List[Dict[str, object]] = []

    for scen in scenarios:
        profile = TRAFFIC_SCENARIOS[scen]
        for seed in seeds:
            workload = generate_workload(traffic_profile=profile, seed=seed)
            for strat in strategies:
                cfg = SimulationConfig(
                    strategy=strat,
                    scenario_name=scen,
                    traffic_profile=profile,
                    random_seed=seed,
                )
                res = run_simulation(cfg, pregenerated_requests=workload)
                run_rows.append(res.summary.to_dict())

    df_runs = pd.DataFrame(run_rows)
    df_summary = aggregate_runs(df_runs, group_cols=["scenario_name", "strategy"])
    df_paired = compute_paired_comparisons(df_runs)

    # Build RQ3 SLO-threshold trade-off table distinguishing:
    # 1. Strict 100% per-run compliance (all evaluated seeds satisfy p95_response_time_s <= thresh)
    # 2. Mean-P95 feasibility (p95_response_time_s_mean <= thresh across seeds)
    slo_thresholds = [0.25, 0.30, 0.35, 0.40, 0.50, 1.00]
    rq3_rows: List[Dict[str, object]] = []
    for scen in ["variable_baseline", "sudden_spike", "recurring_spikes"]:
        sub_sum = df_summary[df_summary["scenario_name"] == scen].copy()
        sub_runs = df_runs[df_runs["scenario_name"] == scen]
        for thresh in slo_thresholds:
            pass_counts: Dict[str, int] = {}
            pass_rates: Dict[str, float] = {}
            all_pass_flags: Dict[str, bool] = {}

            for strat in strategies:
                s_runs = sub_runs[sub_runs["strategy"] == strat]
                n_s = len(s_runs)
                passed = (
                    (s_runs["p95_response_time_s"].to_numpy(dtype=float) <= thresh)
                    & (s_runs["unfinished_requests"].to_numpy(dtype=int) == 0)
                )
                cnt = int(np.sum(passed))
                pass_counts[strat] = cnt
                pass_rates[strat] = float(cnt / n_s) if n_s > 0 else 0.0
                all_pass_flags[strat] = bool(n_s > 0 and cnt == n_s)

            sub_sum["thresh_pass_count"] = sub_sum["strategy"].map(pass_counts)
            sub_sum["thresh_pass_rate"] = sub_sum["strategy"].map(pass_rates)
            sub_sum["thresh_all_runs_pass"] = sub_sum["strategy"].map(all_pass_flags)

            # Criterion A: Strict 100% per-run compliance (every run satisfies P95 <= thresh)
            strict_compliant = sub_sum[sub_sum["thresh_all_runs_pass"]]
            if len(strict_compliant) == 0:
                strict_winner = "none (no strategy meets SLO in 100% of runs)"
                strict_min_cost = np.nan
                strict_list = "none"
            else:
                best_strict_idx = strict_compliant["total_cost_mean"].idxmin()
                strict_winner = str(strict_compliant.loc[best_strict_idx, "strategy"])
                strict_min_cost = float(strict_compliant.loc[best_strict_idx, "total_cost_mean"])
                strict_list = ", ".join(
                    f"{r['strategy']} ({int(r['thresh_pass_count'])}/{int(r['n_runs'])})"
                    for _, r in strict_compliant.iterrows()
                )

            # Criterion B: Mean-P95 feasibility (mean P95 across seeds <= thresh)
            mean_compliant = sub_sum[sub_sum["p95_response_time_s_mean"] <= thresh]
            if len(mean_compliant) == 0:
                mean_winner = "none (no strategy meets mean P95)"
                mean_min_cost = np.nan
                mean_winner_cnt = 0
                mean_winner_rate = 0.0
                mean_list = "none"
            else:
                best_mean_idx = mean_compliant["total_cost_mean"].idxmin()
                mean_winner = str(mean_compliant.loc[best_mean_idx, "strategy"])
                mean_min_cost = float(mean_compliant.loc[best_mean_idx, "total_cost_mean"])
                mean_winner_cnt = int(mean_compliant.loc[best_mean_idx, "thresh_pass_count"])
                mean_winner_rate = float(mean_compliant.loc[best_mean_idx, "thresh_pass_rate"])
                mean_list = ", ".join(
                    f"{r['strategy']} ({int(r['thresh_pass_count'])}/{int(r['n_runs'])})"
                    for _, r in mean_compliant.iterrows()
                )

            rq3_rows.append(
                {
                    "scenario_name": scen,
                    "slo_p95_threshold_s": thresh,
                    "lowest_cost_compliant_strategy": strict_winner,
                    "lowest_cost_units": strict_min_cost,
                    "strict_100pct_compliant_strategies": strict_list,
                    "lowest_cost_mean_p95_strategy": mean_winner,
                    "lowest_cost_mean_p95_units": mean_min_cost,
                    "mean_winner_pass_count": mean_winner_cnt,
                    "mean_winner_pass_rate": mean_winner_rate,
                    "mean_p95_feasible_strategies": mean_list,
                }
            )
    df_rq3 = pd.DataFrame(rq3_rows)

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        df_runs.to_csv(output_dir / "exp5_scenarios_runs.csv", index=False)
        df_summary.to_csv(output_dir / "exp5_scenarios_summary.csv", index=False)
        df_rq3.to_csv(output_dir / "exp5_rq3_slo_regimes.csv", index=False)
        df_paired.to_csv(output_dir / "exp5_paired_comparisons.csv", index=False)

    return {
        "runs": df_runs,
        "summary": df_summary,
        "rq3_regimes": df_rq3,
        "paired_comparisons": df_paired,
    }


def run_all_experiments(
    seeds: Sequence[int] = DEFAULT_SEEDS,
    output_dir: Path = Path("results"),
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """Run all five scientific experiments and save machine-readable CSV outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {
        "exp1": run_experiment_1_strategy_comparison(seeds=seeds, output_dir=output_dir),
        "exp2": run_experiment_2_startup_delay(seeds=seeds, output_dir=output_dir),
        "exp3": run_experiment_3_standby(seeds=seeds, output_dir=output_dir),
        "exp4": run_experiment_4_shutdown_delay(seeds=seeds, output_dir=output_dir),
        "exp5": run_experiment_5_workload_and_hybrid_regimes(seeds=seeds, output_dir=output_dir),
    }
    return results
