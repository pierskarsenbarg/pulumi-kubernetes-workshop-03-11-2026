import json
from pathlib import Path

import pulumi
import pulumi_kubernetes as k8s

config = pulumi.Config()

provider = k8s.Provider(
    "k8s",
    kubeconfig=config.require_secret("kubeconfig"),
)
opts = pulumi.ResourceOptions(provider=provider)

monitoring_ns = k8s.core.v1.Namespace(
    "monitoring",
    metadata={
        "name": "monitoring",
        # Talos enforces "baseline" by default; node-exporter needs host access.
        "labels": {"pod-security.kubernetes.io/enforce": "privileged"},
    },
    opts=opts,
)

pko_ns = k8s.core.v1.Namespace(
    "pulumi-kubernetes-operator",
    metadata={"name": "pulumi-kubernetes-operator"},
    opts=opts,
)

prometheus_stack = k8s.helm.v3.Release(
    "kube-prometheus-stack",
    name="kube-prometheus-stack",
    chart="oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack",
    version="92.17.0",
    namespace=monitoring_ns.metadata.name,
    values={
        "prometheus": {
            "prometheusSpec": {
                # Without this, Prometheus ignores ServiceMonitors not created by this chart.
                "serviceMonitorSelectorNilUsesHelmValues": False,
            },
        },
    },
    opts=opts,
)

# The chart only renders its ServiceMonitor once the monitoring.coreos.com CRDs exist.
pko = k8s.helm.v3.Release(
    "pulumi-kubernetes-operator",
    name="pulumi-kubernetes-operator",
    chart="oci://ghcr.io/pulumi/helm-charts/pulumi-kubernetes-operator",
    version="2.10.0",
    namespace=pko_ns.metadata.name,
    values={
        # The chart's ServiceMonitor scrapes plain HTTP, so serve metrics without TLS.
        "controller": {"metricsSecure": False},
        "serviceMonitor": {"enabled": True},
    },
    opts=pulumi.ResourceOptions(provider=provider, depends_on=[prometheus_stack]),
)

flux_ns = k8s.core.v1.Namespace(
    "flux-system",
    metadata={"name": "flux-system"},
    opts=opts,
)

# PKO only needs source-controller to fetch GitRepository artifacts.
# Flux's default NetworkPolicies block workspace pods in other namespaces from fetching artifacts.
flux = k8s.helm.v3.Release(
    "flux",
    name="flux",
    chart="flux2",
    version="2.19.1",
    repository_opts=k8s.helm.v3.RepositoryOptsArgs(
        repo="https://fluxcd-community.github.io/helm-charts",
    ),
    namespace=flux_ns.metadata.name,
    values={
        "helmController": {"create": False},
        "imageAutomationController": {"create": False},
        "imageReflectionController": {"create": False},
        "kustomizeController": {"create": False},
        "notificationController": {"create": False},
        "policies": {"create": False},
    },
    opts=opts,
)

dashboard_json = (
    Path(__file__).parent.joinpath("dashboards", "operator-metrics.json").read_text()
)
dashboard = json.loads(dashboard_json.replace("${DS_PROMETHEUS}", "prometheus"))
dashboard.pop("__inputs", None)

k8s.core.v1.ConfigMap(
    "pko-dashboard",
    metadata={
        "name": "pulumi-kubernetes-operator-dashboard",
        "namespace": monitoring_ns.metadata.name,
        "labels": {"grafana_dashboard": "1"},
    },
    data={"operator-metrics.json": json.dumps(dashboard)},
    opts=pulumi.ResourceOptions(provider=provider, depends_on=[prometheus_stack]),
)