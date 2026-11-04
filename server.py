"""Request FIFO Queue and Server Pool components for discrete-event simulation.

Implements Component 2 (RequestQueue) and Component 3 (ServerPool) with explicit
server lifecycle states (STOPPED, BOOTING, ACTIVE, DRAINING, STANDBY), safe
scale-down without interrupting running jobs, and deterministic capacity changes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Deque, List, Optional
import simpy

from workload import Request


class ServerState(str, Enum):
    """Lifecycle states of a simulated server instance."""

    STOPPED = "stopped"
    BOOTING = "booting"
    ACTIVE = "active"
    DRAINING = "draining"
    STANDBY = "standby"


class RequestQueue:
    """Centralized First-In, First-Out (FIFO) request queue with continuous-time tracking."""

    def __init__(self, env: simpy.Environment) -> None:
        self.env = env
        self._items: Deque[Request] = deque()
        self._last_change_time: float = 0.0
        self._area_queue_time: float = 0.0
        self.max_length: int = 0
        self.total_enqueued: int = 0
        self.total_dequeued: int = 0

    def _update_integral(self) -> None:
        now = float(self.env.now)
        dt = now - self._last_change_time
        if dt > 0.0:
            self._area_queue_time += len(self._items) * dt
            self._last_change_time = now

    def push(self, request: Request) -> None:
        """Add an arriving request to the tail of the FIFO queue."""
        self._update_integral()
        request.queue_entry_time = float(self.env.now)
        self._items.append(request)
        self.total_enqueued += 1
        if len(self._items) > self.max_length:
            self.max_length = len(self._items)

    def pop(self) -> Optional[Request]:
        """Remove and return the oldest waiting request from the head of the queue."""
        if not self._items:
            return None
        self._update_integral()
        req = self._items.popleft()
        self.total_dequeued += 1
        return req

    def __len__(self) -> int:
        return len(self._items)

    @property
    def is_empty(self) -> bool:
        return len(self._items) == 0

    def time_weighted_average(self, total_duration: Optional[float] = None) -> float:
        """Compute exact time-weighted mean queue length from t=0 to now."""
        self._update_integral()
        denom = total_duration if total_duration is not None else float(self.env.now)
        if denom <= 0.0:
            return 0.0
        return self._area_queue_time / denom

    @property
    def area_queue_time(self) -> float:
        self._update_integral()
        return self._area_queue_time


@dataclass
class ServerInstance:
    """Represents a single virtual server instance in the ServerPool."""

    server_id: int
    capacity: float = 1.0
    state: ServerState = ServerState.ACTIVE
    busy: bool = False
    current_request: Optional[Request] = None
    # Pending vertical capacity changes
    pending_upgrade_capacity: Optional[float] = None
    pending_downgrade_capacity: Optional[float] = None
    # Target state when DRAINING completes (STOPPED or STANDBY)
    drain_target_state: ServerState = ServerState.STOPPED

    @property
    def is_eligible_for_work(self) -> bool:
        """A server can start a new job only when ACTIVE and not currently busy."""
        return self.state == ServerState.ACTIVE and not self.busy

    @property
    def is_providing_active_capacity(self) -> bool:
        """True when the server is ACTIVE or finishing an in-flight request while DRAINING."""
        return self.state == ServerState.ACTIVE or (
            self.state == ServerState.DRAINING and self.busy
        )


class ServerPool:
    """Manages server instances, request dispatch, and vertical/horizontal capacity transitions."""

    def __init__(
        self,
        env: simpy.Environment,
        queue: RequestQueue,
        initial_servers: int = 1,
        initial_capacity_per_server: float = 1.0,
        max_total_capacity: float = 4.0,
        on_state_change: Optional[Callable[[], None]] = None,
        on_request_start: Optional[Callable[[Request, ServerInstance], None]] = None,
        on_request_complete: Optional[Callable[[Request, ServerInstance], None]] = None,
    ) -> None:
        self.env = env
        self.queue = queue
        self.max_total_capacity = max_total_capacity
        self.on_state_change = on_state_change
        self.on_request_start = on_request_start
        self.on_request_complete = on_request_complete

        self.servers: List[ServerInstance] = []
        for idx in range(1, max(initial_servers, 4) + 1):
            is_initial = idx <= initial_servers
            self.servers.append(
                ServerInstance(
                    server_id=idx,
                    capacity=initial_capacity_per_server,
                    state=ServerState.ACTIVE if is_initial else ServerState.STOPPED,
                )
            )

    def _notify_state_change(self) -> None:
        if self.on_state_change is not None:
            self.on_state_change()

    @property
    def active_servers(self) -> List[ServerInstance]:
        """Servers currently in ACTIVE state or finishing a job in DRAINING state."""
        return [s for s in self.servers if s.is_providing_active_capacity]

    @property
    def strictly_active_servers(self) -> List[ServerInstance]:
        """Servers currently in ACTIVE state (not draining)."""
        return [s for s in self.servers if s.state == ServerState.ACTIVE]

    @property
    def standby_servers(self) -> List[ServerInstance]:
        return [s for s in self.servers if s.state == ServerState.STANDBY]

    @property
    def booting_servers(self) -> List[ServerInstance]:
        return [s for s in self.servers if s.state == ServerState.BOOTING]

    @property
    def stopped_servers(self) -> List[ServerInstance]:
        return [s for s in self.servers if s.state == ServerState.STOPPED]

    @property
    def active_capacity(self) -> float:
        """Total effective processing capacity currently available for running jobs."""
        return sum(s.capacity for s in self.servers if s.is_providing_active_capacity)

    @property
    def busy_capacity(self) -> float:
        """Total capacity of servers currently executing a request."""
        return sum(s.capacity for s in self.servers if s.busy)

    @property
    def provisioning_capacity(self) -> float:
        """Capacity currently booting or undergoing vertical upgrade."""
        boot_cap = sum(s.capacity for s in self.servers if s.state == ServerState.BOOTING)
        upgrade_delta = sum(
            (s.pending_upgrade_capacity - s.capacity)
            for s in self.servers
            if s.pending_upgrade_capacity is not None and s.pending_upgrade_capacity > s.capacity
        )
        return boot_cap + upgrade_delta

    @property
    def standby_capacity(self) -> float:
        """Total capacity of servers in warm STANDBY mode."""
        return sum(s.capacity for s in self.servers if s.state == ServerState.STANDBY)

    @property
    def committed_capacity(self) -> float:
        """Target active capacity after all pending boots, upgrades, and drains complete."""
        total = 0.0
        for s in self.servers:
            if s.state == ServerState.BOOTING:
                total += s.capacity
            elif s.state == ServerState.ACTIVE:
                if s.pending_upgrade_capacity is not None:
                    total += s.pending_upgrade_capacity
                elif s.pending_downgrade_capacity is not None:
                    total += s.pending_downgrade_capacity
                else:
                    total += s.capacity
            # DRAINING, STANDBY, and STOPPED have 0 committed future active capacity
        return total

    @property
    def has_pending_scaling(self) -> bool:
        """True if any server is booting, draining, or has a pending vertical change."""
        for s in self.servers:
            if s.state in (ServerState.BOOTING, ServerState.DRAINING):
                return True
            if s.pending_upgrade_capacity is not None or s.pending_downgrade_capacity is not None:
                return True
        return False

    def dispatch(self) -> None:
        """Assign waiting requests from the FIFO queue to eligible idle ACTIVE servers."""
        if self.queue.is_empty:
            return

        # Sort eligible servers deterministically by server_id (prefer higher capacity first if hybrid)
        eligible = [s for s in self.servers if s.is_eligible_for_work]
        eligible.sort(key=lambda s: (-s.capacity, s.server_id))

        for server in eligible:
            if self.queue.is_empty:
                break
            req = self.queue.pop()
            if req is not None:
                # Mark server busy synchronously upon dispatch so concurrent events
                # at the same SimPy timestamp never double-assign the same server.
                self._notify_state_change()
                server.busy = True
                server.current_request = req
                self._notify_state_change()
                self.env.process(self._execute_request(server, req))

    def _execute_request(self, server: ServerInstance, request: Request):
        """SimPy process executing a single request on the designated server."""
        request.service_start_time = float(self.env.now)
        request.server_id = server.server_id
        # Capacity at start determines service duration (idealized linear speedup)
        cap_at_start = float(server.capacity)
        request.server_capacity_at_start = cap_at_start
        service_duration = request.cpu_work / cap_at_start

        if self.on_request_start is not None:
            self.on_request_start(request, server)

        yield self.env.timeout(service_duration)

        # Request finishes
        self._notify_state_change()
        request.completion_time = float(self.env.now)
        server.busy = False
        server.current_request = None

        # Apply any deferred vertical downgrade now that the in-flight request finished
        if server.pending_downgrade_capacity is not None:
            server.capacity = server.pending_downgrade_capacity
            server.pending_downgrade_capacity = None

        # If server was DRAINING, transition to its target post-drain state (STANDBY or STOPPED)
        if server.state == ServerState.DRAINING:
            server.state = server.drain_target_state

        if self.on_request_complete is not None:
            self.on_request_complete(request, server)
        self._notify_state_change()

        # Check if more queued requests can now be dispatched
        self.dispatch()

    def start_horizontal_scale_up(
        self,
        target_server_capacity: float = 1.0,
        cold_startup_delay: float = 10.0,
        standby_startup_delay: float = 2.0,
        on_complete: Optional[Callable[[ServerInstance], None]] = None,
    ) -> Optional[ServerInstance]:
        """Boot an additional server instance from STANDBY (preferred) or STOPPED."""
        if self.committed_capacity + target_server_capacity > self.max_total_capacity + 1e-9:
            return None

        # Prefer resuming a STANDBY server first
        candidate: Optional[ServerInstance] = None
        from_standby = False
        if self.standby_servers:
            candidate = self.standby_servers[0]
            from_standby = True
        elif self.stopped_servers:
            candidate = self.stopped_servers[0]
            from_standby = False

        if candidate is None:
            return None

        delay = standby_startup_delay if from_standby else cold_startup_delay
        self._notify_state_change()
        candidate.capacity = target_server_capacity
        candidate.state = ServerState.BOOTING
        self._notify_state_change()

        self.env.process(self._finish_boot(candidate, delay, on_complete))
        return candidate

    def _finish_boot(
        self,
        server: ServerInstance,
        delay: float,
        on_complete: Optional[Callable[[ServerInstance], None]],
    ):
        if delay > 0.0:
            yield self.env.timeout(delay)
        self._notify_state_change()
        server.state = ServerState.ACTIVE
        self._notify_state_change()
        if on_complete is not None:
            on_complete(server)
        self.dispatch()

    def start_horizontal_scale_down(
        self,
        to_standby: bool = False,
        target_server: Optional[ServerInstance] = None,
    ) -> Optional[ServerInstance]:
        """Safely decommission one ACTIVE server without interrupting running work."""
        active = self.strictly_active_servers
        if len(active) <= 1 and target_server is None:
            return None

        if target_server is None:
            # Prefer shutting down an idle server first, and smaller capacity first
            active_sorted = sorted(
                active,
                key=lambda s: (1 if s.busy else 0, s.capacity, -s.server_id),
            )
            target_server = active_sorted[0]

        dest_state = ServerState.STANDBY if to_standby else ServerState.STOPPED
        self._notify_state_change()
        if not target_server.busy:
            target_server.state = dest_state
        else:
            target_server.state = ServerState.DRAINING
            target_server.drain_target_state = dest_state
        self._notify_state_change()
        return target_server

    def start_vertical_upgrade(
        self,
        server: ServerInstance,
        new_capacity: float,
        upgrade_delay: float = 5.0,
        on_complete: Optional[Callable[[ServerInstance], None]] = None,
    ) -> bool:
        """Upgrade a server's processing capacity after vertical_upgrade_delay."""
        if server.state != ServerState.ACTIVE:
            return False
        if server.pending_upgrade_capacity is not None:
            return False
        delta = new_capacity - server.capacity
        if delta <= 0.0:
            return False
        if self.committed_capacity + delta > self.max_total_capacity + 1e-9:
            return False

        self._notify_state_change()
        server.pending_upgrade_capacity = new_capacity
        self._notify_state_change()
        self.env.process(self._finish_vertical_upgrade(server, new_capacity, upgrade_delay, on_complete))
        return True

    def _finish_vertical_upgrade(
        self,
        server: ServerInstance,
        new_capacity: float,
        delay: float,
        on_complete: Optional[Callable[[ServerInstance], None]],
    ):
        if delay > 0.0:
            yield self.env.timeout(delay)
        self._notify_state_change()
        server.capacity = new_capacity
        server.pending_upgrade_capacity = None
        self._notify_state_change()
        if on_complete is not None:
            on_complete(server)
        self.dispatch()

    def start_vertical_downgrade(
        self,
        server: ServerInstance,
        new_capacity: float,
    ) -> bool:
        """Safely downgrade a server's processing capacity without disrupting running jobs."""
        if server.state != ServerState.ACTIVE:
            return False
        if new_capacity >= server.capacity or new_capacity < 1.0:
            return False

        self._notify_state_change()
        if not server.busy:
            server.capacity = new_capacity
        else:
            # Apply immediately when the current in-flight request completes
            server.pending_downgrade_capacity = new_capacity
        self._notify_state_change()
        return True
