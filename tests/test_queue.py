"""Automated unit tests for the centralized FIFO RequestQueue (Component 2)."""

from __future__ import annotations

import pytest
import simpy

from server import RequestQueue
from workload import Request


def test_fifo_dispatch_order_and_timestamps() -> None:
    """RequestQueue must preserve strict First-In, First-Out ordering and record entry times."""
    env = simpy.Environment()
    queue = RequestQueue(env)

    r1 = Request(request_id=1, arrival_time=1.0, request_class="small", cpu_work=0.05)
    r2 = Request(request_id=2, arrival_time=2.5, request_class="medium", cpu_work=0.15)
    r3 = Request(request_id=3, arrival_time=4.0, request_class="heavy", cpu_work=0.35)

    env.run(until=1.0)
    queue.push(r1)
    env.run(until=2.5)
    queue.push(r2)
    env.run(until=4.0)
    queue.push(r3)

    assert len(queue) == 3
    assert queue.max_length == 3
    assert queue.total_enqueued == 3
    assert r1.queue_entry_time == pytest.approx(1.0)
    assert r2.queue_entry_time == pytest.approx(2.5)
    assert r3.queue_entry_time == pytest.approx(4.0)

    out1 = queue.pop()
    out2 = queue.pop()
    out3 = queue.pop()
    out4 = queue.pop()

    assert out1 is not None and out1.request_id == 1
    assert out2 is not None and out2.request_id == 2
    assert out3 is not None and out3.request_id == 3
    assert out4 is None
    assert len(queue) == 0
    assert queue.total_dequeued == 3


def test_time_weighted_queue_length_calculation() -> None:
    """Time-weighted queue length must integrate exact continuous-time queue occupancy."""
    env = simpy.Environment()
    queue = RequestQueue(env)

    # [0, 2): length = 0 -> area = 0
    # [2, 5): push 2 items -> length = 2 for 3s -> area = 6
    # [5, 9): pop 1 item -> length = 1 for 4s -> area = 4
    # [9, 10): pop 1 item -> length = 0 for 1s -> area = 0
    # Total area over 10s = 10 -> time-weighted mean = 1.0
    env.run(until=2.0)
    queue.push(Request(1, 2.0, "small", 0.05))
    queue.push(Request(2, 2.0, "small", 0.05))

    env.run(until=5.0)
    queue.pop()

    env.run(until=9.0)
    queue.pop()

    env.run(until=10.0)
    assert queue.area_queue_time == pytest.approx(10.0, abs=1e-9)
    assert queue.time_weighted_average() == pytest.approx(1.0, abs=1e-9)
