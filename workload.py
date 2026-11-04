"""Workload data model and seeded piecewise-Poisson traffic generator.

Generates deterministic, repeatable HTTP-style request workloads independently
of scaling policies so that identical request sequences can be replayed across
Vertical, Horizontal, Hybrid, and Static strategies in paired comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence
import numpy as np
import simpy

from config import (
    DEFAULT_REQUEST_CLASSES,
    VARIABLE_BASELINE_PROFILE,
    RequestClassSpec,
    TrafficSegment,
)


@dataclass
class Request:
    """Represents a single incoming web application request."""

    request_id: int
    arrival_time: float
    request_class: str
    cpu_work: float
    segment_label: str = ""

    # Populated during simulation execution
    queue_entry_time: Optional[float] = None
    service_start_time: Optional[float] = None
    completion_time: Optional[float] = None
    server_id: Optional[int] = None
    server_capacity_at_start: Optional[float] = None

    @property
    def waiting_time(self) -> Optional[float]:
        """Time spent waiting in the FIFO queue before service begins."""
        if self.service_start_time is None:
            return None
        return self.service_start_time - self.arrival_time

    @property
    def processing_time(self) -> Optional[float]:
        """Time spent actively executing on a server instance."""
        if self.completion_time is None or self.service_start_time is None:
            return None
        return self.completion_time - self.service_start_time

    @property
    def response_time(self) -> Optional[float]:
        """End-to-end latency from arrival to completion (waiting + processing)."""
        if self.completion_time is None:
            return None
        return self.completion_time - self.arrival_time

    def clone(self) -> "Request":
        """Create a clean copy preserving arrival and workload identity."""
        return Request(
            request_id=self.request_id,
            arrival_time=self.arrival_time,
            request_class=self.request_class,
            cpu_work=self.cpu_work,
            segment_label=self.segment_label,
        )


def clone_workload(requests: Sequence[Request]) -> List[Request]:
    """Return a deep copy of a pre-generated request sequence for fair replay."""
    return [req.clone() for req in requests]


def generate_workload(
    traffic_profile: Sequence[TrafficSegment] = VARIABLE_BASELINE_PROFILE,
    request_classes: Sequence[RequestClassSpec] = DEFAULT_REQUEST_CLASSES,
    seed: int = 42,
    max_duration: Optional[float] = None,
) -> List[Request]:
    """Generate a sequence of requests using a piecewise-constant Poisson process.

    By the memoryless property of the homogeneous Poisson process within each
    traffic segment [start_time, end_time), inter-arrival times are drawn from
    Exp(1 / arrival_rate). Any arrival falling at or beyond segment.end_time is
    discarded and generation advances cleanly to the next segment boundary so
    an old arrival rate never leaks into a subsequent traffic period.
    """
    if not request_classes:
        raise ValueError("At least one RequestClassSpec must be provided.")

    probs = np.array([rc.probability for rc in request_classes], dtype=float)
    if not np.isclose(probs.sum(), 1.0, atol=1e-6):
        raise ValueError(f"Request class probabilities must sum to 1.0, got {probs.sum():.6f}")
    probs = probs / probs.sum()

    rng = np.random.default_rng(seed)
    requests: List[Request] = []
    next_id = 1

    for segment in traffic_profile:
        seg_start = segment.start_time
        seg_end = segment.end_time
        if max_duration is not None:
            if seg_start >= max_duration:
                break
            seg_end = min(seg_end, max_duration)

        rate = segment.arrival_rate
        if rate <= 0.0 or seg_end <= seg_start:
            continue

        current_time = seg_start
        mean_interarrival = 1.0 / rate

        while True:
            dt = float(rng.exponential(scale=mean_interarrival))
            current_time += dt
            if current_time >= seg_end:
                # Boundary reached: do not emit an arrival past seg_end using old rate
                break

            class_idx = int(rng.choice(len(request_classes), p=probs))
            rc = request_classes[class_idx]
            requests.append(
                Request(
                    request_id=next_id,
                    arrival_time=current_time,
                    request_class=rc.name,
                    cpu_work=rc.cpu_work,
                    segment_label=segment.label,
                )
            )
            next_id += 1

    return requests


class TrafficGenerator:
    """SimPy process component that injects pre-generated requests at arrival_time."""

    def __init__(
        self,
        env: simpy.Environment,
        requests: Sequence[Request],
        on_arrival: Callable[[Request], None],
    ) -> None:
        self.env = env
        self.requests = clone_workload(requests)
        self.on_arrival = on_arrival
        self.generated_count = 0
        self.process = env.process(self._run())

    def _run(self):
        for req in self.requests:
            delay = req.arrival_time - self.env.now
            if delay > 0.0:
                yield self.env.timeout(delay)
            self.generated_count += 1
            self.on_arrival(req)
