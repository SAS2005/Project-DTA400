"""Automated unit tests for ServerPool processing, concurrency, and state transitions."""

from __future__ import annotations

import pytest
import simpy

from server import RequestQueue, ServerPool, ServerState
from workload import Request


def test_service_duration_scales_linearly_with_capacity() -> None:
    """Service duration must equal cpu_work / server.capacity."""
    for cap, expected_dt in [(1.0, 0.35), (2.0, 0.175), (4.0, 0.0875)]:
        env = simpy.Environment()
        q = RequestQueue(env)
        pool = ServerPool(env, q, initial_servers=1, initial_capacity_per_server=cap)

        req = Request(request_id=1, arrival_time=0.0, request_class="heavy", cpu_work=0.35)
        q.push(req)
        pool.dispatch()
        env.run()

        assert req.service_start_time == pytest.approx(0.0)
        assert req.completion_time == pytest.approx(expected_dt)
        assert req.processing_time == pytest.approx(expected_dt)


def test_concurrent_execution_across_multiple_horizontal_servers() -> None:
    """Two active servers must execute two requests concurrently without queueing delay."""
    env = simpy.Environment()
    q = RequestQueue(env)
    pool = ServerPool(env, q, initial_servers=2, initial_capacity_per_server=1.0)

    r1 = Request(1, 0.0, "heavy", 0.35)
    r2 = Request(2, 0.0, "heavy", 0.35)
    r3 = Request(3, 0.0, "small", 0.05)

    q.push(r1)
    q.push(r2)
    q.push(r3)
    pool.dispatch()
    env.run()

    # r1 and r2 start immediately at t=0.0 on servers 1 and 2
    assert r1.service_start_time == pytest.approx(0.0)
    assert r2.service_start_time == pytest.approx(0.0)
    assert r1.server_id != r2.server_id
    # r3 waits until t=0.35 when a server becomes free
    assert r3.service_start_time == pytest.approx(0.35)
    assert r3.waiting_time == pytest.approx(0.35)
    assert r3.completion_time == pytest.approx(0.40)


def test_vertical_upgrade_applies_to_subsequent_requests_after_delay() -> None:
    """Vertical capacity upgrade must take effect after upgrade_delay for future jobs."""
    env = simpy.Environment()
    q = RequestQueue(env)
    pool = ServerPool(env, q, initial_servers=1, initial_capacity_per_server=1.0)
    srv = pool.servers[0]

    # Start upgrade to capacity 2.0 at t=0 with 5.0 s upgrade delay
    ok = pool.start_vertical_upgrade(srv, new_capacity=2.0, upgrade_delay=5.0)
    assert ok is True
    assert srv.capacity == pytest.approx(1.0)
    assert pool.provisioning_capacity == pytest.approx(1.0)

    # Job arriving at t=1.0 runs at capacity 1.0
    r_before = Request(1, 1.0, "heavy", 0.35)
    env.run(until=1.0)
    q.push(r_before)
    pool.dispatch()
    env.run()

    assert float(env.now) == pytest.approx(5.0)
    assert r_before.completion_time == pytest.approx(1.35)
    assert srv.capacity == pytest.approx(2.0)
    assert pool.provisioning_capacity == pytest.approx(0.0)

    # Job arriving at t=6.0 runs at upgraded capacity 2.0 (takes 0.175 s)
    r_after = Request(2, 6.0, "heavy", 0.35)
    env.run(until=6.0)
    q.push(r_after)
    pool.dispatch()
    env.run()

    assert r_after.processing_time == pytest.approx(0.175)


def test_booting_server_does_not_accept_work_before_startup_completes() -> None:
    """A booting horizontal server must not process requests until startup delay elapses."""
    env = simpy.Environment()
    q = RequestQueue(env)
    pool = ServerPool(env, q, initial_servers=1, initial_capacity_per_server=1.0)

    # Keep server 1 busy from t=0 to t=15
    r_long = Request(1, 0.0, "custom", 15.0)
    q.push(r_long)
    pool.dispatch()

    # Start booting server 2 at t=0 with 10 s startup delay
    srv2 = pool.start_horizontal_scale_up(target_server_capacity=1.0, cold_startup_delay=10.0)
    assert srv2 is not None
    assert srv2.state == ServerState.BOOTING

    # Request 2 arrives at t=2.0; must wait until server 2 finishes booting at t=10.0
    r_queued = Request(2, 2.0, "medium", 0.15)
    env.run(until=2.0)
    q.push(r_queued)
    pool.dispatch()

    env.run(until=9.9)
    assert r_queued.service_start_time is None
    assert srv2.state == ServerState.BOOTING

    env.run()
    assert srv2.state == ServerState.ACTIVE
    assert r_queued.service_start_time == pytest.approx(10.0)
    assert r_queued.completion_time == pytest.approx(10.15)


def test_safe_scale_down_drains_running_request_and_supports_standby() -> None:
    """Scale-down must never abort an in-flight request and must transition cleanly to STANDBY."""
    env = simpy.Environment()
    q = RequestQueue(env)
    pool = ServerPool(env, q, initial_servers=2, initial_capacity_per_server=1.0)

    # Put both servers to work at t=0
    r1 = Request(1, 0.0, "heavy", 0.35)
    r2 = Request(2, 0.0, "heavy", 0.35)
    q.push(r1)
    q.push(r2)
    pool.dispatch()

    env.run(until=0.10)
    # Request scale-down to STANDBY while both servers are busy
    draining_srv = pool.start_horizontal_scale_down(to_standby=True)
    assert draining_srv is not None
    assert draining_srv.state == ServerState.DRAINING
    assert draining_srv.busy is True

    # Complete execution at t=0.35
    env.run()
    assert r1.completion_time == pytest.approx(0.35)
    assert r2.completion_time == pytest.approx(0.35)
    assert draining_srv.state == ServerState.STANDBY
    assert len(pool.standby_servers) == 1
    assert len(pool.strictly_active_servers) == 1

    # Resuming from STANDBY uses standby_startup_delay (2.0 s)
    t_resume_start = float(env.now)
    resumed = pool.start_horizontal_scale_up(
        target_server_capacity=1.0,
        cold_startup_delay=10.0,
        standby_startup_delay=2.0,
    )
    assert resumed is draining_srv
    env.run()
    assert float(env.now) - t_resume_start == pytest.approx(2.0)
    assert resumed.state == ServerState.ACTIVE
