"""End-to-end integration tests for paired multi-strategy comparisons and reproducibility."""

from __future__ import annotations

import pytest

from config import SimulationConfig, TRAFFIC_SCENARIOS, TrafficSegment
from experiments import aggregate_runs
from scaling import run_simulation
from workload import generate_workload


def test_reproducibility_with_fixed_seeds() -> None:
    """Running the same strategy twice with the same seed must produce identical outputs."""
    cfg = SimulationConfig(
        strategy="hybrid",
        traffic_profile=TRAFFIC_SCENARIOS["variable_baseline"],
        simulation_duration=1200.0,
        random_seed=77,
    )
    res_a = run_simulation(cfg)
    res_b = run_simulation(cfg)

    assert res_a.summary.generated_requests == res_b.summary.generated_requests
    assert res_a.summary.completed_requests == res_b.summary.completed_requests
    assert res_a.summary.avg_response_time_s == pytest.approx(res_b.summary.avg_response_time_s, abs=1e-12)
    assert res_a.summary.p95_response_time_s == pytest.approx(res_b.summary.p95_response_time_s, abs=1e-12)
    assert res_a.summary.total_cost == pytest.approx(res_b.summary.total_cost, abs=1e-12)


def test_paired_shared_workload_conservation_of_requests() -> None:
    """All three primary strategies must process the exact same generated workload without loss."""
    profile = (
        TrafficSegment(0.0, 200.0, 3.0, "Low"),
        TrafficSegment(200.0, 400.0, 12.0, "High"),
        TrafficSegment(400.0, 500.0, 20.0, "Spike"),
        TrafficSegment(500.0, 700.0, 3.0, "Low"),
    )
    shared_workload = generate_workload(traffic_profile=profile, seed=42)
    expected_n = len(shared_workload)
    assert expected_n > 3000

    summaries = {}
    for strat in ["vertical", "horizontal", "hybrid"]:
        cfg = SimulationConfig(
            strategy=strat,
            traffic_profile=profile,
            simulation_duration=700.0,
            random_seed=42,
        )
        res = run_simulation(cfg, pregenerated_requests=shared_workload)
        s = res.summary
        summaries[strat] = s

        # Verify request conservation and mathematical bounds
        assert s.generated_requests == expected_n
        assert s.completed_requests == expected_n
        assert s.unfinished_requests == 0
        assert 0.0 < s.avg_utilization <= 1.0
        assert s.avg_queue_length >= 0.0
        assert s.total_cost > 0.0
        assert s.p95_response_time_s >= s.avg_response_time_s

    # Verify that the strategies actually differ in behavior on the shared workload
    assert summaries["vertical"].avg_response_time_s != pytest.approx(
        summaries["horizontal"].avg_response_time_s, abs=1e-4
    )


