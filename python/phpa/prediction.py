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

"""Prediction models for the Predictive Horizontal Pod Autoscaler."""

import math
import warnings
from datetime import datetime, timedelta, timezone
from typing import List

import statsmodels.api as sm
import statsmodels.tsa.api as tsa
from statsmodels.tools.sm_exceptions import ConvergenceWarning

from .config import (
    HoltWintersConfig,
    LinearConfig,
    ModelConfig,
    TimestampedReplicas,
    MODEL_LINEAR,
    MODEL_HOLT_WINTERS,
)

warnings.simplefilter("ignore", ConvergenceWarning)


def predict_linear(
    replica_history: List[TimestampedReplicas],
    config: LinearConfig,
    current_time: datetime = None,
) -> int:
    """
    Predict future replica count using linear regression (OLS).

    Uses statsmodels OLS to fit a linear regression on the replica history and
    predict the replica count at a future time point determined by look_ahead.

    Args:
        replica_history: List of timestamped replica counts.
        config: Linear regression configuration (look_ahead, history_size).
        current_time: Override for the current time (defaults to UTC now).

    Returns:
        Predicted replica count (ceiling of the regression prediction).

    Raises:
        ValueError: If replica_history has fewer than 2 data points.
    """
    if len(replica_history) < 2:
        raise ValueError(
            "Linear regression requires at least 2 data points, "
            f"got {len(replica_history)}"
        )

    if current_time is None:
        current_time = datetime.now(timezone.utc)

    search_time = current_time + timedelta(milliseconds=config.look_ahead)
    search_timestamp = search_time.timestamp()

    x = []
    y = []

    for entry in replica_history:
        entry_timestamp = entry.time.timestamp()
        x.append(search_timestamp - entry_timestamp)
        y.append(entry.replicas)

    x = sm.add_constant(x)
    model = sm.OLS(y, x).fit()

    # Predict at search_time (offset 0 from itself), with constant 1.0
    prediction = model.predict([[1, 0]])[0]
    return math.ceil(prediction)


def predict_holt_winters(
    series: List[int],
    config: HoltWintersConfig,
) -> int:
    """
    Predict the next value using Holt-Winters exponential smoothing.

    Args:
        series: Historical replica counts as a time series.
        config: Holt-Winters model configuration.

    Returns:
        Predicted next replica count (ceiling of the forecast).

    Raises:
        ValueError: If the series is too short for the configured seasonal periods.
    """
    if len(series) < 2 * config.seasonal_periods:
        raise ValueError(
            "Holt-Winters requires at least 2 * seasonal_periods observations, "
            f"got {len(series)} (need {2 * config.seasonal_periods})"
        )

    if len(series) < 10 + 2 * (config.seasonal_periods // 2):
        raise ValueError(
            "Holt-Winters requires at least 10 + 2 * (seasonal_periods // 2) "
            f"observations, got {len(series)} "
            f"(need {10 + 2 * (config.seasonal_periods // 2)})"
        )

    model = tsa.ExponentialSmoothing(
        series,
        trend=config.trend,
        seasonal=config.seasonal,
        seasonal_periods=config.seasonal_periods,
        initialization_method=config.initialization_method,
        damped_trend=config.damped_trend,
        initial_level=config.initial_level,
        initial_trend=config.initial_trend,
        initial_seasonal=config.initial_seasonal,
    )

    fitted = model.fit(
        smoothing_level=config.alpha,
        smoothing_trend=config.beta,
        smoothing_seasonal=config.gamma,
        optimized=False,
    )

    prediction = fitted.forecast(steps=1)[0]
    return math.ceil(prediction)


def get_prediction(
    model_config: ModelConfig,
    replica_history: List[TimestampedReplicas],
    current_time: datetime = None,
) -> int:
    """
    Route prediction to the appropriate model based on model_type.

    Args:
        model_config: The model configuration specifying type and parameters.
        replica_history: List of timestamped replica counts.
        current_time: Override for the current time (for linear regression).

    Returns:
        Predicted replica count.

    Raises:
        ValueError: If model_type is unknown or model-specific config is missing.
    """
    if model_config.model_type == MODEL_LINEAR:
        if model_config.linear is None:
            raise ValueError(
                f"Model '{model_config.name}' is Linear type but has no linear config"
            )
        return predict_linear(replica_history, model_config.linear, current_time)

    if model_config.model_type == MODEL_HOLT_WINTERS:
        if model_config.holt_winters is None:
            raise ValueError(
                f"Model '{model_config.name}' is HoltWinters type but has no "
                "holt_winters config"
            )
        series = [entry.replicas for entry in replica_history]
        return predict_holt_winters(series, model_config.holt_winters)

    raise ValueError(f"Unknown model type '{model_config.model_type}'")


def prune_history(
    model_config: ModelConfig,
    replica_history: List[TimestampedReplicas],
) -> List[TimestampedReplicas]:
    """
    Prune the replica history to the appropriate size for the model type.

    For Linear models, keeps only the most recent `history_size` entries.
    For HoltWinters models, keeps `stored_seasons * seasonal_periods` entries.

    Args:
        model_config: The model configuration.
        replica_history: The full replica history.

    Returns:
        The pruned replica history.
    """
    if model_config.model_type == MODEL_LINEAR:
        if model_config.linear is None:
            return replica_history
        max_size = model_config.linear.history_size
        if len(replica_history) > max_size:
            return replica_history[-max_size:]
        return replica_history

    if model_config.model_type == MODEL_HOLT_WINTERS:
        if model_config.holt_winters is None:
            return replica_history
        hw = model_config.holt_winters
        max_size = hw.stored_seasons * hw.seasonal_periods
        if len(replica_history) > max_size:
            return replica_history[-max_size:]
        return replica_history

    return replica_history
