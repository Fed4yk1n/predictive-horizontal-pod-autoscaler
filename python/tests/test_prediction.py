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

"""Tests for the prediction module."""

from datetime import datetime, timedelta, timezone

import pytest

from phpa.config import (
    HoltWintersConfig,
    LinearConfig,
    ModelConfig,
    TimestampedReplicas,
)
from phpa.prediction import (
    get_prediction,
    predict_holt_winters,
    predict_linear,
    prune_history,
)


class TestPredictLinear:
    """Tests for predict_linear."""

    def test_constant_replicas(self):
        """If replicas are constant, prediction should be close to that constant."""
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        config = LinearConfig(history_size=6, look_ahead=10000)

        history = [
            TimestampedReplicas(
                time=now - timedelta(minutes=5 - i), replicas=5
            )
            for i in range(6)
        ]

        result = predict_linear(history, config, current_time=now)
        assert result == 5

    def test_increasing_replicas(self):
        """If replicas are increasing, prediction should be higher."""
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        config = LinearConfig(history_size=6, look_ahead=60000)

        history = [
            TimestampedReplicas(
                time=now - timedelta(minutes=5 - i), replicas=i + 1
            )
            for i in range(6)
        ]

        result = predict_linear(history, config, current_time=now)
        # Replicas 1,2,3,4,5,6 over 5 minutes, predicting 1 minute ahead
        assert result >= 6

    def test_too_few_data_points(self):
        """Linear regression needs at least 2 data points."""
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        config = LinearConfig(history_size=6, look_ahead=10000)

        history = [TimestampedReplicas(time=now, replicas=5)]

        with pytest.raises(ValueError, match="at least 2 data points"):
            predict_linear(history, config, current_time=now)

    def test_empty_history(self):
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        config = LinearConfig(history_size=6, look_ahead=10000)

        with pytest.raises(ValueError, match="at least 2 data points"):
            predict_linear([], config, current_time=now)

    def test_decreasing_replicas(self):
        """If replicas are decreasing, prediction should be lower."""
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        config = LinearConfig(history_size=6, look_ahead=60000)

        history = [
            TimestampedReplicas(
                time=now - timedelta(minutes=5 - i), replicas=10 - i
            )
            for i in range(6)
        ]

        result = predict_linear(history, config, current_time=now)
        assert result <= 5


class TestPredictHoltWinters:
    """Tests for predict_holt_winters."""

    def test_constant_series(self):
        """A constant series should predict close to that constant."""
        config = HoltWintersConfig(
            alpha=0.9,
            beta=0.9,
            gamma=0.9,
            trend="add",
            seasonal="add",
            seasonal_periods=2,
        )
        series = [5] * 12

        result = predict_holt_winters(series, config)
        assert result == 5

    def test_too_few_observations_seasonal(self):
        """Need at least 2 * seasonal_periods observations."""
        config = HoltWintersConfig(seasonal_periods=5)
        series = [1, 2, 3]  # Only 3, need 10

        with pytest.raises(ValueError, match="2 \\* seasonal_periods"):
            predict_holt_winters(series, config)

    def test_too_few_observations_minimum(self):
        """Need at least 10 + 2*(seasonal_periods//2) observations."""
        config = HoltWintersConfig(seasonal_periods=2)
        series = [1, 2, 3, 4, 5, 6, 7, 8, 9]  # 9, need 12

        with pytest.raises(ValueError, match="10 \\+ 2"):
            predict_holt_winters(series, config)

    def test_increasing_series(self):
        """An increasing series should predict a value >= last value."""
        config = HoltWintersConfig(
            alpha=0.9,
            beta=0.9,
            gamma=0.9,
            trend="add",
            seasonal="add",
            seasonal_periods=2,
        )
        series = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

        result = predict_holt_winters(series, config)
        assert result >= 12


class TestGetPrediction:
    """Tests for get_prediction routing."""

    def test_linear_model(self):
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        model = ModelConfig(
            name="test-linear",
            model_type="Linear",
            linear=LinearConfig(history_size=6, look_ahead=10000),
        )
        history = [
            TimestampedReplicas(
                time=now - timedelta(minutes=5 - i), replicas=5
            )
            for i in range(6)
        ]

        result = get_prediction(model, history, current_time=now)
        assert result == 5

    def test_holt_winters_model(self):
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        model = ModelConfig(
            name="test-hw",
            model_type="HoltWinters",
            holt_winters=HoltWintersConfig(
                alpha=0.9,
                beta=0.9,
                gamma=0.9,
                seasonal_periods=2,
            ),
        )
        history = [
            TimestampedReplicas(
                time=now - timedelta(minutes=12 - i), replicas=5
            )
            for i in range(12)
        ]

        result = get_prediction(model, history, current_time=now)
        assert result == 5

    def test_unknown_model_type(self):
        model = ModelConfig(name="test", model_type="Unknown")
        with pytest.raises(ValueError, match="Unknown model type"):
            get_prediction(model, [])

    def test_linear_without_config(self):
        model = ModelConfig(name="test", model_type="Linear", linear=None)
        with pytest.raises(ValueError, match="no linear config"):
            get_prediction(model, [])

    def test_holt_winters_without_config(self):
        model = ModelConfig(name="test", model_type="HoltWinters", holt_winters=None)
        with pytest.raises(ValueError, match="no holt_winters config"):
            get_prediction(model, [])


class TestPruneHistory:
    """Tests for prune_history."""

    def test_linear_prune(self):
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        model = ModelConfig(
            name="test",
            model_type="Linear",
            linear=LinearConfig(history_size=3),
        )
        history = [
            TimestampedReplicas(time=now - timedelta(minutes=i), replicas=i)
            for i in range(10)
        ]

        pruned = prune_history(model, history)
        assert len(pruned) == 3

    def test_holt_winters_prune(self):
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        model = ModelConfig(
            name="test",
            model_type="HoltWinters",
            holt_winters=HoltWintersConfig(
                seasonal_periods=3, stored_seasons=2
            ),
        )
        history = [
            TimestampedReplicas(time=now - timedelta(minutes=i), replicas=i)
            for i in range(20)
        ]

        pruned = prune_history(model, history)
        assert len(pruned) == 6  # 3 * 2

    def test_no_prune_needed(self):
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        model = ModelConfig(
            name="test",
            model_type="Linear",
            linear=LinearConfig(history_size=10),
        )
        history = [
            TimestampedReplicas(time=now - timedelta(minutes=i), replicas=i)
            for i in range(5)
        ]

        pruned = prune_history(model, history)
        assert len(pruned) == 5
