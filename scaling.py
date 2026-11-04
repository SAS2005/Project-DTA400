"""Autoscaling control policies (Component 4) and simulation execution engine.

Implements Vertical, Horizontal, Hybrid, and Static scaling strategies with:
- Periodic window-integrated utilization and sustained queue monitoring
- Cold-start delays (horizontal boot) and vertical upgrade delays
- Cooldown enforcement and duplicate-action prevention
- Warm standby resumption and configurable scale-down observation windows
- Post-arrival drain handling so no requests are silently dropped
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence
import simpy

from config import SimulationConfig
from metrics import MetricsCollector, SimulationSummary
from server import RequestQueue, ServerInstance, ServerPool, ServerState
from workload import Request, TrafficGenerator, clone_workload, generate_workload


@dataclass
class SimulationResult:
    """Complete output of a single simulation run."""

    config: SimulationConfig
    summary: SimulationSummary
    metrics: MetricsCollector
    requests: List[Request]


class Autoscaler:
    """Monitors workload and server utilization and triggers capacity adjustments."""

    def __init__(
        self,
        env: simpy.Environment,
        config: SimulationConfig,
        queue: RequestQueue,
        pool: ServerPool,
        metrics: MetricsCollector,
    ) -> None:
        self.env = env
        self.config = config
        self.auto_cfg = config.autoscaling
        self.queue = queue
        self.pool = pool
        self.metrics = metrics

        self.strategy = config.strategy.lower()
        self.consecutive_queue_samples: int = 0
        self.low_util_duration: float = 0.0
        self.last_scaling_completed_time: float = -1e9
        self.last_scale_up_completed_time: float = -1e9
        self.last_scale_down_completed_time: float = -1e9

        if not self.strategy.startswith("static"):
            self.process = env.process(self._monitor_loop())

    def _in_cooldown(self, for_scale_up: bool = False) -> bool:
        if self.auto_cfg.scaling_cooldown <= 0.0:
            return False
        now = float(self.env.now)
        if for_scale_up:
            # Cooldown between consecutive scale-up actions prevents over-scaling
            # before newly provisioned capacity has stabilized. A previous scale-down
            # does not block scaling back up if a new traffic spike arrives.
            return (now - self.last_scale_up_completed_time) < (
                self.auto_cfg.scaling_cooldown - 1e-9
            )
        # Scale-down respects cooldown from BOTH the last scale-up and last scale-down
        return (now - self.last_scaling_completed_time) < (
            self.auto_cfg.scaling_cooldown - 1e-9
        )

    def _monitor_loop(self):
        interval = self.auto_cfg.monitoring_interval
        while float(self.env.now) + interval <= self.config.simulation_duration + 1e-9:
            yield self.env.timeout(interval)
            self._evaluate_and_scale(interval)

    def _evaluate_and_scale(self, interval: float) -> None:
        window_util, window_avg_q = self.metrics.poll_autoscaler_window_metrics()
        current_q = len(self.queue)

        # Check sustained queue buildup condition:
        # Require nonempty waiting queue (>= scale_up_queue_threshold) AND
        # non-trivial time-averaged queue over the monitoring window (>= 1.0)
        if (
            current_q >= self.auto_cfg.scale_up_queue_threshold
            and window_avg_q >= 1.0
        ) or window_avg_q >= float(self.auto_cfg.scale_up_queue_threshold):
            self.consecutive_queue_samples += 1
        else:
            self.consecutive_queue_samples = 0

        sustained_queue = (
            self.consecutive_queue_samples >= self.auto_cfg.sustained_queue_samples
        )
        high_utilization = window_util >= self.auto_cfg.scale_up_utilization_threshold

        # Track sustained low utilization for scale-down observation window
        if (
            window_util <= self.auto_cfg.scale_down_utilization_threshold
            and current_q == 0
            and window_avg_q < 0.5
        ):
            self.low_util_duration += interval
        else:
            self.low_util_duration = 0.0

        # Do not issue new scaling operations while one is already in progress
        if self.pool.has_pending_scaling:
            return

        # Check Scale-Up Trigger
        if high_utilization or sustained_queue:
            # Allow multi-tier scale-up during severe overload once the previous boot has
            # completed and been observed for at least one full monitoring interval,
            # while respecting full scale-up cooldown for moderate load increases.
            severe_overload = window_util >= 0.95 and window_avg_q >= 2.0
            post_boot_ready = (float(self.env.now) - self.last_scale_up_completed_time) >= (
                interval - 1e-9
            )
            if not self._in_cooldown(for_scale_up=True) or (
                severe_overload and post_boot_ready
            ):
                reason = (
                    f"util={window_util:.2f}>={self.auto_cfg.scale_up_utilization_threshold:.2f}"
                    if high_utilization
                    else f"sustained_queue(q={current_q}, avg_q={window_avg_q:.1f})"
                )
                scaled = self._try_scale_up(reason, window_util, current_q)
                if scaled:
                    self.consecutive_queue_samples = 0
                    self.low_util_duration = 0.0
                    return

        # Respect full cooldown window for scale-down operations
        if self._in_cooldown(for_scale_up=False):
            return

        # Check Scale-Down Trigger
        if self.low_util_duration >= self.auto_cfg.scale_down_observation_window - 1e-9:
            reason = (
                f"low_util={window_util:.2f}<={self.auto_cfg.scale_down_utilization_threshold:.2f}"
                f"_for_{self.low_util_duration:.0f}s"
            )
            scaled = self._try_scale_down(reason)
            if scaled:
                self.low_util_duration = 0.0
                self.consecutive_queue_samples = 0

    def _try_scale_up(self, reason: str, window_util: float, current_q: int) -> bool:
        current_cap = self.pool.committed_capacity
        if current_cap >= float(self.auto_cfg.max_capacity) - 1e-9:
            return False

        decision_time = float(self.env.now)

        if self.strategy == "vertical":
            server = self.pool.strictly_active_servers[0]
            new_cap = 2.0 if server.capacity < 1.5 else float(self.auto_cfg.max_capacity)
            new_cap = min(new_cap, float(self.auto_cfg.max_capacity))
            if new_cap <= server.capacity:
                return False

            delay = self.auto_cfg.vertical_upgrade_delay
            old_cap = self.pool.active_capacity

            def _on_done(srv: ServerInstance) -> None:
                now_t = float(self.env.now)
                self.last_scaling_completed_time = now_t
                self.last_scale_up_completed_time = now_t
                self.metrics.log_scaling_event(
                    decision_time=decision_time,
                    completion_time=now_t,
                    action_type="scale_up_vertical",
                    old_capacity=old_cap,
                    new_capacity=self.pool.active_capacity,
                    active_servers_after=len(self.pool.active_servers),
                    reason=reason,
                )

            return self.pool.start_vertical_upgrade(
                server=server,
                new_capacity=new_cap,
                upgrade_delay=delay,
                on_complete=_on_done,
            )

        elif self.strategy == "horizontal":
            old_cap = self.pool.active_capacity
            from_standby = len(self.pool.standby_servers) > 0
            action_label = "scale_up_standby_resume" if from_standby else "scale_up_horizontal"

            def _on_done(srv: ServerInstance) -> None:
                now_t = float(self.env.now)
                self.last_scaling_completed_time = now_t
                self.last_scale_up_completed_time = now_t
                self.metrics.log_scaling_event(
                    decision_time=decision_time,
                    completion_time=now_t,
                    action_type=action_label,
                    old_capacity=old_cap,
                    new_capacity=self.pool.active_capacity,
                    active_servers_after=len(self.pool.active_servers),
                    reason=reason,
                )

            booted = self.pool.start_horizontal_scale_up(
                target_server_capacity=1.0,
                cold_startup_delay=self.auto_cfg.horizontal_startup_delay,
                standby_startup_delay=self.auto_cfg.standby_startup_delay,
                on_complete=_on_done,
            )
            return booted is not None

        elif self.strategy in ("hybrid", "hybrid_adaptive"):
            mode = (
                "adaptive"
                if self.strategy == "hybrid_adaptive"
                else self.auto_cfg.hybrid_mode
            )
            active_srvs = sorted(self.pool.strictly_active_servers, key=lambda s: s.server_id)
            old_cap = self.pool.active_capacity

            # Step 1: If 1 server with capacity 1.0 -> upgrade vertically to capacity 2.0
            if len(active_srvs) == 1 and active_srvs[0].capacity < 1.5:
                primary = active_srvs[0]

                def _on_v_done(srv: ServerInstance) -> None:
                    now_t = float(self.env.now)
                    self.last_scaling_completed_time = now_t
                    self.last_scale_up_completed_time = now_t
                    self.metrics.log_scaling_event(
                        decision_time=decision_time,
                        completion_time=now_t,
                        action_type="scale_up_hybrid_vertical",
                        old_capacity=old_cap,
                        new_capacity=self.pool.active_capacity,
                        active_servers_after=len(self.pool.active_servers),
                        reason=reason,
                    )

                return self.pool.start_vertical_upgrade(
                    server=primary,
                    new_capacity=2.0,
                    upgrade_delay=self.auto_cfg.vertical_upgrade_delay,
                    on_complete=_on_v_done,
                )

            # Step 2: If 1 server with capacity 2.0 -> add second server horizontally
            if len(active_srvs) == 1 and active_srvs[0].capacity >= 1.5:
                if mode == "adaptive" and not (window_util >= 0.95 and current_q >= 6):
                    second_cap = 1.0
                else:
                    second_cap = 2.0

                from_standby = len(self.pool.standby_servers) > 0
                action_label = (
                    "scale_up_hybrid_standby" if from_standby else "scale_up_hybrid_horizontal"
                )

                def _on_h_done(srv: ServerInstance) -> None:
                    now_t = float(self.env.now)
                    self.last_scaling_completed_time = now_t
                    self.last_scale_up_completed_time = now_t
                    self.metrics.log_scaling_event(
                        decision_time=decision_time,
                        completion_time=now_t,
                        action_type=action_label,
                        old_capacity=old_cap,
                        new_capacity=self.pool.active_capacity,
                        active_servers_after=len(self.pool.active_servers),
                        reason=reason,
                    )

                booted = self.pool.start_horizontal_scale_up(
                    target_server_capacity=second_cap,
                    cold_startup_delay=self.auto_cfg.horizontal_startup_delay,
                    standby_startup_delay=self.auto_cfg.standby_startup_delay,
                    on_complete=_on_h_done,
                )
                return booted is not None

            # Step 3 (Adaptive mode): If 2 servers with [2.0, 1.0] -> upgrade second server to 2.0
            if len(active_srvs) == 2:
                smaller = [s for s in active_srvs if s.capacity < 1.5]
                if smaller:
                    target_srv = smaller[0]

                    def _on_v2_done(srv: ServerInstance) -> None:
                        now_t = float(self.env.now)
                        self.last_scaling_completed_time = now_t
                        self.last_scale_up_completed_time = now_t
                        self.metrics.log_scaling_event(
                            decision_time=decision_time,
                            completion_time=now_t,
                            action_type="scale_up_hybrid_vertical",
                            old_capacity=old_cap,
                            new_capacity=self.pool.active_capacity,
                            active_servers_after=len(self.pool.active_servers),
                            reason=reason,
                        )

                    return self.pool.start_vertical_upgrade(
                        server=target_srv,
                        new_capacity=2.0,
                        upgrade_delay=self.auto_cfg.vertical_upgrade_delay,
                        on_complete=_on_v2_done,
                    )

        return False

    def _try_scale_down(self, reason: str) -> bool:
        current_cap = self.pool.committed_capacity
        if current_cap <= float(self.auto_cfg.min_capacity) + 1e-9:
            return False

        decision_time = float(self.env.now)
        old_cap = self.pool.active_capacity

        if self.strategy == "vertical":
            server = self.pool.strictly_active_servers[0]
            new_cap = 2.0 if server.capacity > 2.5 else 1.0
            new_cap = max(new_cap, float(self.auto_cfg.min_capacity))
            if new_cap >= server.capacity:
                return False

            ok = self.pool.start_vertical_downgrade(server, new_cap)
            if ok:
                self.last_scaling_completed_time = decision_time
                self.last_scale_down_completed_time = decision_time
                self.metrics.log_scaling_event(
                    decision_time=decision_time,
                    completion_time=decision_time,
                    action_type="scale_down_vertical",
                    old_capacity=old_cap,
                    new_capacity=new_cap,
                    active_servers_after=len(self.pool.active_servers),
                    reason=reason,
                )
            return ok

        elif self.strategy == "horizontal":
            if len(self.pool.strictly_active_servers) <= self.auto_cfg.min_capacity:
                return False
            srv = self.pool.start_horizontal_scale_down(
                to_standby=self.auto_cfg.enable_standby
            )
            if srv is not None:
                self.last_scaling_completed_time = decision_time
                self.last_scale_down_completed_time = decision_time
                action_label = (
                    "scale_down_to_standby"
                    if self.auto_cfg.enable_standby
                    else "scale_down_horizontal"
                )
                self.metrics.log_scaling_event(
                    decision_time=decision_time,
                    completion_time=decision_time,
                    action_type=action_label,
                    old_capacity=old_cap,
                    new_capacity=self.pool.committed_capacity,
                    active_servers_after=len(self.pool.strictly_active_servers),
                    reason=reason,
                )
                return True
            return False

        elif self.strategy in ("hybrid", "hybrid_adaptive"):
            mode = (
                "adaptive"
                if self.strategy == "hybrid_adaptive"
                else self.auto_cfg.hybrid_mode
            )
            active_srvs = sorted(self.pool.strictly_active_servers, key=lambda s: s.server_id)

            if len(active_srvs) == 2:
                if mode == "adaptive" and all(s.capacity >= 1.5 for s in active_srvs):
                    second_srv = active_srvs[-1]
                    ok = self.pool.start_vertical_downgrade(second_srv, 1.0)
                    if ok:
                        self.last_scaling_completed_time = decision_time
                        self.last_scale_down_completed_time = decision_time
                        self.metrics.log_scaling_event(
                            decision_time=decision_time,
                            completion_time=decision_time,
                            action_type="scale_down_hybrid_vertical",
                            old_capacity=old_cap,
                            new_capacity=self.pool.committed_capacity,
                            active_servers_after=len(self.pool.strictly_active_servers),
                            reason=reason,
                        )
                    return ok

                second_srv = active_srvs[-1]
                srv = self.pool.start_horizontal_scale_down(
                    to_standby=self.auto_cfg.enable_standby,
                    target_server=second_srv,
                )
                if srv is not None:
                    self.last_scaling_completed_time = decision_time
                    self.last_scale_down_completed_time = decision_time
                    action_label = (
                        "scale_down_hybrid_standby"
                        if self.auto_cfg.enable_standby
                        else "scale_down_hybrid_horizontal"
                    )
                    self.metrics.log_scaling_event(
                        decision_time=decision_time,
                        completion_time=decision_time,
                        action_type=action_label,
                        old_capacity=old_cap,
                        new_capacity=self.pool.committed_capacity,
                        active_servers_after=len(self.pool.strictly_active_servers),
                        reason=reason,
                    )
                    return True

            elif len(active_srvs) == 1 and active_srvs[0].capacity > 1.5:
                primary = active_srvs[0]
                ok = self.pool.start_vertical_downgrade(primary, 1.0)
                if ok:
                    self.last_scaling_completed_time = decision_time
                    self.last_scale_down_completed_time = decision_time
                    self.metrics.log_scaling_event(
                        decision_time=decision_time,
                        completion_time=decision_time,
                        action_type="scale_down_hybrid_vertical",
                        old_capacity=old_cap,
                        new_capacity=1.0,
                        active_servers_after=1,
                        reason=reason,
                    )
                return ok

        return False


def _initial_pool_params(config: SimulationConfig) -> tuple[int, float]:
    """Determine (initial_servers, initial_capacity_per_server) for the chosen strategy."""
    strat = config.strategy.lower()
    if strat == "static_1":
        return 1, 1.0
    if strat == "static_2":
        return 1, 2.0
    if strat == "static_4":
        return 1, 4.0
    return 1, 1.0


def run_simulation(
    config: SimulationConfig,
    pregenerated_requests: Optional[Sequence[Request]] = None,
) -> SimulationResult:
    """Execute a complete discrete-event simulation run for a given configuration.

    Policy at end of arrival period (t = config.simulation_duration):
    1. New request arrivals stop at t = simulation_duration.
    2. Autoscaling periodic monitoring stops at t = simulation_duration.
    3. Any requests already in the FIFO queue or currently executing on a server
       continue draining until all requests finish (up to max_drain_time).
    4. Active server operating costs continue accruing during the drain phase.
    """
    env = simpy.Environment()
    queue = RequestQueue(env)

    init_servers, init_cap = _initial_pool_params(config)
    pool = ServerPool(
        env=env,
        queue=queue,
        initial_servers=init_servers,
        initial_capacity_per_server=init_cap,
        max_total_capacity=float(config.autoscaling.max_capacity),
    )

    metrics = MetricsCollector(env=env, config=config, queue=queue, pool=pool)
    pool.on_state_change = metrics.record_state_change
    pool.on_request_start = metrics.on_request_start
    pool.on_request_complete = metrics.on_request_complete

    if pregenerated_requests is None:
        workload_requests = generate_workload(
            traffic_profile=config.traffic_profile,
            request_classes=config.request_classes,
            seed=config.random_seed,
            max_duration=config.simulation_duration,
        )
    else:
        workload_requests = clone_workload(pregenerated_requests)

    def _handle_arrival(req: Request) -> None:
        metrics.on_request_arrival(req)
        queue.push(req)
        pool.dispatch()

    generator = TrafficGenerator(env=env, requests=workload_requests, on_arrival=_handle_arrival)
    _autoscaler = Autoscaler(env=env, config=config, queue=queue, pool=pool, metrics=metrics)

    # Periodic time-series recorder over the main arrival window
    def _ts_sampler():
        step = config.sample_interval
        while float(env.now) + step <= config.simulation_duration + 1e-9:
            yield env.timeout(step)
            metrics.record_time_series_point()

    env.process(_ts_sampler())

    # Run through the full arrival window first
    env.run(until=config.simulation_duration)

    # Drain any remaining queued or in-flight requests up to max_drain_time
    if (not queue.is_empty or pool.busy_capacity > 0.0) and config.max_drain_time > 0.0:
        max_end_time = config.simulation_duration + config.max_drain_time
        while (not queue.is_empty or pool.busy_capacity > 0.0) and float(env.now) < max_end_time:
            next_evt = env.peek()
            if next_evt == simpy.core.Infinity or next_evt > max_end_time:
                env.run(until=max_end_time)
                break
            env.step()

    summary = metrics.build_summary(generated_count=generator.generated_count)
    return SimulationResult(
        config=config,
        summary=summary,
        metrics=metrics,
        requests=generator.requests,
    )
