"""Automated unit tests for the normalized operating cost model (Component 5)."""

from __future__ import annotations

import pytest
import simpy

from config import AutoscalingConfig, SimulationConfig
from metrics import MetricsCollector
from scaling import run_simulation
from server import RequestQueue, ServerPool
from workload import Request


def test_static_single_and_quad_server_hourly_cost() -> None:
    """A 1-hour (3,600 s) run with no queueing backlog must cost 1.0 unit on Static-1 and 4.0 on Static-4."""
    reqs = [Request(1, 10.0, "small", 0.05)]

    cfg1 = SimulationConfig(strategy="static_1", simulation_duration=3600.0)
    res1 = run_simulation(cfg1, pregenerated_requests=reqs)
    assert res1.summary.active_cost == pytest.approx(1.0, abs=1e-9)
    assert res1.summary.provisioning_cost == pytest.approx(0.0, abs=1e-9)
    assert res1.summary.standby_cost == pytest.approx(0.0, abs=1e-9)
    assert res1.summary.total_cost == pytest.approx(1.0, abs=1e-9)

    cfg4 = SimulationConfig(strategy="static_4", simulation_duration=3600.0)
    res4 = run_simulation(cfg4, pregenerated_requests=reqs)
    assert res4.summary.total_cost == pytest.approx(4.0, abs=1e-9)


def test_startup_standby_and_active_cost_integration_without_double_counting() -> None:
    """Verify exact continuous-time cost integration across BOOTING, ACTIVE, and STANDBY transitions."""
    env = simpy.Environment()
    q = RequestQueue(env)
    cfg = SimulationConfig(
        strategy="horizontal",
        simulation_duration=3600.0,
        autoscaling=AutoscalingConfig(enable_standby=True),
    )
    pool = ServerPool(env, q, initial_servers=1, initial_capacity_per_server=1.0)
    metrics = MetricsCollector(env, cfg, q, pool)
    pool.on_state_change = metrics.record_state_change

    # Server 1 is ACTIVE for the entire 3,600 s -> 1.00 cost unit
    # Server 2 boots at t=0 for 360 s (0.1 hr) -> provisioning_cost = 0.10 cost unit
    # Server 2 stays ACTIVE from t=360 to t=2160 (1,800 s = 0.5 hr) -> active_cost += 0.50 cost unit
    # Server 2 enters STANDBY from t=2160 to t=3600 (1,440 s = 0.4 hr @ 0.25/hr) -> standby_cost = 0.10 cost unit
    srv2 = pool.start_horizontal_scale_up(target_server_capacity=1.0, cold_startup_delay=360.0)
    assert srv2 is not None

    env.run(until=2160.0)
    pool.start_horizontal_scale_down(to_standby=True, target_server=srv2)

    env.run(until=3600.0)
    metrics.record_state_change()

    assert metrics.active_cost == pytest.approx(1.50, abs=1e-9)
    assert metrics.provisioning_cost == pytest.approx(0.10, abs=1e-9)
    assert metrics.standby_cost == pytest.approx(0.10, abs=1e-9)
    assert metrics.total_cost == pytest.approx(1.70, abs=1e-9)
