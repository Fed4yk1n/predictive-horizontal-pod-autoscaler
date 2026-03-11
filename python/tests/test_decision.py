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

"""Tests for the decision module."""

import pytest

from phpa.decision import (
    apply_downscale_stabilization,
    apply_min_max,
    decide_replicas,
)


class TestDecideReplicas:
    """Tests for decide_replicas."""

    def test_maximum(self):
        assert decide_replicas("maximum", [3, 5, 7, 2]) == 7

    def test_minimum(self):
        assert decide_replicas("minimum", [3, 5, 7, 2]) == 2

    def test_mean(self):
        # (3 + 5 + 7 + 2) / 4 = 4.25 -> rounds to 4
        assert decide_replicas("mean", [3, 5, 7, 2]) == 4

    def test_mean_rounds_up(self):
        # (3 + 5 + 7) / 3 = 5.0
        assert decide_replicas("mean", [3, 5, 7]) == 5

    def test_median_odd(self):
        # sorted: [2, 3, 5, 7, 9] -> median is 5
        assert decide_replicas("median", [3, 5, 7, 2, 9]) == 5

    def test_median_even(self):
        # sorted: [2, 3, 5, 7] -> median is (3+5)//2 = 4
        assert decide_replicas("median", [3, 5, 7, 2]) == 4

    def test_single_value(self):
        assert decide_replicas("maximum", [5]) == 5
        assert decide_replicas("minimum", [5]) == 5
        assert decide_replicas("mean", [5]) == 5
        assert decide_replicas("median", [5]) == 5

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="No predicted replica values"):
            decide_replicas("maximum", [])

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown decision type"):
            decide_replicas("invalid", [1, 2, 3])


class TestApplyMinMax:
    """Tests for apply_min_max."""

    def test_within_bounds(self):
        assert apply_min_max(5, 1, 10) == 5

    def test_below_min(self):
        assert apply_min_max(0, 1, 10) == 1

    def test_above_max(self):
        assert apply_min_max(15, 1, 10) == 10

    def test_at_boundaries(self):
        assert apply_min_max(1, 1, 10) == 1
        assert apply_min_max(10, 1, 10) == 10


class TestApplyDownscaleStabilization:
    """Tests for apply_downscale_stabilization."""

    def test_scaling_up_no_stabilization(self):
        # When scaling up, just return target
        assert apply_downscale_stabilization(8, 5, [4, 5, 6]) == 8

    def test_scaling_down_uses_max(self):
        # When scaling down, use max of recent recommendations
        assert apply_downscale_stabilization(2, 5, [4, 3, 5]) == 5

    def test_scaling_down_with_empty_history(self):
        assert apply_downscale_stabilization(2, 5, []) == 2

    def test_no_change(self):
        assert apply_downscale_stabilization(5, 5, [5, 5, 5]) == 5
