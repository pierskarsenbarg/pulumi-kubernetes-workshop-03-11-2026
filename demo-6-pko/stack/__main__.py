import pulumi
import pulumi_kubernetes as k8s
import pulumi_flux_source as flux_source
import pulumi_pulumi_operator as pulumi_operator

flux = flux_source.source.v1
pko = pulumi_operator.pulumi.v1

org = "pierskarsenbarg"

config = pulumi.Config()

provider = k8s.Provider(
    "provider",
    kubeconfig=config.require_secret("kubeconfig"),
)

opts = pulumi.ResourceOptions(provider=provider)

eso_stack = pulumi.StackReference(f"{org}/demo-5-eso/dev")

ns = k8s.core.v1.Namespace(
    "simple-random",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="simple-random"),
    opts=opts,
)

# Stack envRefs can only read Secrets in the Stack's own namespace.
token_secret = k8s.core.v1.Secret(
    "pulumi-access-token",
    metadata=k8s.meta.v1.ObjectMetaArgs(namespace=ns.metadata.name),
    string_data={"accessToken": eso_stack.require_output("pulumiAccessToken")},
    opts=opts,
)

# The workspace pod authenticates to the operator with this service account.
service_account = k8s.core.v1.ServiceAccount(
    "pulumi",
    metadata=k8s.meta.v1.ObjectMetaArgs(namespace=ns.metadata.name),
    opts=opts,
)

k8s.rbac.v1.ClusterRoleBinding(
    "simple-random-auth-delegator",
    role_ref=k8s.rbac.v1.RoleRefArgs(
        api_group="rbac.authorization.k8s.io",
        kind="ClusterRole",
        name="system:auth-delegator",
    ),
    subjects=[
        k8s.rbac.v1.SubjectArgs(
            kind="ServiceAccount",
            name=service_account.metadata.name,
            namespace=ns.metadata.name,
        )
    ],
    opts=opts,
)

git_repo = flux.GitRepository(
    "simple-random",
    metadata=k8s.meta.v1.ObjectMetaArgs(namespace=ns.metadata.name),
    spec=flux.GitRepositorySpecArgs(
        url="https://github.com/pierskarsenbarg/simple-random",
        interval="1m",
        ref=flux.GitRepositorySpecRefArgs(branch="main"),
    ),
    opts=opts,
)

stack = pko.Stack(
    "simple-random",
    metadata=k8s.meta.v1.ObjectMetaArgs(namespace=ns.metadata.name),
    spec=pko.StackSpecArgs(
        stack=f"{org}/simple-random/dev",
        service_account_name=service_account.metadata.name,
        flux_source=pko.StackSpecFluxSourceArgs(
            source_ref=pko.StackSpecFluxSourceSourceRefArgs(
                api_version="source.toolkit.fluxcd.io/v1",
                kind="GitRepository",
                name=git_repo.metadata.name,
            ),
        ),
        # The generated SDK types envRefs values as flat string maps, so set the token on the workspace pod instead.
        workspace_template=pko.StackSpecWorkspaceTemplateArgs(
            spec=pko.StackSpecWorkspaceTemplateSpecArgs(
                # The default full image fills the nodes' 16 GiB disks; YAML only needs the CLI.
                # pulumi-base has no nonroot variant, so drop to the baseline profile to run it as root.
                image="pulumi/pulumi-base:3.273.0",
                security_profile="baseline",
                env=[
                    pko.StackSpecWorkspaceTemplateSpecEnvArgs(
                        name="PULUMI_ACCESS_TOKEN",
                        value_from=pko.StackSpecWorkspaceTemplateSpecEnvValueFromArgs(
                            secret_key_ref=pko.StackSpecWorkspaceTemplateSpecEnvValueFromSecretKeyRefArgs(
                                name=token_secret.metadata.name,
                                key="accessToken",
                            ),
                        ),
                    )
                ],
            ),
        ),
        refresh=True,
        destroy_on_finalize=True,
        workspace_reclaim_policy="Retain",
    ),
    opts=opts,
)

pulumi.export("namespace", ns.metadata.name)
pulumi.export("stackName", stack.metadata.name)
