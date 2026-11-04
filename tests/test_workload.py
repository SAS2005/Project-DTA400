"""Automated unit tests for workload generation and TrafficGenerator (Component 1)."""

from __future__ import annotations

import numpy as np
import pytest
import simpy

from config import DEFAULT_REQUEST_CLASSES, TrafficSegment, VARIABLE_BASELINE_PROFILE
from workload import TrafficGenerator, clone_workload, generate_workload


def test_deterministic_seed_behavior() -> None:
    """Identical random seeds must produce identical request sequences."""
    w1 = generate_workload(seed=101)
    w2 = generate_workload(seed=101)
    w3 = generate_workload(seed=202)

    assert len(w1) == len(w2)
    for r1, r2 in zip(w1, w2):
        assert r1.request_id == r2.request_id
        assert r1.arrival_time == pytest.approx(r2.arrival_time, abs=1e-12)
        assert r1.request_class == r2.request_class
        assert r1.cpu_work == pytest.approx(r2.cpu_work, abs=1e-12)

    # Different seed produces a different sequence
    assert len(w1) != len(w3) or w1[0].arrival_time != w3[0].arrival_time


def test_unique_sequential_ids_and_monotonic_arrivals() -> None:
    """Every generated request must have a unique sequential ID and valid timestamp."""
    workload = generate_workload(seed=42)
    assert len(workload) > 20000

    ids = [r.request_id for r in workload]
    assert ids == list(range(1, len(workload) + 1))

    times = [r.arrival_time for r in workload]
    assert all(0.0 <= t < 3600.0 for t in times)
    assert all(times[i] <= times[i + 1] for i in range(len(times) - 1))


def test_traffic_segment_boundaries_respected() -> None:
    """Requests must not leak across segment boundaries using an old arrival rate."""
    profile = (
        TrafficSegment(0.0, 100.0, 10.0, "High"),
        TrafficSegment(100.0, 200.0, 0.0, "Zero"),
        TrafficSegment(200.0, 300.0, 5.0, "Moderate"),
    )
    workload = generate_workload(traffic_profile=profile, seed=7)

    in_seg1 = [r for r in workload if r.arrival_time < 100.0]
    in_seg2 = [r for r in workload if 100.0 <= r.arrival_time < 200.0]
    in_seg3 = [r for r in workload if 200.0 <= r.arrival_time < 300.0]

    assert len(in_seg1) > 800
    assert len(in_seg2) == 0  # Zero arrival rate segment must contain 0 arrivals
    assert len(in_seg3) > 350
    assert all(r.segment_label == "High" for r in in_seg1)
    assert all(r.segment_label == "Moderate" for r in in_seg3)


def test_request_class_probabilities_and_cpu_work() -> None:
    """Request class proportions must match 50% Small, 35% Medium, 15% Heavy within tolerance."""
    workload = generate_workload(
        traffic_profile=VARIABLE_BASELINE_PROFILE,
        request_classes=DEFAULT_REQUEST_CLASSES,
        seed=42,
    )
    n = len(workload)
    counts = {"small": 0, "medium": 0, "heavy": 0}
    work_map = {"small": 0.05, "medium": 0.15, "heavy": 0.35}

    for r in workload:
        counts[r.request_class] += 1
        assert r.cpu_work == pytest.approx(work_map[r.request_class], abs=1e-9)

    assert counts["small"] / n == pytest.approx(0.50, abs=0.015)
    assert counts["medium"] / n == pytest.approx(0.35, abs=0.015)
    assert counts["heavy"] / n == pytest.approx(0.15, abs=0.015)


def test_clone_workload_isolation() -> None:
    """Mutating execution timestamps on a cloned workload must not affect the original."""
    orig = generate_workload(
        traffic_profile=(TrafficSegment(0.0, 10.0, 2.0, "Short"),),
        seed=11,
    )
    cloned = clone_workload(orig)
    cloned[0].service_start_time = 1.23
    cloned[0].completion_time = 1.45

    assert orig[0].service_start_time is None
    assert orig[0].completion_time is None
    assert cloned[0].waiting_time == pytest.approx(1.23 - cloned[0].arrival_time)
    assert cloned[0].processing_time == pytest.approx(1.45 - 1.23)
    assert cloned[0].response_time == pytest.approx(1.45 - cloned[0].arrival_time)


def test_simpy_traffic_generator_arrival_timing() -> None:
    """TrafficGenerator must inject requests into SimPy at their exact arrival_time."""
    profile = (TrafficSegment(0.0, 20.0, 2.0, "Test"),)
    reqs = generate_workload(traffic_profile=profile, seed=99)
    env = simpy.Environment()
    observed_times = []

    def _on_arrival(r):
        observed_times.append((r.request_id, float(env.now), r.arrival_time))

    gen = TrafficGenerator(env, reqs, on_arrival=_on_arrival)
    env.run(until=25.0)

    assert gen.generated_count == len(reqs)
    assert len(observed_times) == len(reqs)
    for req_id, sim_now, target_t in observed_times:
        assert sim_now == pytest.approx(target_t, abs=1e-12)
