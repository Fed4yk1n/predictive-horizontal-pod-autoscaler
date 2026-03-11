#!/usr/bin/env python3
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

"""
Entry point for the simple Python Predictive Horizontal Pod Autoscaler.

Usage:
    python main.py --config config.yaml
    python main.py --deployment my-app --namespace default --max-replicas 10
"""

import argparse
import logging
import sys

import yaml

from phpa.autoscaler import PredictiveAutoscaler
from phpa.config import (
    HoltWintersConfig,
    LinearConfig,
    MetricTarget,
    ModelConfig,
    PHPAConfig,
    ScaleTargetRef,
    MODEL_LINEAR,
    MODEL_HOLT_WINTERS,
    DEFAULT_DECISION_TYPE,
    DEFAULT_DOWNSCALE_STABILIZATION_SECONDS,
    DEFAULT_MIN_REPLICAS,
    DEFAULT_SYNC_PERIOD_SECONDS,
    DEFAULT_TOLERANCE,
    DEFAULT_CPU_TARGET_UTILIZATION,
)


def load_config_from_yaml(path: str) -> PHPAConfig:
    """Load PHPA configuration from a YAML file."""
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    spec = raw.get("spec", raw)

    # Parse scale target ref
    target_ref_raw = spec.get("scaleTargetRef", {})
    scale_target_ref = ScaleTargetRef(
        api_version=target_ref_raw.get("apiVersion", "apps/v1"),
        kind=target_ref_raw.get("kind", "Deployment"),
        name=target_ref_raw.get("name", ""),
        namespace=raw.get("metadata", {}).get("namespace", "default"),
    )

    # Parse metrics
    metrics = []
    for metric_raw in spec.get("metrics", []):
        resource = metric_raw.get("resource", {})
        target = resource.get("target", {})
        metrics.append(
            MetricTarget(
                metric_type=resource.get("name", "cpu"),
                average_utilization=target.get(
                    "averageUtilization", DEFAULT_CPU_TARGET_UTILIZATION
                ),
            )
        )

    # Parse models
    models = []
    for model_raw in spec.get("models", []):
        model_type = model_raw.get("type", MODEL_LINEAR)
        linear = None
        holt_winters = None

        if model_type == MODEL_LINEAR:
            linear_raw = model_raw.get("linear", {})
            linear = LinearConfig(
                history_size=linear_raw.get("historySize", 6),
                look_ahead=linear_raw.get("lookAhead", 10000),
            )
        elif model_type == MODEL_HOLT_WINTERS:
            hw_raw = model_raw.get("holtWinters", {})
            holt_winters = HoltWintersConfig(
                alpha=hw_raw.get("alpha", 0.9),
                beta=hw_raw.get("beta", 0.9),
                gamma=hw_raw.get("gamma", 0.9),
                trend=hw_raw.get("trend", "add"),
                seasonal=hw_raw.get("seasonal", "add"),
                seasonal_periods=hw_raw.get("seasonalPeriods", 2),
                stored_seasons=hw_raw.get("storedSeasons", 4),
                damped_trend=hw_raw.get("dampedTrend", False),
                initialization_method=hw_raw.get(
                    "initializationMethod", "estimated"
                ),
                initial_level=hw_raw.get("initialLevel"),
                initial_trend=hw_raw.get("initialTrend"),
                initial_seasonal=hw_raw.get("initialSeasonal"),
            )

        models.append(
            ModelConfig(
                name=model_raw.get("name", "default"),
                model_type=model_type,
                per_sync_period=model_raw.get("perSyncPeriod", 1),
                linear=linear,
                holt_winters=holt_winters,
            )
        )

    # Parse behavior
    behavior = spec.get("behavior", {})
    scale_down = behavior.get("scaleDown", {})
    downscale_stabilization = scale_down.get(
        "stabilizationWindowSeconds", DEFAULT_DOWNSCALE_STABILIZATION_SECONDS
    )

    return PHPAConfig(
        scale_target_ref=scale_target_ref,
        min_replicas=spec.get("minReplicas", DEFAULT_MIN_REPLICAS),
        max_replicas=spec.get("maxReplicas", 10),
        metrics=metrics,
        models=models,
        decision_type=spec.get("decisionType", DEFAULT_DECISION_TYPE),
        sync_period_seconds=spec.get("syncPeriod", DEFAULT_SYNC_PERIOD_SECONDS * 1000)
        // 1000,
        downscale_stabilization_seconds=downscale_stabilization,
        tolerance=spec.get("tolerance", DEFAULT_TOLERANCE),
    )


