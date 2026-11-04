"""Central configuration for the DTA400 Dynamic Server Scaling Simulation.

Separates approved course/proposal parameters from configurable experimental
modeling assumptions so that all experiments are transparent and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class RequestClassSpec:
    """Specification for a discrete request workload class."""

    name: str
    probability: float
    cpu_work: float  # CPU-seconds required on a 1-unit server


DEFAULT_REQUEST_CLASSES: Tuple[RequestClassSpec, ...] = (
    RequestClassSpec(name="small", probability=0.50, cpu_work=0.05),
    RequestClassSpec(name="medium", probability=0.35, cpu_work=0.15),
    RequestClassSpec(name="heavy", probability=0.15, cpu_work=0.35),
)


@dataclass(frozen=True)
class TrafficSegment:
    """Time segment with a constant Poisson arrival rate [start_time, end_time)."""

    start_time: float  # seconds
    end_time: float    # seconds
    arrival_rate: float  # requests per second
    label: str


# Approved 60-minute (3,600 s) variable workload scenario from project specification
VARIABLE_BASELINE_PROFILE: Tuple[TrafficSegment, ...] = (
    TrafficSegment(0.0, 600.0, 3.0, "Low"),
    TrafficSegment(600.0, 1500.0, 6.0, "Normal"),
    TrafficSegment(1500.0, 2100.0, 12.0, "High"),
    TrafficSegment(2100.0, 2220.0, 20.0, "Traffic spike"),
    TrafficSegment(2220.0, 3000.0, 6.0, "Normal"),
    TrafficSegment(3000.0, 3600.0, 3.0, "Low"),
)

STEADY_LOW_PROFILE: Tuple[TrafficSegment, ...] = (
    TrafficSegment(0.0, 3600.0, 3.0, "Steady Low"),
)

STEADY_NORMAL_PROFILE: Tuple[TrafficSegment, ...] = (
    TrafficSegment(0.0, 3600.0, 6.0, "Steady Normal"),
)

STEADY_HIGH_PROFILE: Tuple[TrafficSegment, ...] = (
    TrafficSegment(0.0, 3600.0, 12.0, "Steady High"),
)

SUDDEN_SPIKE_PROFILE: Tuple[TrafficSegment, ...] = (
    TrafficSegment(0.0, 600.0, 3.0, "Low"),
    TrafficSegment(600.0, 1500.0, 6.0, "Normal"),
    TrafficSegment(1500.0, 1680.0, 20.0, "Sudden Spike"),
    TrafficSegment(1680.0, 3000.0, 6.0, "Normal"),
    TrafficSegment(3000.0, 3600.0, 3.0, "Low"),
)

RECURRING_SPIKES_PROFILE: Tuple[TrafficSegment, ...] = (
    TrafficSegment(0.0, 400.0, 3.0, "Low"),
    TrafficSegment(400.0, 700.0, 6.0, "Normal"),
    TrafficSegment(700.0, 820.0, 12.0, "High"),
    # Spike 1 (120 s) followed by a 45 s lull (tests 30 s vs 60 s shutdown delay)
    TrafficSegment(820.0, 940.0, 20.0, "Spike 1"),
    TrafficSegment(940.0, 985.0, 2.0, "Short Lull (45s)"),
    # Spike 2 (120 s) followed by a 90 s lull (tests 60 s vs 120 s shutdown delay)
    TrafficSegment(985.0, 1105.0, 20.0, "Spike 2"),
    TrafficSegment(1105.0, 1195.0, 2.0, "Medium Lull (90s)"),
    # Spike 3 (120 s) followed by a 90 s lull
    TrafficSegment(1195.0, 1315.0, 20.0, "Spike 3"),
    TrafficSegment(1315.0, 1405.0, 2.0, "Medium Lull (90s)"),
    # Spike 4 (120 s)
    TrafficSegment(1405.0, 1525.0, 20.0, "Spike 4"),
    TrafficSegment(1525.0, 2400.0, 6.0, "Normal"),
    # Late burst cluster
    TrafficSegment(2400.0, 2520.0, 12.0, "High"),
    TrafficSegment(2520.0, 2640.0, 20.0, "Spike 5"),
    TrafficSegment(2640.0, 2730.0, 2.0, "Medium Lull (90s)"),
    TrafficSegment(2730.0, 2850.0, 20.0, "Spike 6"),
    TrafficSegment(2850.0, 3600.0, 3.0, "Low"),
)

TRAFFIC_SCENARIOS: Dict[str, Tuple[TrafficSegment, ...]] = {
    "variable_baseline": VARIABLE_BASELINE_PROFILE,
    "steady_low": STEADY_LOW_PROFILE,
    "steady_normal": STEADY_NORMAL_PROFILE,
    "steady_high": STEADY_HIGH_PROFILE,
    "sudden_spike": SUDDEN_SPIKE_PROFILE,
    "recurring_spikes": RECURRING_SPIKES_PROFILE,
}


@dataclass(frozen=True)
class AutoscalingConfig:
    """Parameters governing dynamic scaling control and state transitions."""

    monitoring_interval: float = 5.0
    scale_up_utilization_threshold: float = 0.85
    # Sustained queue buildup: queue length >= scale_up_queue_threshold
    # across sustained_queue_samples consecutive monitoring intervals
    scale_up_queue_threshold: int = 2
    sustained_queue_samples: int = 2
    scale_down_observation_window: float = 60.0
    scale_down_utilization_threshold: float = 0.35
    horizontal_startup_delay: float = 10.0
    vertical_upgrade_delay: float = 5.0
    scaling_cooldown: float = 60.0
    min_capacity: int = 1
    max_capacity: int = 4
    enable_standby: bool = False
    standby_startup_delay: float = 2.0
    # Hybrid policy mode:
    # - "vertical_first": (1x1) <-> (1x2) <-> (2x2)
    # - "adaptive": allows intermediate 3-unit state (1x2 + 1x1) under moderate high load
    hybrid_mode: str = "vertical_first"


@dataclass(frozen=True)
class CostConfig:
    """Normalized operating cost model assumptions."""

    active_cost_per_unit_hour: float = 1.0
    provisioning_cost_per_unit_hour: float = 1.0
    standby_cost_ratio: float = 0.25  # 25% of active unit cost per hour

    @property
    def standby_cost_per_unit_hour(self) -> float:
        return self.active_cost_per_unit_hour * self.standby_cost_ratio


@dataclass(frozen=True)
class SimulationConfig:
    """Complete configuration for a single simulation run."""

    strategy: str = "vertical"
    scenario_name: str = "variable_baseline"
    traffic_profile: Tuple[TrafficSegment, ...] = VARIABLE_BASELINE_PROFILE
    request_classes: Tuple[RequestClassSpec, ...] = DEFAULT_REQUEST_CLASSES
    autoscaling: AutoscalingConfig = field(default_factory=AutoscalingConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    simulation_duration: float = 3600.0
    max_drain_time: float = 1800.0
    slo_p95_target: float = 1.0
    random_seed: int = 42
    sample_interval: float = 5.0  # Time-series recording interval (seconds)

    def with_updates(self, **kwargs) -> "SimulationConfig":
        """Return a copy of the configuration with updated top-level fields."""
        return replace(self, **kwargs)
