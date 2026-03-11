[![Build](https://github.com/jthomperoo/predictive-horizontal-pod-autoscaler/workflows/main/badge.svg)](https://github.com/jthomperoo/predictive-horizontal-pod-autoscaler/actions)
[![go.dev](https://img.shields.io/badge/go.dev-reference-007d9c?logo=go&logoColor=white&style=flat)](https://pkg.go.dev/github.com/jthomperoo/predictive-horizontal-pod-autoscaler)
[![Go Report Card](https://goreportcard.com/badge/github.com/jthomperoo/predictive-horizontal-pod-autoscaler)](https://goreportcard.com/report/github.com/jthomperoo/predictive-horizontal-pod-autoscaler)
[![Documentation Status](https://readthedocs.org/projects/predictive-horizontal-pod-autoscaler/badge/?version=latest)](https://predictive-horizontal-pod-autoscaler.readthedocs.io/en/latest)
[![License](https://img.shields.io/:license-apache-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0.html)

# Predictive Horizontal Pod Autoscaler

Predictive Horizontal Pod Autoscalers (PHPAs) are Horizontal Pod Autoscalers (HPAs) with extra predictive capabilities,
allowing you to autoscale using statistical models for ahead of time predictions.

## Why would I use it?

PHPAs can better scaling results by making proactive decisions to scale up ahead of demand, meaning that a
resource does not have to wait for performance to degrade before autoscaling kicks in.

## What systems would need it?

Any systems that have regular/predictable demand peaks/troughs.

Some use cases:

* A service that sees demand peak between 3pm and 5pm every week day, this is a regular and predictable load which
could be pre-empted.
* A service which sees a surge in demand at 12pm every day for 10 minutes, this is such a short time interval that
by the time a regular HPA made the decision to scale up there could already be major performance/availablity issues.

PHPAs are not a silver bullet, and require tuning using real data for there to be any benefits of using it. A poorly
tuned PHPA could easily end up being worse than a normal HPA.

## How does it work?

This project works by doing the same calculations as the Horizontal Pod Autoscaler does to determine how many replicas
a resource should have, then applies statistical models against the calculated replica count and the replica history.

## Supported Kubernetes versions

The minimum Kubernetes version the autoscaler can run on is `v1.23` because it relies on the `autoscaling/v2` API which
was only available in `v1.23` and above.

The autoscaler is only tested against the latest Kubernetes version - if there are bugs that affect older Kubernetes
versions we will try to fix them, but there is no guarantee of support.

## Features

* Functionally identical to Horizontal Pod Autoscaler for calculating replica counts without prediction.
* Choice of statistical models to apply over Horizontal Pod Autoscaler replica counting logic.
  * Holt-Winters Smoothing
  * Linear Regression
* Allows customisation of Kubernetes autoscaling options without master node access. Can therefore work on managed
solutions such as EKS or GCP.
  * CPU Initialization Period.
  * Downscale Stabilization.
  * Sync Period.

## What does a Predictive Horizontal Pod Autoscaler look like?

PHPAs are designed to be as similar in configuration to Horizontal Pod Autoscalers as possible, with extra
configuration options.

PHPAs have their own custom resource:

```yaml
apiVersion: jamiethompson.me/v1alpha1
kind: PredictiveHorizontalPodAutoscaler
metadata:
  name: simple-linear
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: php-apache
  minReplicas: 1
  maxReplicas: 10
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 0
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          averageUtilization: 50
          type: Utilization
  models:
    - type: Linear
      name: simple-linear
      linear:
        lookAhead: 10000
        historySize: 6
```

This PHPA acts like a Horizontal Pod Autoscaler and autoscales to try and keep the target resource's CPU utilization at
50%, but with the extra predictive layer of a linear regression model applied to the results.

## Prerequisites

To deploy PHPAs to a Kubernetes cluster you need:

* [kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl) >= `v1.23`
* [Helm](https://helm.sh/docs/intro/install/) >= `v3`
* A running Kubernetes cluster (>= `v1.23`) with the [metrics server](https://github.com/kubernetes-sigs/metrics-server)
  enabled. For local development you can use [k3d](https://k3d.io/) or [minikube](https://minikube.sigs.k8s.io/).

## Installation

The operator for managing Predictive Horizontal Pod Autoscalers can be installed using Helm:

```bash
VERSION=v0.13.2
HELM_CHART=predictive-horizontal-pod-autoscaler-operator
helm install ${HELM_CHART} https://github.com/jthomperoo/predictive-horizontal-pod-autoscaler/releases/download/${VERSION}/predictive-horizontal-pod-autoscaler-${VERSION}.tgz
```

Verify the operator is running:

```bash
helm status predictive-horizontal-pod-autoscaler-operator
```

## Quick start

Once the operator is installed, you can deploy a sample workload and autoscaler to see it in action.

### 1. Deploy a test application

```bash
kubectl apply -f examples/simple-linear/deployment.yaml
```

### 2. Deploy a Predictive Horizontal Pod Autoscaler

```bash
kubectl apply -f examples/simple-linear/phpa.yaml
```

### 3. Verify the autoscaler is running

```bash
kubectl get phpa simple-linear
```

### 4. Watch the operator logs

```bash
kubectl logs -l name=predictive-horizontal-pod-autoscaler -f
```

### 5. Generate load to trigger autoscaling

In a separate terminal, start a load generator:

```bash
kubectl run -it --rm load-generator --image=busybox -- /bin/sh -c "while true; do wget -q -O- http://php-apache.default.svc.cluster.local; done"
```

You should see the number of replicas increase in the operator logs. Stop the load generator with `Ctrl+C` and the
replicas will scale back down.

### 6. Clean up

```bash
kubectl delete -f examples/simple-linear/phpa.yaml
kubectl delete -f examples/simple-linear/deployment.yaml
```

For a detailed walkthrough, see the [getting started
guide](https://predictive-horizontal-pod-autoscaler.readthedocs.io/en/latest/user-guide/getting-started/). More
examples are available in the [`examples/` directory](./examples).

## More information

See the [wiki for more information, such as guides and
references](https://predictive-horizontal-pod-autoscaler.readthedocs.io/en/latest/).

See the [`examples/` directory](./examples) for working code samples.

## Developing this project

### Dependencies

* [Go](https://golang.org/doc/install) >= `1.20`
* [Python](https://www.python.org/downloads/) == `3.8.x`
* [Helm](https://helm.sh/) == `3.9.x`
* A running Kubernetes cluster configured via `kubeconfig` (e.g. [k3d](https://k3d.io/))

### Getting started

Install Python dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the operator locally against the cluster configured in your kubeconfig:

```bash
make run
```

This uses [Air](https://github.com/cosmtrek/air) for live-reloading. The operator connects to the cluster in your
current kubeconfig context and will manage any PHPA resources on that cluster.

You can then deploy a PHPA example (see the [`examples/` directory](./examples) for choices) to test your changes.

This project extensively uses the [jthomperoo/k8shorizmetrics](https://github.com/jthomperoo/k8shorizmetrics) library
to gather metrics and to evaluate them as the Kubernetes Horizontal Pod Autoscaler does.

### Commands

* `make run` - runs the PHPA locally against the cluster configured in your kubeconfig file.
* `make docker` - builds the PHPA Docker image.
* `make test` - runs the unit tests (Go and Python).
* `make lint` - lints the code.
* `make format` - formats the code, must be run to pass the CI.
* `make doc` - hosts the documentation locally at <https://localhost:8000>.
* `make coverage` - opens up any generated coverage reports in the browser.
