# Predictive Horizontal Pod Autoscaler - Simple Python Version

A simple, standalone Python implementation of the [Predictive Horizontal Pod Autoscaler](https://github.com/jthomperoo/predictive-horizontal-pod-autoscaler).

This version provides the core predictive autoscaling functionality in a single Python package,
making it easy to understand, modify, and deploy.

## Features

- **Linear Regression** prediction model — predicts future replica counts based on historical trends
- **Holt-Winters Exponential Smoothing** prediction model — captures seasonal patterns for more accurate predictions
- **Decision Strategies** — combine predictions from multiple models using maximum, minimum, mean, or median
- **Downscale Stabilization** — prevents rapid scale-down fluctuations
- **Min/Max Replica Constraints** — enforces bounds on scaling
- **Kubernetes Integration** — reads metrics and scales Deployments/StatefulSets via the Kubernetes API

## Quick Start

### Installation

```bash
cd python
pip install -r requirements.txt
```

### Usage

#### With a YAML config file (same format as the PHPA CRD):

```bash
python main.py --config ../examples/simple-linear/phpa.yaml
```

#### With command-line arguments:

```bash
python main.py \
  --deployment my-app \
  --namespace default \
  --min-replicas 1 \
  --max-replicas 10 \
  --cpu-target 50 \
  --model Linear \
  --look-ahead 10000 \
  --history-size 6 \
  --sync-period 15
```

#### Using Holt-Winters instead of Linear Regression:

```bash
python main.py \
  --deployment my-app \
  --model HoltWinters \
  --alpha 0.9 --beta 0.9 --gamma 0.9 \
  --seasonal-periods 24 \
  --stored-seasons 4 \
  --trend add --seasonal add
```

### Running in a Kubernetes Cluster

When running inside a cluster (e.g., as a Pod), use the `--in-cluster` flag:

```bash
python main.py --config /etc/phpa/config.yaml --in-cluster
```

## Architecture

```
python/
├── main.py                  # Entry point / CLI
├── requirements.txt         # Python dependencies
├── phpa/
│   ├── __init__.py
│   ├── config.py            # Configuration data classes
│   ├── prediction.py        # Linear regression & Holt-Winters models
│   ├── decision.py          # Decision strategies (max/min/mean/median)
│   └── autoscaler.py        # Main reconciliation loop
└── tests/
    ├── test_decision.py     # Decision strategy tests
    ├── test_prediction.py   # Prediction model tests
    └── test_autoscaler.py   # Autoscaler integration tests
```

### How It Works

1. **Metrics Collection**: Reads CPU utilization from the Kubernetes Metrics API
2. **Replica Calculation**: Applies the standard HPA formula:
   `desiredReplicas = ceil(currentReplicas × (currentUtilization / targetUtilization))`
3. **Prediction**: Feeds the calculated replica count into prediction models:
   - **Linear Regression**: Uses OLS to predict replicas at a future time point
   - **Holt-Winters**: Captures trend and seasonal patterns to forecast the next value
4. **Decision**: Combines predictions using the configured strategy (default: maximum)
5. **Stabilization**: Applies downscale stabilization to prevent rapid fluctuations
6. **Constraints**: Clamps the result to min/max replica bounds
7. **Scaling**: Updates the target Deployment/StatefulSet replica count

## Configuration Reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--deployment` | (required) | Name of the Deployment to scale |
| `--namespace` | `default` | Kubernetes namespace |
| `--kind` | `Deployment` | Target kind (`Deployment` or `StatefulSet`) |
| `--min-replicas` | `1` | Minimum replica count |
| `--max-replicas` | `10` | Maximum replica count |
| `--cpu-target` | `80` | Target CPU utilization percentage |
| `--model` | `Linear` | Prediction model (`Linear` or `HoltWinters`) |
| `--decision-type` | `maximum` | Strategy: `maximum`, `minimum`, `mean`, `median` |
| `--sync-period` | `15` | Reconciliation interval in seconds |
| `--downscale-stabilization` | `300` | Downscale stabilization window in seconds |
| `--tolerance` | `0.1` | Minimum ratio change to trigger scaling |

### Linear Regression Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--look-ahead` | `10000` | How far ahead to predict (milliseconds) |
| `--history-size` | `6` | Number of historical data points to keep |

### Holt-Winters Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--alpha` | `0.9` | Smoothing level parameter |
| `--beta` | `0.9` | Smoothing trend parameter |
| `--gamma` | `0.9` | Smoothing seasonal parameter |
| `--trend` | `add` | Trend type (`add` or `mul`) |
| `--seasonal` | `add` | Seasonal type (`add` or `mul`) |
| `--seasonal-periods` | `2` | Number of periods in a seasonal cycle |
| `--stored-seasons` | `4` | Number of seasons to store in history |

## Running Tests

```bash
cd python
pip install -r requirements.txt
pip install pytest
pytest tests/ -v
```

## Comparison with the Full Version

| Feature | Full (Go+Python) | Simple (Python) |
|---------|------------------|-----------------|
| Kubernetes Operator (CRD) | ✅ | ❌ (standalone script) |
| Linear Regression | ✅ | ✅ |
| Holt-Winters | ✅ | ✅ |
| Decision Strategies | ✅ | ✅ |
| Downscale Stabilization | ✅ | ✅ (simplified) |
| HPA Scaling Policies | ✅ | ❌ |
| Per-sync-period Model Execution | ✅ | ✅ |
| Start Intervals | ✅ | ❌ |
| Reset Duration | ✅ | ❌ |
| Runtime Tuning Hooks | ✅ | ❌ |
| ConfigMap State Persistence | ✅ | ❌ (in-memory) |
| Multiple Metrics | ✅ | CPU only |
