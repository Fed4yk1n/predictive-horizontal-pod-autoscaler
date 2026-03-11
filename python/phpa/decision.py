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

"""Decision strategies for combining predictions from multiple models."""

import math
from typing import List

from .config import (
    DECISION_MAXIMUM,
    DECISION_MINIMUM,
    DECISION_MEAN,
    DECISION_MEDIAN,
)


def decide_replicas(decision_type: str, predicted_replicas: List[int]) -> int:
    """
    Decide the target replica count based on the decision strategy.

    Combines predictions from multiple models (and the HPA-calculated value)
    using the specified strategy.

    Args:
        decision_type: One of "maximum", "minimum", "mean", or "median".
        predicted_replicas: List of predicted replica counts.

    Returns:
        The target replica count based on the decision strategy.

    Raises:
        ValueError: If the decision_type is unknown or no replicas are provided.
    """
    if not predicted_replicas:
        raise ValueError("No predicted replica values provided")

    sorted_replicas = sorted(predicted_replicas)

    if decision_type == DECISION_MAXIMUM:
        return max(sorted_replicas)

    if decision_type == DECISION_MINIMUM:
        return min(sorted_replicas)

    if decision_type == DECISION_MEAN:
        return round(sum(sorted_replicas) / len(sorted_replicas))

    if decision_type == DECISION_MEDIAN:
        n = len(sorted_replicas)
        mid = n // 2
        if n % 2 == 0:
            return (sorted_replicas[mid - 1] + sorted_replicas[mid]) // 2
        return sorted_replicas[mid]

    raise ValueError(f"Unknown decision type '{decision_type}'")


def apply_min_max(replicas: int, min_replicas: int, max_replicas: int) -> int:
    """
    Clamp replicas to the configured minimum and maximum.

    Args:
        replicas: The target replica count.
        min_replicas: The minimum allowed replicas.
        max_replicas: The maximum allowed replicas.

    Returns:
        The clamped replica count.
    """
    return max(min_replicas, min(replicas, max_replicas))


def apply_downscale_stabilization(
    target_replicas: int,
    current_replicas: int,
    recent_recommendations: List[int],
) -> int:
    """
    Apply downscale stabilization by using the highest recommendation in the window.

    When scaling down, this prevents rapid fluctuations by looking at all
    recent recommendations in the stabilization window and choosing the highest.

    Args:
        target_replicas: The newly calculated target replicas.
        current_replicas: The current number of replicas.
        recent_recommendations: List of recent target replica recommendations
            within the stabilization window.

    Returns:
        The stabilized replica count.
    """
    if target_replicas >= current_replicas:
        # Not scaling down, no stabilization needed
        return target_replicas

    # For downscale, use the maximum of all recent recommendations
    all_recommendations = recent_recommendations + [target_replicas]
    return max(all_recommendations)
