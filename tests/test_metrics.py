"""Automated unit tests for performance metrics calculation (Component 5)."""

from __future__ import annotations

import numpy as np
import pytest

from config import SimulationConfig, TrafficSegment
from scaling import run_simulation
from workload import Request


def test_response_time_waiting_time_and_p95_exactness() -> None:
    """Mean, P50, P95, waiting time, and processing time must match exact analytical values."""
    # Construct 20 deterministic requests spaced far apart so waiting_time == 0
    reqs = [
        Request(
            request_id=i + 1,
            arrival_time=float(i * 2.0),
            request_class="custom",
            cpu_work=0.05 * (i + 1),  # 0.05, 0.10, ..., 1.00 s
        )
        for i in range(20)
    ]
    cfg = SimulationConfig(
        strategy="static_1",
        simulation_duration=45.0,
        slo_p95_target=0.90,
    )
    res = run_simulation(cfg, pregenerated_requests=reqs)
    s = res.summary

    expected_rts = np.array([0.05 * (i + 1) for i in range(20)], dtype=float)
    assert s.completed_requests == 20
    assert s.unfinished_requests == 0
    assert s.avg_waiting_time_s == pytest.approx(0.0, abs=1e-9)
    assert s.avg_processing_time_s == pytest.approx(float(np.mean(expected_rts)), abs=1e-9)
    assert s.avg_response_time_s == pytest.approx(float(np.mean(expected_rts)), abs=1e-9)
    assert s.p50_response_time_s == pytest.approx(float(np.percentile(expected_rts, 50)), abs=1e-9)
    assert s.p95_response_time_s == pytest.approx(float(np.percentile(expected_rts, 95)), abs=1e-9)
    assert s.throughput_req_per_s == pytest.approx(20.0 / 45.0, abs=1e-9)
    # 95th percentile of [0.05..1.00] is ~0.9525 > 0.90 -> slo_met is False
    assert s.slo_met is False


def test_utilization_is_mathematically_valid_and_bounded() -> None:
    """Time-weighted utilization must equal total CPU work / available capacity-seconds."""
    # 100 requests of 0.20 CPU-s each = 20.0 CPU-seconds over a 100.0 s simulation on 1-unit server
    reqs = [
        Request(request_id=i + 1, arrival_time=float(i * 1.0), request_class="custom", cpu_work=0.20)
        for i in range(100)
    ]
    cfg = SimulationConfig(strategy="static_1", simulation_duration=100.0)
    res = run_simulation(cfg, pregenerated_requests=reqs)

    assert 0.0 <= res.summary.avg_utilization <= 1.0
    assert res.summary.avg_utilization == pytest.approx(20.0 / 100.0, abs=1e-6)


