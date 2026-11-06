import pulumi
import pulumi_kubernetes as k8s

label = {"app": "podinfo"}

config = pulumi.Config()

provider = k8s.Provider(
    "provider",
    kubeconfig=config.require_secret("kubeconfig"),
    # render_yaml_to_directory="./rendered",
)

opts = pulumi.ResourceOptions(provider=provider)

ns = k8s.core.v1.Namespace(
    "podinfo",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="podinfo"),
    opts=opts,
)

deployment = k8s.apps.v1.Deployment(
    "podinfo",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        namespace=ns.metadata.name,
        labels=label,
        annotations={"pulumi.com/patchForce": "true"},
    ),
    spec=k8s.apps.v1.DeploymentSpecArgs(
        replicas=2,
        selector=k8s.meta.v1.LabelSelectorArgs(match_labels=label),
        template=k8s.core.v1.PodTemplateSpecArgs(
            metadata=k8s.meta.v1.ObjectMetaArgs(labels=label),
            spec=k8s.core.v1.PodSpecArgs(
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="podinfo",
                        image=f"stefanprodan/podinfo",
                        ports=[k8s.core.v1.ContainerPortArgs(name="http", container_port=9898)],
                        readiness_probe=k8s.core.v1.ProbeArgs(
                            http_get=k8s.core.v1.HTTPGetActionArgs(path="/readyz", port="http"),
                        ),
                    )
                ],
            ),
        ),
    ),
    opts=opts,
)

service = k8s.core.v1.Service(
    "podinfo",
    metadata=k8s.meta.v1.ObjectMetaArgs(namespace=ns.metadata.name, labels=label),
    spec=k8s.core.v1.ServiceSpecArgs(
        type="LoadBalancer",
        selector=label,
        ports=[k8s.core.v1.ServicePortArgs(port=80, target_port="http")],
    ),
    opts=opts.merge(pulumi.ResourceOptions(depends_on=[deployment])),
)

pulumi.export("namespace", ns.metadata.name)
pulumi.export("deploymentName", deployment.metadata.name)
pulumi.export("serviceName", service.metadata.name)
pulumi.export(
    "url",
    service.status.load_balancer.ingress[0].apply(lambda i: f"http://{i.hostname or i.ip}"),
)
