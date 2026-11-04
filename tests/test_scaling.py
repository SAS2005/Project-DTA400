"""Automated unit tests for the Autoscaler control policies (Component 4)."""

from __future__ import annotations

import pytest

from config import AutoscalingConfig, SimulationConfig, TrafficSegment
from scaling import run_simulation
from workload import generate_workload


def test_scale_up_and_max_capacity_limit() -> None:
    """Autoscaler must scale up under high load and never exceed max_capacity=4."""
    profile = (TrafficSegment(0.0, 300.0, 20.0, "Intense Spike"),)
    workload = generate_workload(traffic_profile=profile, seed=42)

    for strat in ["vertical", "horizontal", "hybrid"]:
        cfg = SimulationConfig(
            strategy=strat,
            traffic_profile=profile,
            simulation_duration=300.0,
            random_seed=42,
        )
        res = run_simulation(cfg, pregenerated_requests=workload)
        assert res.summary.scale_up_count >= 2
        for pt in res.metrics.time_series:
            assert pt.active_capacity <= 4.0 + 1e-9
            assert pt.active_servers <= 4
            if strat == "vertical":
                assert pt.active_servers == 1
            elif strat == "horizontal":
                assert pt.active_capacity == pytest.approx(float(pt.active_servers))


def test_scale_down_and_min_capacity_limit() -> None:
    """Autoscaler must scale down after low utilization window and never drop below min_capacity=1."""
    profile = (
        TrafficSegment(0.0, 120.0, 20.0, "Spike"),
        TrafficSegment(120.0, 400.0, 1.0, "Very Low"),
    )
    workload = generate_workload(traffic_profile=profile, seed=42)

    for strat in ["vertical", "horizontal", "hybrid"]:
        cfg = SimulationConfig(
            strategy=strat,
            traffic_profile=profile,
            simulation_duration=400.0,
            random_seed=42,
        )
        res = run_simulation(cfg, pregenerated_requests=workload)
        assert res.summary.scale_up_count >= 2
        assert res.summary.scale_down_count >= 2
        # By end of simulation, capacity returns to min_capacity = 1.0
        assert res.metrics.pool.active_capacity == pytest.approx(1.0)
        for pt in res.metrics.time_series:
            assert pt.active_capacity >= 1.0 - 1e-9


def test_cooldown_prevents_premature_reversal() -> None:
    """Scale-down must respect scaling_cooldown and scale_down_observation_window."""
    profile = (
        TrafficSegment(0.0, 60.0, 14.0, "High"),
        TrafficSegment(60.0, 300.0, 1.0, "Low"),
    )
    workload = generate_workload(traffic_profile=profile, seed=42)
    auto_cfg = AutoscalingConfig(
        scale_down_observation_window=60.0,
        scaling_cooldown=90.0,
    )
    cfg = SimulationConfig(
        strategy="vertical",
        traffic_profile=profile,
        autoscaling=auto_cfg,
        simulation_duration=300.0,
    )
    res = run_simulation(cfg, pregenerated_requests=workload)

    up_events = [e for e in res.metrics.scaling_events if e.new_capacity > e.old_capacity]
    down_events = [e for e in res.metrics.scaling_events if e.new_capacity < e.old_capacity]
    assert len(up_events) >= 1
    assert len(down_events) >= 1

    last_up_done = up_events[-1].completion_time
    first_down_dec = down_events[0].decision_time
    assert (first_down_dec - last_up_done) >= 90.0 - 1e-6


def test_hybrid_strategy_follows_vertical_then_horizontal_progression() -> None:
    """Hybrid strategy must first upgrade Server 1 vertically (1->2) then add Server 2 (2->4)."""
    profile = (
        TrafficSegment(0.0, 120.0, 6.0, "Normal"),
        TrafficSegment(120.0, 300.0, 20.0, "Spike"),
    )
    workload = generate_workload(traffic_profile=profile, seed=42)
    cfg = SimulationConfig(
        strategy="hybrid",
        traffic_profile=profile,
        simulation_duration=300.0,
    )
    res = run_simulation(cfg, pregenerated_requests=workload)
    events = res.metrics.scaling_events

    assert len(events) >= 2
    assert events[0].action_type == "scale_up_hybrid_vertical"
    assert events[0].old_capacity == pytest.approx(1.0)
    assert events[0].new_capacity == pytest.approx(2.0)
    assert events[0].active_servers_after == 1

    assert events[1].action_type == "scale_up_hybrid_horizontal"
    assert events[1].old_capacity == pytest.approx(2.0)
    assert events[1].new_capacity == pytest.approx(4.0)
    assert events[1].active_servers_after == 2


