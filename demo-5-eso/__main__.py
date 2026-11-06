import pulumi
import pulumi_kubernetes as k8s
import pulumi_external_secrets as external_secrets

eso = external_secrets.external_secrets.v1

eso_version = "2.14.0"

config = pulumi.Config()

esc_org = "pierskarsenbarg"
esc_project = "workshop-cluster-setup"
esc_environment = "eso-demo"

provider = k8s.Provider(
    "provider",
    kubeconfig=config.require_secret("kubeconfig"),
)

opts = pulumi.ResourceOptions(provider=provider)

# Same manifest that generates the typed SDK, so the SDK and cluster stay in step.
crds = k8s.yaml.v2.ConfigFile(
    "external-secrets-crds",
    file=f"crd/external-secrets-v{eso_version}.yaml",
    opts=opts,
)

eso_ns = k8s.core.v1.Namespace(
    "external-secrets",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="external-secrets"),
    opts=opts,
)

chart = k8s.helm.v4.Chart(
    "external-secrets",
    k8s.helm.v4.ChartArgs(
        chart="external-secrets",
        version=eso_version,
        repository_opts=k8s.helm.v4.RepositoryOptsArgs(repo="https://charts.external-secrets.io"),
        namespace=eso_ns.metadata.name,
        values={"installCRDs": False},
    ),
    opts=opts.merge(pulumi.ResourceOptions(depends_on=[crds])),
)

token_secret = k8s.core.v1.Secret(
    "pulumi-access-token",
    metadata=k8s.meta.v1.ObjectMetaArgs(namespace=eso_ns.metadata.name),
    string_data={"PULUMI_ACCESS_TOKEN": config.require_secret("pulumiAccessToken")},
    opts=opts,
)

# The ESO webhook validates stores, so wait for the chart to be ready first.
store_opts = opts.merge(pulumi.ResourceOptions(depends_on=[chart]))

cluster_store = eso.ClusterSecretStore(
    "pulumi-esc",
    spec=eso.ClusterSecretStoreSpecArgs(
        # Generated SDK sends `pulumi_` as the wire name, so use the CRD's real key here.
        provider={
            "pulumi": eso.ClusterSecretStoreSpecProviderPulumiArgs(
                organization=esc_org,
                project=esc_project,
                environment=esc_environment,
                auth=eso.ClusterSecretStoreSpecProviderPulumiAuthArgs(
                    access_token=eso.ClusterSecretStoreSpecProviderPulumiAuthAccessTokenArgs(
                        secret_ref=eso.ClusterSecretStoreSpecProviderPulumiAuthAccessTokenSecretRefArgs(
                            name=token_secret.metadata.name,
                            namespace=token_secret.metadata.namespace,
                            key="PULUMI_ACCESS_TOKEN",
                        ),
                    ),
                ),
            ),
        },
    ),
    opts=store_opts,
)

app_ns = k8s.core.v1.Namespace(
    "eso-demo",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="eso-demo"),
    opts=opts,
)

external_secret = eso.ExternalSecret(
    "demo-password",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        namespace=app_ns.metadata.name,
        annotations={"pulumi.com/waitFor": "condition=Ready"},
    ),
    spec=eso.ExternalSecretSpecArgs(
        refresh_interval="30s",
        secret_store_ref=eso.ExternalSecretSpecSecretStoreRefArgs(
            kind="ClusterSecretStore",
            name=cluster_store.metadata.name,
        ),
        target=eso.ExternalSecretSpecTargetArgs(name="demo-password"),
        data=[
            eso.ExternalSecretSpecDataArgs(
                secret_key="password",
                remote_ref=eso.ExternalSecretSpecDataRemoteRefArgs(key="demo.password"),
            )
        ],
    ),
    opts=opts,
)

pulumi.export("namespace", app_ns.metadata.name)
pulumi.export("syncedSecret", "demo-password")
pulumi.export("pulumiAccessToken", config.require_secret("pulumiAccessToken"))
