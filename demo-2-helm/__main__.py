import pulumi
import pulumi_kubernetes as k8s

podinfo_repo = "https://stefanprodan.github.io/podinfo"

replicas = 1

config = pulumi.Config()

provider = k8s.Provider(
    "provider",
    kubeconfig=config.require_secret("kubeconfig"),
)

opts = pulumi.ResourceOptions(provider=provider)

# Helm installs this one: one Pulumi resource, visible in `helm list`.
release = k8s.helm.v3.Release(
    "podinfo-release",
    k8s.helm.v3.ReleaseArgs(
        name="podinfo",
        chart="podinfo",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(repo=podinfo_repo),
        namespace="podinfo-release",
        create_namespace=True,
        values={"replicaCount": replicas},
    ),
    opts=opts,
)


def add_team_label(args: pulumi.ResourceTransformArgs):
    if not args.type_.startswith("kubernetes:"):
        return None
    
    props = args.props
    metadata = pulumi.Output.from_input(props.get("metadata", {}))
    metadata["labels"] = {**(metadata.get("labels") or {}), "team": "platform"}
    props["metadata"] = metadata
    return pulumi.ResourceTransformResult(props=props, opts=args.opts)


chart_ns = k8s.core.v1.Namespace(
    "podinfo-chart",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="podinfo-chart"),
    opts=opts,
)

# Pulumi renders the chart and manages each object itself, so there is no Helm release.
chart = k8s.helm.v4.Chart(
    "podinfo-chart",
    k8s.helm.v4.ChartArgs(
        chart="podinfo",
        repository_opts=k8s.helm.v4.RepositoryOptsArgs(repo=podinfo_repo),
        namespace=chart_ns.metadata.name,
        values={"replicaCount": replicas},
    ),
    opts=opts.merge(
        pulumi.ResourceOptions(
            transforms=[add_team_label],
        )
    ),
)

pulumi.export("releaseNamespace", release.status.namespace)
pulumi.export("chartNamespace", chart_ns.metadata.name)
