# Copyright 2024 The Predictive Horizontal Pod Autoscaler Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Configuration data classes for the Predictive Horizontal Pod Autoscaler."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


# Decision type constants
DECISION_MAXIMUM = "maximum"
DECISION_MINIMUM = "minimum"
DECISION_MEAN = "mean"
DECISION_MEDIAN = "median"

# Model type constants
MODEL_LINEAR = "Linear"
MODEL_HOLT_WINTERS = "HoltWinters"

# Metric type constants
METRIC_CPU = "cpu"

# Default values
DEFAULT_SYNC_PERIOD_SECONDS = 15
DEFAULT_MIN_REPLICAS = 1
DEFAULT_TOLERANCE = 0.1
DEFAULT_DECISION_TYPE = DECISION_MAXIMUM
DEFAULT_DOWNSCALE_STABILIZATION_SECONDS = 300
DEFAULT_CPU_TARGET_UTILIZATION = 80


@dataclass
class TimestampedReplicas:
    """A replica count paired with a timestamp."""
    time: datetime
    replicas: int


@dataclass
class LinearConfig:
    """Configuration for the linear regression model."""
    history_size: int = 6
    look_ahead: int = 10000  # milliseconds


@dataclass
class HoltWintersConfig:
    """Configuration for the Holt-Winters exponential smoothing model."""
    alpha: float = 0.9
    beta: float = 0.9
    gamma: float = 0.9
    trend: str = "add"
    seasonal: str = "add"
    seasonal_periods: int = 2
    stored_seasons: int = 4
    damped_trend: bool = False
    initialization_method: str = "estimated"
    initial_level: Optional[float] = None
    initial_trend: Optional[float] = None
    initial_seasonal: Optional[float] = None


@dataclass
class ModelConfig:
    """Configuration for a prediction model."""
    name: str
    model_type: str  # "Linear" or "HoltWinters"
    per_sync_period: int = 1
    linear: Optional[LinearConfig] = None
    holt_winters: Optional[HoltWintersConfig] = None


@dataclass
class ModelHistory:
    """Stored state for a single model's history."""
    model_type: str
    sync_periods_passed: int = 1
    replica_history: List[TimestampedReplicas] = field(default_factory=list)


@dataclass
class ScaleTargetRef:
    """Reference to the target resource to scale."""
    api_version: str = "apps/v1"
    kind: str = "Deployment"
    name: str = ""
    namespace: str = "default"


@dataclass
class MetricTarget:
    """Configuration for a metric to use for scaling decisions."""
    metric_type: str = METRIC_CPU
    average_utilization: int = DEFAULT_CPU_TARGET_UTILIZATION


@dataclass
class PHPAConfig:
    """Top-level configuration for the Predictive Horizontal Pod Autoscaler."""
    scale_target_ref: ScaleTargetRef = field(default_factory=ScaleTargetRef)
    min_replicas: int = DEFAULT_MIN_REPLICAS
    max_replicas: int = 10
    metrics: List[MetricTarget] = field(default_factory=list)
    models: List[ModelConfig] = field(default_factory=list)
    decision_type: str = DEFAULT_DECISION_TYPE
    sync_period_seconds: int = DEFAULT_SYNC_PERIOD_SECONDS
    downscale_stabilization_seconds: int = DEFAULT_DOWNSCALE_STABILIZATION_SECONDS
    tolerance: float = DEFAULT_TOLERANCE
