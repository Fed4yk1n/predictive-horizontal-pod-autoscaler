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

"""Tests for the autoscaler module."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from phpa.autoscaler import PredictiveAutoscaler
from phpa.config import (
    LinearConfig,
    MetricTarget,
    ModelConfig,
    PHPAConfig,
    ScaleTargetRef,
)


@pytest.fixture
def basic_config():
    """A basic PHPA configuration for testing."""
    return PHPAConfig(
        scale_target_ref=ScaleTargetRef(
            kind="Deployment",
            name="test-app",
            namespace="default",
        ),
        min_replicas=1,
        max_replicas=10,
        metrics=[MetricTarget(metric_type="cpu", average_utilization=50)],
        models=[
            ModelConfig(
                name="test-linear",
                model_type="Linear",
                linear=LinearConfig(history_size=6, look_ahead=10000),
            )
        ],
        decision_type="maximum",
        sync_period_seconds=15,
        downscale_stabilization_seconds=30,
    )


class TestParseCpu:
    """Tests for CPU resource string parsing."""

    def test_millicores(self):
        assert PredictiveAutoscaler._parse_cpu("100m") == 0.1

    def test_cores(self):
        assert PredictiveAutoscaler._parse_cpu("1") == 1.0

    def test_nanocores(self):
        assert PredictiveAutoscaler._parse_cpu("1000000000n") == 1.0

    def test_microcores(self):
        assert PredictiveAutoscaler._parse_cpu("1000000u") == 1.0


class TestReconcile:
    """Tests for the reconciliation logic."""

    @patch("phpa.autoscaler.k8s_config")
    @patch("phpa.autoscaler.client")
    def test_reconcile_no_change_needed(self, mock_client, mock_k8s_config, basic_config):
        """When calculated replicas match current, no scaling should occur."""
        mock_apps = MagicMock()
        mock_deployment = MagicMock()
        mock_deployment.spec.replicas = 5
        mock_apps.read_namespaced_deployment.return_value = mock_deployment
        mock_client.AppsV1Api.return_value = mock_apps
        mock_client.CustomObjectsApi.return_value = MagicMock()

        autoscaler = PredictiveAutoscaler(basic_config, in_cluster=False)
        autoscaler.apps_v1 = mock_apps

        # Mock _calculate_replicas to return current
        autoscaler._calculate_replicas = MagicMock(return_value=5)

        autoscaler.reconcile()

        mock_apps.patch_namespaced_deployment_scale.assert_not_called()

    @patch("phpa.autoscaler.k8s_config")
    @patch("phpa.autoscaler.client")
    def test_reconcile_scale_up(self, mock_client, mock_k8s_config, basic_config):
        """When predictions indicate higher replicas, should scale up."""
        mock_apps = MagicMock()
        mock_deployment = MagicMock()
        mock_deployment.spec.replicas = 3
        mock_apps.read_namespaced_deployment.return_value = mock_deployment
        mock_client.AppsV1Api.return_value = mock_apps
        mock_client.CustomObjectsApi.return_value = MagicMock()

        autoscaler = PredictiveAutoscaler(basic_config, in_cluster=False)
        autoscaler.apps_v1 = mock_apps

        # Mock to return higher replicas
        autoscaler._calculate_replicas = MagicMock(return_value=7)

        autoscaler.reconcile()

        mock_apps.patch_namespaced_deployment_scale.assert_called_once()
        call_args = mock_apps.patch_namespaced_deployment_scale.call_args
        assert call_args.kwargs["body"]["spec"]["replicas"] == 7

    @patch("phpa.autoscaler.k8s_config")
    @patch("phpa.autoscaler.client")
    def test_reconcile_respects_max_replicas(self, mock_client, mock_k8s_config, basic_config):
        """Scaling should never exceed max_replicas."""
        mock_apps = MagicMock()
        mock_deployment = MagicMock()
        mock_deployment.spec.replicas = 5
        mock_apps.read_namespaced_deployment.return_value = mock_deployment
        mock_client.AppsV1Api.return_value = mock_apps
        mock_client.CustomObjectsApi.return_value = MagicMock()

        autoscaler = PredictiveAutoscaler(basic_config, in_cluster=False)
        autoscaler.apps_v1 = mock_apps

        # Mock to return way more than max
        autoscaler._calculate_replicas = MagicMock(return_value=50)

        autoscaler.reconcile()

        mock_apps.patch_namespaced_deployment_scale.assert_called_once()
        call_args = mock_apps.patch_namespaced_deployment_scale.call_args
        assert call_args.kwargs["body"]["spec"]["replicas"] == 10  # max_replicas

    @patch("phpa.autoscaler.k8s_config")
    @patch("phpa.autoscaler.client")
    def test_reconcile_respects_min_replicas(self, mock_client, mock_k8s_config, basic_config):
        """Scaling should never go below min_replicas."""
        mock_apps = MagicMock()
        mock_deployment = MagicMock()
        mock_deployment.spec.replicas = 5
        mock_apps.read_namespaced_deployment.return_value = mock_deployment
        mock_client.AppsV1Api.return_value = mock_apps
        mock_client.CustomObjectsApi.return_value = MagicMock()

        autoscaler = PredictiveAutoscaler(basic_config, in_cluster=False)
        autoscaler.apps_v1 = mock_apps
        autoscaler.recent_recommendations = []

        # Mock to return 0
        autoscaler._calculate_replicas = MagicMock(return_value=0)

        autoscaler.reconcile()

        mock_apps.patch_namespaced_deployment_scale.assert_called_once()
        call_args = mock_apps.patch_namespaced_deployment_scale.call_args
        assert call_args.kwargs["body"]["spec"]["replicas"] == 1  # min_replicas
