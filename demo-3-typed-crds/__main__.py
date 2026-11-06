import pulumi
import pulumi_kubernetes as k8s
import pulumi_gateway_networking as gateway_networking

gwapi = gateway_networking.gateway.v1

label = {"app": "podinfo"}

config = pulumi.Config()

provider = k8s.Provider(
    "provider",
    kubeconfig=config.require_secret("kubeconfig"),
)

opts = pulumi.ResourceOptions(provider=provider)

ns = k8s.core.v1.Namespace(
    "podinfo-gateway",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="podinfo-gateway"),
    opts=opts,
)

deployment = k8s.apps.v1.Deployment(
    "podinfo",
    metadata=k8s.meta.v1.ObjectMetaArgs(namespace=ns.metadata.name, labels=label),
    spec=k8s.apps.v1.DeploymentSpecArgs(
        replicas=2,
        selector=k8s.meta.v1.LabelSelectorArgs(match_labels=label),
        template=k8s.core.v1.PodTemplateSpecArgs(
            metadata=k8s.meta.v1.ObjectMetaArgs(labels=label),
            spec=k8s.core.v1.PodSpecArgs(
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="podinfo",
                        image="stefanprodan/podinfo",
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

# NodePort: pod IPs aren't routable from the VPC, so the ALB targets the nodes (instance mode).
service = k8s.core.v1.Service(
    "podinfo",
    metadata=k8s.meta.v1.ObjectMetaArgs(namespace=ns.metadata.name, labels=label),
    spec=k8s.core.v1.ServiceSpecArgs(
        type="NodePort",
        selector=label,
        ports=[k8s.core.v1.ServicePortArgs(name="http", port=80, target_port="http")],
    ),
    opts=opts,
)

gateway = gwapi.Gateway(
    "podinfo",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        namespace=ns.metadata.name,
        # Wait until the ALB exists so status.addresses is populated.
        annotations={"pulumi.com/waitFor": "condition=Programmed"},
    ),
    spec=gwapi.GatewaySpecArgs(
        gateway_class_name="aws-alb",
        listeners=[
            gwapi.GatewaySpecListenersArgs(
                name="http",
                protocol="HTTP",
                port=80,
                allowed_routes=gwapi.GatewaySpecListenersAllowedRoutesArgs(
                    namespaces=gwapi.GatewaySpecListenersAllowedRoutesNamespacesArgs(from_="Same"),
                ),
            )
        ],
    ),
    opts=opts,
)

route = gwapi.HTTPRoute(
    "podinfo",
    metadata=k8s.meta.v1.ObjectMetaArgs(namespace=ns.metadata.name),
    spec=gwapi.HTTPRouteSpecArgs(
        parent_refs=[gwapi.HTTPRouteSpecParentRefsArgs(name=gateway.metadata.name)],
        rules=[
            gwapi.HTTPRouteSpecRulesArgs(
                backend_refs=[
                    gwapi.HTTPRouteSpecRulesBackendRefsArgs(name=service.metadata.name, port=80)
                ],
            )
        ],
    ),
    opts=opts.merge(pulumi.ResourceOptions(depends_on=[deployment])),
)

pulumi.export("namespace", ns.metadata.name)
pulumi.export("url", gateway.status.addresses[0].value.apply(lambda v: f"http://{v}"))