def build_config_from_args(args: argparse.Namespace) -> PHPAConfig:
    """Build PHPA configuration from command-line arguments."""
    models = []
    if args.model == MODEL_LINEAR:
        models.append(
            ModelConfig(
                name="linear",
                model_type=MODEL_LINEAR,
                linear=LinearConfig(
                    history_size=args.history_size,
                    look_ahead=args.look_ahead,
                ),
            )
        )
    elif args.model == MODEL_HOLT_WINTERS:
        models.append(
            ModelConfig(
                name="holt-winters",
                model_type=MODEL_HOLT_WINTERS,
                holt_winters=HoltWintersConfig(
                    alpha=args.alpha,
                    beta=args.beta,
                    gamma=args.gamma,
                    trend=args.trend,
                    seasonal=args.seasonal,
                    seasonal_periods=args.seasonal_periods,
                    stored_seasons=args.stored_seasons,
                ),
            )
        )

    metrics = [
        MetricTarget(
            metric_type="cpu",
            average_utilization=args.cpu_target,
        )
    ]

    return PHPAConfig(
        scale_target_ref=ScaleTargetRef(
            kind=args.kind,
            name=args.deployment,
            namespace=args.namespace,
        ),
        min_replicas=args.min_replicas,
        max_replicas=args.max_replicas,
        metrics=metrics,
        models=models,
        decision_type=args.decision_type,
        sync_period_seconds=args.sync_period,
        downscale_stabilization_seconds=args.downscale_stabilization,
        tolerance=args.tolerance,
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Simple Predictive Horizontal Pod Autoscaler (Python)"
    )

    parser.add_argument(
        "--config",
        type=str,
        help="Path to a YAML configuration file (same format as the PHPA CRD spec)",
    )
    parser.add_argument("--deployment", type=str, help="Deployment name to scale")
    parser.add_argument(
        "--namespace", type=str, default="default", help="Kubernetes namespace"
    )
    parser.add_argument(
        "--kind",
        type=str,
        default="Deployment",
        choices=["Deployment", "StatefulSet"],
        help="Kind of the scale target",
    )
    parser.add_argument("--min-replicas", type=int, default=DEFAULT_MIN_REPLICAS)
    parser.add_argument("--max-replicas", type=int, default=10)
    parser.add_argument("--cpu-target", type=int, default=DEFAULT_CPU_TARGET_UTILIZATION)
    parser.add_argument(
        "--model",
        type=str,
        default=MODEL_LINEAR,
        choices=[MODEL_LINEAR, MODEL_HOLT_WINTERS],
    )
    parser.add_argument(
        "--decision-type",
        type=str,
        default=DEFAULT_DECISION_TYPE,
        choices=["maximum", "minimum", "mean", "median"],
    )
    parser.add_argument(
        "--sync-period",
        type=int,
        default=DEFAULT_SYNC_PERIOD_SECONDS,
        help="Sync period in seconds",
    )
    parser.add_argument(
        "--downscale-stabilization",
        type=int,
        default=DEFAULT_DOWNSCALE_STABILIZATION_SECONDS,
    )
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    parser.add_argument(
        "--in-cluster",
        action="store_true",
        default=False,
        help="Use in-cluster Kubernetes configuration",
    )

    # Linear model arguments
    parser.add_argument("--history-size", type=int, default=6)
    parser.add_argument("--look-ahead", type=int, default=10000, help="Look ahead in ms")

    # Holt-Winters arguments
    parser.add_argument("--alpha", type=float, default=0.9)
    parser.add_argument("--beta", type=float, default=0.9)
    parser.add_argument("--gamma", type=float, default=0.9)
    parser.add_argument("--trend", type=str, default="add", choices=["add", "mul"])
    parser.add_argument(
        "--seasonal", type=str, default="add", choices=["add", "mul"]
    )
    parser.add_argument("--seasonal-periods", type=int, default=2)
    parser.add_argument("--stored-seasons", type=int, default=4)

    # Logging
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.config:
        phpa_config = load_config_from_yaml(args.config)
    elif args.deployment:
        phpa_config = build_config_from_args(args)
    else:
        parser.error("Either --config or --deployment is required")
        sys.exit(1)

    autoscaler = PredictiveAutoscaler(phpa_config, in_cluster=args.in_cluster)
    autoscaler.run()


if __name__ == "__main__":
    main()
