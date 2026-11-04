"""Metrics collection and continuous-time economic cost accounting (Component 5).

Tracks request latencies, time-weighted queue length, time-weighted server
utilization, scaling events, periodic time-series snapshots, and normalized
operating costs without double counting.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional
import numpy as np
import simpy

from config import SimulationConfig
from server import RequestQueue, ServerInstance, ServerPool
from workload import Request


@dataclass
class ScalingEventRecord:
    """Audit record for a single dynamic scaling transition."""

    decision_time: float
    completion_time: float
    action_type: str
    old_capacity: float
    new_capacity: float
    active_servers_after: int
    reason: str


@dataclass
class TimeSeriesPoint:
    """Periodic snapshot of system state and recent interval performance."""

    time_s: float
    arrival_rate_window: float
    throughput_window: float
    queue_length: int
    avg_queue_length_window: float
    utilization_window: float
    active_servers: int
    standby_servers: int
    booting_servers: int
    active_capacity: float
    provisioning_capacity: float
    standby_capacity: float
    cumulative_cost: float
    mean_response_time_window: float
    p95_response_time_window: float


@dataclass
class SimulationSummary:
    """Aggregated performance and economic metrics for one simulation run."""

    strategy: str
    scenario_name: str
    seed: int
    simulation_duration_s: float
    last_arrival_time_s: float
    last_completion_time_s: float
    total_elapsed_s: float
    drain_duration_s: float
    generated_requests: int
    completed_requests: int
    completed_in_window_requests: int
    completed_in_drain_requests: int
    unfinished_requests: int
    avg_response_time_s: float
    p50_response_time_s: float
    p95_response_time_s: float
    p99_response_time_s: float
    max_response_time_s: float
    avg_waiting_time_s: float
    p95_waiting_time_s: float
    avg_processing_time_s: float
    arrival_window_throughput_req_per_s: float
    end_to_end_completion_rate_req_per_s: float
    throughput_req_per_s: float
    avg_queue_length: float
    max_queue_length: int
    avg_utilization: float
    avg_active_servers: float
    avg_active_capacity: float
    scale_up_count: int
    scale_down_count: int
    total_scaling_events: int
    active_cost: float
    provisioning_cost: float
    standby_cost: float
    total_cost: float
    cost_per_1k_requests: float
    cost_per_request: float
    slo_target_s: float
    slo_met: bool
    slo_035_met: bool
    slo_violation_fraction: float

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class MetricsCollector:
    """Observes simulation events and computes exact continuous-time integrals."""

    def __init__(
        self,
        env: simpy.Environment,
        config: SimulationConfig,
        queue: RequestQueue,
        pool: ServerPool,
    ) -> None:
        self.env = env
        self.config = config
        self.queue = queue
        self.pool = pool

        # Request tracking
        self.arrived_requests: List[Request] = []
        self.completed_requests: List[Request] = []
        self._window_arrivals: int = 0
        self._window_completions: List[Request] = []

        # Continuous-time state integrals
        self._last_state_time: float = 0.0
        self._prev_busy_cap: float = pool.busy_capacity
        self._prev_active_cap: float = pool.active_capacity
        self._prev_prov_cap: float = pool.provisioning_capacity
        self._prev_standby_cap: float = pool.standby_capacity
        self._prev_active_servers: int = len(pool.active_servers)

        self.busy_capacity_seconds: float = 0.0
        self.available_capacity_seconds: float = 0.0
        self.provisioning_capacity_seconds: float = 0.0
        self.standby_capacity_seconds: float = 0.0
        self.active_server_seconds: float = 0.0

        # Window-specific tracking for time-series and autoscaler queries
        self._ts_last_time: float = 0.0
        self._ts_last_busy_cap_sec: float = 0.0
        self._ts_last_avail_cap_sec: float = 0.0
        self._ts_last_queue_area: float = 0.0

        self._mon_last_busy_cap_sec: float = 0.0
        self._mon_last_avail_cap_sec: float = 0.0
        self._mon_last_queue_area: float = 0.0
        self._mon_last_time: float = 0.0

        self.scaling_events: List[ScalingEventRecord] = []
        self.time_series: List[TimeSeriesPoint] = []

    def record_state_change(self) -> None:
        """Integrate server capacity and state durations up to env.now."""
        now = float(self.env.now)
        dt = now - self._last_state_time
        if dt > 0.0:
            self.busy_capacity_seconds += self._prev_busy_cap * dt
            self.available_capacity_seconds += self._prev_active_cap * dt
            self.provisioning_capacity_seconds += self._prev_prov_cap * dt
            self.standby_capacity_seconds += self._prev_standby_cap * dt
            self.active_server_seconds += self._prev_active_servers * dt
            self._last_state_time = now

        self._prev_busy_cap = self.pool.busy_capacity
        self._prev_active_cap = self.pool.active_capacity
        self._prev_prov_cap = self.pool.provisioning_capacity
        self._prev_standby_cap = self.pool.standby_capacity
        self._prev_active_servers = len(self.pool.active_servers)

    def on_request_arrival(self, request: Request) -> None:
        self.arrived_requests.append(request)
        self._window_arrivals += 1

    def on_request_start(self, request: Request, server: ServerInstance) -> None:
        pass

    def on_request_complete(self, request: Request, server: ServerInstance) -> None:
        self.completed_requests.append(request)
        self._window_completions.append(request)

    def log_scaling_event(
        self,
        decision_time: float,
        completion_time: float,
        action_type: str,
        old_capacity: float,
        new_capacity: float,
        active_servers_after: int,
        reason: str,
    ) -> None:
        self.scaling_events.append(
            ScalingEventRecord(
                decision_time=decision_time,
                completion_time=completion_time,
                action_type=action_type,
                old_capacity=old_capacity,
                new_capacity=new_capacity,
                active_servers_after=active_servers_after,
                reason=reason,
            )
        )

    def poll_autoscaler_window_metrics(self) -> Tuple[float, float]:
        """Return (window_utilization, window_avg_queue_length) since last autoscaler poll."""
        self.record_state_change()
        now = float(self.env.now)
        dt = now - self._mon_last_time

        d_busy = self.busy_capacity_seconds - self._mon_last_busy_cap_sec
        d_avail = self.available_capacity_seconds - self._mon_last_avail_cap_sec
        q_area = self.queue.area_queue_time
        d_q_area = q_area - self._mon_last_queue_area

        self._mon_last_busy_cap_sec = self.busy_capacity_seconds
        self._mon_last_avail_cap_sec = self.available_capacity_seconds
        self._mon_last_queue_area = q_area
        self._mon_last_time = now

        util = (d_busy / d_avail) if d_avail > 0.0 else 0.0
        util = float(np.clip(util, 0.0, 1.0))
        avg_q = (d_q_area / dt) if dt > 0.0 else float(len(self.queue))
        return util, avg_q

    @property
    def active_cost(self) -> float:
        self.record_state_change()
        return (self.available_capacity_seconds / 3600.0) * self.config.cost.active_cost_per_unit_hour

    @property
    def provisioning_cost(self) -> float:
        self.record_state_change()
        return (
            self.provisioning_capacity_seconds / 3600.0
        ) * self.config.cost.provisioning_cost_per_unit_hour

    @property
    def standby_cost(self) -> float:
        self.record_state_change()
        return (self.standby_capacity_seconds / 3600.0) * self.config.cost.standby_cost_per_unit_hour

    @property
    def total_cost(self) -> float:
        return self.active_cost + self.provisioning_cost + self.standby_cost

    def record_time_series_point(self) -> None:
        """Capture a snapshot for plotting at the end of a sampling window."""
        self.record_state_change()
        now = float(self.env.now)
        dt = now - self._ts_last_time

        d_busy = self.busy_capacity_seconds - self._ts_last_busy_cap_sec
        d_avail = self.available_capacity_seconds - self._ts_last_avail_cap_sec
        q_area = self.queue.area_queue_time
        d_q_area = q_area - self._ts_last_queue_area

        util_win = (d_busy / d_avail) if d_avail > 0.0 else 0.0
        util_win = float(np.clip(util_win, 0.0, 1.0))
        avg_q_win = (d_q_area / dt) if dt > 0.0 else float(len(self.queue))
        arr_rate = (self._window_arrivals / dt) if dt > 0.0 else 0.0
        tput_win = (len(self._window_completions) / dt) if dt > 0.0 else 0.0

        if self._window_completions:
            rts = [r.response_time for r in self._window_completions if r.response_time is not None]
            mean_rt = float(np.mean(rts)) if rts else 0.0
            p95_rt = float(np.percentile(rts, 95)) if rts else 0.0
        else:
            mean_rt = 0.0
            p95_rt = 0.0

        self.time_series.append(
            TimeSeriesPoint(
                time_s=now,
                arrival_rate_window=arr_rate,
                throughput_window=tput_win,
                queue_length=len(self.queue),
                avg_queue_length_window=avg_q_win,
                utilization_window=util_win,
                active_servers=len(self.pool.active_servers),
                standby_servers=len(self.pool.standby_servers),
                booting_servers=len(self.pool.booting_servers),
                active_capacity=self.pool.active_capacity,
                provisioning_capacity=self.pool.provisioning_capacity,
                standby_capacity=self.pool.standby_capacity,
                cumulative_cost=self.total_cost,
                mean_response_time_window=mean_rt,
                p95_response_time_window=p95_rt,
            )
        )

        self._ts_last_time = now
        self._ts_last_busy_cap_sec = self.busy_capacity_seconds
        self._ts_last_avail_cap_sec = self.available_capacity_seconds
        self._ts_last_queue_area = q_area
        self._window_arrivals = 0
        self._window_completions.clear()

    def build_summary(self, generated_count: int) -> SimulationSummary:
        """Compute final summary statistics at the conclusion of the simulation."""
        self.record_state_change()
        total_elapsed = max(float(self.env.now), self.config.simulation_duration)
        drain_duration = max(0.0, float(self.env.now) - self.config.simulation_duration)

        completed_n = len(self.completed_requests)
        unfinished_n = max(0, generated_count - completed_n)

        last_arrival_t = (
            float(max(r.arrival_time for r in self.arrived_requests))
            if self.arrived_requests
            else 0.0
        )
        last_completion_t = (
            float(
                max(
                    r.completion_time
                    for r in self.completed_requests
                    if r.completion_time is not None
                )
            )
            if self.completed_requests
            else 0.0
        )

        completed_in_window_n = sum(
            1
            for r in self.completed_requests
            if r.completion_time is not None
            and r.completion_time <= self.config.simulation_duration + 1e-9
        )
        completed_in_drain_n = max(0, completed_n - completed_in_window_n)

        rts = np.array(
            [r.response_time for r in self.completed_requests if r.response_time is not None],
            dtype=float,
        )
        wts = np.array(
            [r.waiting_time for r in self.completed_requests if r.waiting_time is not None],
            dtype=float,
        )
        pts = np.array(
            [r.processing_time for r in self.completed_requests if r.processing_time is not None],
            dtype=float,
        )

        if len(rts) > 0:
            avg_rt = float(np.mean(rts))
            p50_rt = float(np.percentile(rts, 50))
            p95_rt = float(np.percentile(rts, 95))
            p99_rt = float(np.percentile(rts, 99))
            max_rt = float(np.max(rts))
            slo_viol = float(np.mean(rts > self.config.slo_p95_target))
        else:
            avg_rt = p50_rt = p95_rt = p99_rt = max_rt = slo_viol = 0.0

        if len(wts) > 0:
            avg_wt = float(np.mean(wts))
            p95_wt = float(np.percentile(wts, 95))
        else:
            avg_wt = p95_wt = 0.0

        avg_pt = float(np.mean(pts)) if len(pts) > 0 else 0.0

        arrival_window_tput = (
            completed_in_window_n / self.config.simulation_duration
            if self.config.simulation_duration > 0.0
            else 0.0
        )
        end_to_end_rate = (
            completed_n / total_elapsed
            if total_elapsed > 0.0
            else 0.0
        )
        throughput = arrival_window_tput

        avg_q = self.queue.time_weighted_average(total_duration=total_elapsed)
        avg_util = (
            self.busy_capacity_seconds / self.available_capacity_seconds
            if self.available_capacity_seconds > 0.0
            else 0.0
        )
        avg_util = float(np.clip(avg_util, 0.0, 1.0))

        avg_servers = self.active_server_seconds / total_elapsed if total_elapsed > 0.0 else 0.0
        avg_cap = self.available_capacity_seconds / total_elapsed if total_elapsed > 0.0 else 0.0

        scale_ups = sum(1 for e in self.scaling_events if e.new_capacity > e.old_capacity)
        scale_downs = sum(1 for e in self.scaling_events if e.new_capacity < e.old_capacity)

        act_cost = self.active_cost
        prov_cost = self.provisioning_cost
        stby_cost = self.standby_cost
        tot_cost = act_cost + prov_cost + stby_cost

        cost_per_req = (tot_cost / completed_n) if completed_n > 0 else 0.0
        cost_per_1k = cost_per_req * 1000.0

        slo_met = bool(
            completed_n > 0
            and unfinished_n == 0
            and p95_rt <= self.config.slo_p95_target
        )
        slo_035_met = bool(
            completed_n > 0
            and unfinished_n == 0
            and p95_rt <= 0.35
        )

        return SimulationSummary(
            strategy=self.config.strategy,
            scenario_name=self.config.scenario_name,
            seed=self.config.random_seed,
            simulation_duration_s=self.config.simulation_duration,
            last_arrival_time_s=last_arrival_t,
            last_completion_time_s=last_completion_t,
            total_elapsed_s=total_elapsed,
            drain_duration_s=drain_duration,
            generated_requests=generated_count,
            completed_requests=completed_n,
            completed_in_window_requests=completed_in_window_n,
            completed_in_drain_requests=completed_in_drain_n,
            unfinished_requests=unfinished_n,
            avg_response_time_s=avg_rt,
            p50_response_time_s=p50_rt,
            p95_response_time_s=p95_rt,
            p99_response_time_s=p99_rt,
            max_response_time_s=max_rt,
            avg_waiting_time_s=avg_wt,
            p95_waiting_time_s=p95_wt,
            avg_processing_time_s=avg_pt,
            arrival_window_throughput_req_per_s=arrival_window_tput,
            end_to_end_completion_rate_req_per_s=end_to_end_rate,
            throughput_req_per_s=throughput,
            avg_queue_length=avg_q,
            max_queue_length=self.queue.max_length,
            avg_utilization=avg_util,
            avg_active_servers=avg_servers,
            avg_active_capacity=avg_cap,
            scale_up_count=scale_ups,
            scale_down_count=scale_downs,
            total_scaling_events=len(self.scaling_events),
            active_cost=act_cost,
            provisioning_cost=prov_cost,
            standby_cost=stby_cost,
            total_cost=tot_cost,
            cost_per_1k_requests=cost_per_1k,
            cost_per_request=cost_per_req,
            slo_target_s=self.config.slo_p95_target,
            slo_met=slo_met,
            slo_035_met=slo_035_met,
            slo_violation_fraction=slo_viol,
        )
