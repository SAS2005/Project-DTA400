"""Command-line entry point for the DTA400 Dynamic Server Scaling Simulation.

Supports running:
- A quick paired baseline comparison (`python main.py --mode baseline`)
- The complete multi-seed experimental suite (`python main.py --mode experiments`)
- Figure generation from saved CSV results (`python main.py --mode plots`)
- Full end-to-end execution of experiments + plots (`python main.py --mode all`)
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from config import SimulationConfig, TRAFFIC_SCENARIOS
from experiments import DEFAULT_SEEDS, run_all_experiments
from plots import generate_all_figures
from scaling import run_simulation
from workload import generate_workload


def run_baseline_demo(seed: int = 42, scenario: str = "variable_baseline") -> None:
    """Run a single-seed paired comparison across all strategies and print a summary table."""
    profile = TRAFFIC_SCENARIOS[scenario]
    workload = generate_workload(traffic_profile=profile, seed=seed)
    strategies = [
        "vertical",
        "horizontal",
        "hybrid",
        "hybrid_adaptive",
        "static_1",
        "static_2",
        "static_4",
    ]

    print("=" * 98)
    print(
        f"DTA400 Dynamic Server Scaling Simulation — Paired Baseline Comparison "
        f"(Scenario: {scenario}, Seed: {seed})"
    )
    print(f"Generated Requests: {len(workload)} over 3,600 s (60 minutes)")
    print("=" * 98)
    header = (
        f"{'Strategy':18s} | {'Avg RT (s)':>10s} | {'P95 RT (s)':>10s} | "
        f"{'Tput (r/s)':>10s} | {'Util (%)':>8s} | {'Total Cost':>10s} | "
        f"{'Cost/1k Req':>11s} | {'SLO Met':>7s}"
    )
    print(header)
    print("-" * 98)

    for strat in strategies:
        cfg = SimulationConfig(
            strategy=strat,
            scenario_name=scenario,
            traffic_profile=profile,
            random_seed=seed,
        )
        res = run_simulation(cfg, pregenerated_requests=workload)
        s = res.summary
        slo_str = "YES" if s.slo_met else "NO"
        print(
            f"{s.strategy:18s} | {s.avg_response_time_s:10.4f} | {s.p95_response_time_s:10.4f} | "
            f"{s.throughput_req_per_s:10.2f} | {s.avg_utilization * 100.0:8.1f} | "
            f"{s.total_cost:10.4f} | {s.cost_per_1k_requests:11.5f} | {slo_str:>7s}"
        )
    print("=" * 98)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DTA400 Dynamic Server Scaling Discrete-Event Simulation (SimPy)"
    )
    parser.add_argument(
        "--mode",
        choices=["baseline", "experiments", "plots", "all"],
        default="all",
        help="Execution mode: baseline demo, full experiments, plot generation, or all.",
    )
    parser.add_argument(
        "--num-seeds",
        type=int,
        default=len(DEFAULT_SEEDS),
        help="Number of independent random seeds for multi-run experiments (default: 10).",
    )
    parser.add_argument(
        "--scenario",
        choices=list(TRAFFIC_SCENARIOS.keys()),
        default="variable_baseline",
        help="Traffic scenario for --mode baseline (default: variable_baseline).",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results"),
        help="Directory for CSV output files (default: results/).",
    )
    parser.add_argument(
        "--figures-dir",
        type=Path,
        default=Path("figures"),
        help="Directory for generated plots (default: figures/).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seeds: List[int] = [42 + i for i in range(max(1, args.num_seeds))]

    if args.mode == "baseline":
        run_baseline_demo(seed=seeds[0], scenario=args.scenario)
        return

    if args.mode in ("experiments", "all"):
        print(f"Running all 5 simulation experiments across N={len(seeds)} seeds {seeds}...")
        exp_results = run_all_experiments(seeds=seeds, output_dir=args.results_dir)
        df_sum = exp_results["exp1"]["summary"]
        print("\n=== Experiment 1 Summary (Mean ± 95% CI across N=" + str(len(seeds)) + " seeds) ===")
        for _, r in df_sum.iterrows():
            slo_tag = "YES" if r["slo_met_all_runs"] else "NO"
            print(
                f"  {r['strategy']:16s} | Avg RT: {r['avg_response_time_s_mean']:.4f}±{r['avg_response_time_s_ci95']:.4f}s | "
                f"P95: {r['p95_response_time_s_mean']:.4f}±{r['p95_response_time_s_ci95']:.4f}s | "
                f"Cost: {r['total_cost_mean']:.4f}±{r['total_cost_ci95']:.4f} | "
                f"Cost/1k: {r['cost_per_1k_requests_mean']:.5f} | SLO: {slo_tag}"
            )
        print(f"\nSaved machine-readable CSV datasets to: {args.results_dir.resolve()}")

    if args.mode in ("plots", "all"):
        print(f"\nGenerating publication-quality figures in: {args.figures_dir.resolve()}...")
        paths = generate_all_figures(results_dir=args.results_dir, figures_dir=args.figures_dir)
        for p in paths:
            print(f"  [OK] {p}")


if __name__ == "__main__":
    main()
