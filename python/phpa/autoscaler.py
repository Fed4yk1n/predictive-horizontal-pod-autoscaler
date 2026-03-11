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

"""Main autoscaler reconciliation loop for the Predictive Horizontal Pod Autoscaler."""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException

from .config import (
    ModelConfig,
    ModelHistory,
    PHPAConfig,
    TimestampedReplicas,
    DEFAULT_DECISION_TYPE,
)
from .decision import apply_downscale_stabilization, apply_min_max, decide_replicas
from .prediction import get_prediction, prune_history

logger = logging.getLogger(__name__)


class PredictiveAutoscaler:
    """
    A simple Predictive Horizontal Pod Autoscaler.

    Implements the core reconciliation loop:
    1. Get current replica count and CPU metrics from the target deployment
    2. Calculate desired replicas based on CPU utilization
    3. Feed the calculated value into prediction models
    4. Combine predictions using the configured decision strategy
    5. Apply scaling constraints (min/max, downscale stabilization)
    6. Scale the target deployment

    Attributes:
        config: The PHPA configuration.
        model_histories: Stored state for each prediction model.
        recent_recommendations: Recent scaling recommendations for stabilization.
    """

    def __init__(self, phpa_config: PHPAConfig, in_cluster: bool = True):
        """
        Initialize the autoscaler.

        Args:
            phpa_config: The PHPA configuration.
            in_cluster: Whether running inside a Kubernetes cluster.
                If False, uses local kubeconfig.
        """
        self.config = phpa_config
        self.model_histories: Dict[str, ModelHistory] = {}
        self.recent_recommendations: List[int] = []
        self._last_scale_time: Optional[datetime] = None

        if in_cluster:
            k8s_config.load_incluster_config()
        else:
            k8s_config.load_kube_config()

        self.apps_v1 = client.AppsV1Api()
        self.metrics_api = None
        try:
            self.metrics_api = client.CustomObjectsApi()
        except Exception:
            logger.warning("Could not initialize metrics API client")

    def run(self):
        """Run the autoscaler reconciliation loop indefinitely."""
        logger.info(
            "Starting Predictive Horizontal Pod Autoscaler for %s/%s",
            self.config.scale_target_ref.kind,
            self.config.scale_target_ref.name,
        )
        logger.info(
            "Sync period: %ds, Min replicas: %d, Max replicas: %d",
            self.config.sync_period_seconds,
            self.config.min_replicas,
            self.config.max_replicas,
        )

        while True:
            try:
                self.reconcile()
            except Exception:
                logger.exception("Error during reconciliation")
            time.sleep(self.config.sync_period_seconds)

    def reconcile(self):
        """
        Perform a single reconciliation cycle.

        Gets current state, calculates desired replicas, applies predictions,
        and scales the target if needed.
        """
        now = datetime.now(timezone.utc)
        ref = self.config.scale_target_ref

        # Get current replica count
        current_replicas = self._get_current_replicas()
        if current_replicas is None:
            logger.error("Could not get current replicas for %s/%s", ref.kind, ref.name)
            return

        # Calculate desired replicas based on metrics
        calculated_replicas = self._calculate_replicas(current_replicas)

        # Process prediction models
        predicted_replicas = [calculated_replicas]
        for model_config in self.config.models:
            try:
                prediction = self._process_model(model_config, now, calculated_replicas)
                if prediction is not None:
                    predicted_replicas.append(prediction)
            except Exception:
                logger.exception(
                    "Error processing model '%s'", model_config.name
                )

        # Decide target replicas based on decision strategy
        target_replicas = decide_replicas(
            self.config.decision_type, predicted_replicas
        )

        # Apply downscale stabilization
        target_replicas = apply_downscale_stabilization(
            target_replicas, current_replicas, self.recent_recommendations
        )

        # Update recent recommendations (keep within stabilization window)
        max_recommendations = max(
            1,
            self.config.downscale_stabilization_seconds
            // self.config.sync_period_seconds,
        )
        self.recent_recommendations.append(target_replicas)
        if len(self.recent_recommendations) > max_recommendations:
            self.recent_recommendations = self.recent_recommendations[
                -max_recommendations:
            ]

        # Apply min/max constraints
        target_replicas = apply_min_max(
            target_replicas, self.config.min_replicas, self.config.max_replicas
        )

        # Scale if needed
        if target_replicas != current_replicas:
            logger.info(
                "Scaling %s/%s from %d to %d replicas",
                ref.kind,
                ref.name,
                current_replicas,
                target_replicas,
            )
            self._scale(target_replicas)
        else:
            logger.debug(
                "No scaling needed for %s/%s (current: %d)",
                ref.kind,
                ref.name,
                current_replicas,
            )

        self._last_scale_time = now

    def _get_current_replicas(self) -> Optional[int]:
        """Get the current replica count from the target deployment."""
        ref = self.config.scale_target_ref
        try:
            if ref.kind == "Deployment":
                deployment = self.apps_v1.read_namespaced_deployment(
                    name=ref.name, namespace=ref.namespace
                )
                return deployment.spec.replicas
            if ref.kind == "StatefulSet":
                statefulset = self.apps_v1.read_namespaced_stateful_set(
                    name=ref.name, namespace=ref.namespace
                )
                return statefulset.spec.replicas
            logger.error("Unsupported scale target kind: %s", ref.kind)
            return None
        except ApiException as e:
            logger.error("Failed to get current replicas: %s", e)
            return None

    def _calculate_replicas(self, current_replicas: int) -> int:
        """
        Calculate desired replicas based on CPU metrics.

        Uses the same formula as the standard Kubernetes HPA:
        desiredReplicas = ceil(currentReplicas * (currentUtilization / targetUtilization))

        Falls back to current replicas if metrics are unavailable.
        """
        ref = self.config.scale_target_ref
        target_cpu = None
        for metric in self.config.metrics:
            if metric.metric_type == "cpu":
                target_cpu = metric.average_utilization
                break

        if target_cpu is None or self.metrics_api is None:
            return current_replicas

        try:
            # Fetch pod metrics from the metrics API
            pod_metrics = self.metrics_api.list_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=ref.namespace,
                plural="pods",
            )

            # Calculate average CPU utilization across pods belonging to the target
            total_cpu = 0
            pod_count = 0
            for pod in pod_metrics.get("items", []):
                for container in pod.get("containers", []):
                    cpu_usage = container.get("usage", {}).get("cpu", "0")
                    total_cpu += self._parse_cpu(cpu_usage)
                    pod_count += 1

            if pod_count == 0:
                return current_replicas

            avg_cpu = (total_cpu / pod_count) * 100  # as percentage

            # HPA formula: desiredReplicas = ceil(currentReplicas * (currentUtil / targetUtil))
            ratio = avg_cpu / target_cpu
            if abs(1.0 - ratio) <= self.config.tolerance:
                return current_replicas

            import math
            desired = math.ceil(current_replicas * ratio)
            return max(1, desired)

        except Exception:
            logger.debug(
                "Could not fetch metrics, using current replicas", exc_info=True
            )
            return current_replicas

    def _process_model(
        self,
        model_config: ModelConfig,
        now: datetime,
        calculated_replicas: int,
    ) -> Optional[int]:
        """
        Process a single prediction model.

        Updates the model's history, runs prediction if due, and prunes history.

        Returns:
            Predicted replica count, or None if the model was skipped.
        """
        # Get or create model history
        history = self.model_histories.get(model_config.name)
        if history is None or history.model_type != model_config.model_type:
            history = ModelHistory(
                model_type=model_config.model_type,
                sync_periods_passed=1,
                replica_history=[],
            )

        # Add current calculated replicas to history
        history.replica_history.append(
            TimestampedReplicas(time=now, replicas=calculated_replicas)
        )

        prediction = None
        should_run = history.sync_periods_passed >= model_config.per_sync_period

        if should_run:
            try:
                prediction = get_prediction(
                    model_config, history.replica_history, now
                )
                history.sync_periods_passed = 1
                logger.debug(
                    "Model '%s' predicted %d replicas",
                    model_config.name,
                    prediction,
                )
            except ValueError as e:
                logger.warning(
                    "Model '%s' could not make prediction: %s",
                    model_config.name,
                    e,
                )
                history.sync_periods_passed += 1
        else:
            history.sync_periods_passed += 1

        # Prune history
        history.replica_history = prune_history(
            model_config, history.replica_history
        )

        self.model_histories[model_config.name] = history
        return prediction

    def _scale(self, target_replicas: int):
        """Scale the target resource to the desired replica count."""
        ref = self.config.scale_target_ref
        body = {"spec": {"replicas": target_replicas}}
        try:
            if ref.kind == "Deployment":
                self.apps_v1.patch_namespaced_deployment_scale(
                    name=ref.name, namespace=ref.namespace, body=body
                )
            elif ref.kind == "StatefulSet":
                self.apps_v1.patch_namespaced_stateful_set_scale(
                    name=ref.name, namespace=ref.namespace, body=body
                )
            else:
                logger.error("Unsupported scale target kind: %s", ref.kind)
        except ApiException as e:
            logger.error("Failed to scale %s/%s: %s", ref.kind, ref.name, e)

    @staticmethod
    def _parse_cpu(cpu_str: str) -> float:
        """
        Parse a Kubernetes CPU resource string to cores.

        Handles formats like "100m" (millicores) and "1" (cores).
        """
        if cpu_str.endswith("n"):
            return int(cpu_str[:-1]) / 1_000_000_000
        if cpu_str.endswith("u"):
            return int(cpu_str[:-1]) / 1_000_000
        if cpu_str.endswith("m"):
            return int(cpu_str[:-1]) / 1000
        return float(cpu_str)
