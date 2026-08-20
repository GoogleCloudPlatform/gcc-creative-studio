# Private Cloud SQL Deployment

## Purpose

This runbook deploys the internal Creative Studio trial to
`iconic-ds-creative-studio-dev` in `us-central1`. It replaces the upstream
public Cloud SQL address with private IP because the inherited organisation
policy `constraints/sql.restrictPublicIp` rejects public database addresses.

The deployment creates a Cloud SQL private IP, a VPC, a Private Services
Access allocation and peering, and a Serverless VPC Access connector. The
backend Cloud Run revision uses `PRIVATE_RANGES_ONLY` egress through that
connector. Its Cloud SQL Python Connector is configured with
`CLOUD_SQL_IP_TYPE=PRIVATE`. The frontend never receives VPC access.

## Prerequisites

- Use only project `iconic-ds-creative-studio-dev` and region `us-central1`.
- Use the organisation fork `https://github.com/theiconic/gcc-creative-studio`.
- Create the Cloud Build connection `gh-creative-studio-deploy-con` in
  `us-central1` and grant its GitHub App access to `theiconic/gcc-creative-studio`.
- Enable or allow Terraform to enable `compute.googleapis.com`,
  `servicenetworking.googleapis.com`, `vpcaccess.googleapis.com`,
  `sqladmin.googleapis.com`, `run.googleapis.com`, and the APIs listed in
  `dev.tfvars`.
- The Terraform identity needs Cloud SQL, Cloud Run, Cloud Build, Secret
  Manager, Service Usage, Service Networking, Compute Network Admin, and
  Serverless VPC Access administration permissions in the owning projects.
- The backend runtime service account needs `roles/cloudsql.client`; Terraform
  creates this binding.

### Shared VPC

The default configuration creates a dedicated VPC in the deployment project.
For an organisation-approved Shared VPC, set `network_project_id` and the full
`network_self_link` in the generated, uncommitted environment tfvars file.
Choose an unused Private Services Access range and unused connector `/28` with
the network owner. The Terraform identity and relevant Google service agents
must have the host-project permissions to create the private-services range,
peering, and connector attachment. Do not apply until the network owner has
confirmed those values and permissions.

If the selected Shared VPC already has a Service Networking connection for
`servicenetworking.googleapis.com`, import it into Terraform state before the
apply rather than creating a duplicate connection. Do not commit that state.

## Bootstrap Or Resume

1. Push the reviewed feature branch to the organisation fork before using
   Cloud Shell. The bootstrap script must come from the same branch as the
   Terraform change:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/theiconic/gcc-creative-studio/feature/KN-DATAX-15064-deploy-creative-studio/bootstrap.sh | bash
   ```

2. Enter `https://github.com/theiconic/gcc-creative-studio.git` when prompted
   for the fork URL. Enter
   `feature/KN-DATAX-15064-deploy-creative-studio` when prompted for the Git
   branch. Enter `gh-creative-studio-deploy-con` for the Cloud Build connection.
3. Use `iconic-ds-creative-studio-dev`; keep `us-central1` unchanged.
4. In the generated `infra/environments/dev-infra/dev-infra.tfvars`, set the
   approved Shared VPC values if applicable. Never commit this directory,
   `.bootstrap_state`, Terraform state, or secrets.
5. Run `terraform init -reconfigure`, `terraform fmt -check -recursive`, and
   `terraform validate` in that environment. Review `terraform plan` before
   answering yes to bootstrap's apply prompt.

When resuming a prior bootstrap run, first confirm the existing checkout uses
the feature branch. The bootstrap script updates a clean existing checkout to
the selected branch. For an older checkout created before this behavior was
available, run the following from its parent directory before resuming:

```bash
cd gcc-creative-studio
git status --short
git fetch origin feature/KN-DATAX-15064-deploy-creative-studio
git switch feature/KN-DATAX-15064-deploy-creative-studio
git pull --ff-only origin feature/KN-DATAX-15064-deploy-creative-studio
gcloud services enable servicenetworking.googleapis.com vpcaccess.googleapis.com \
  --project=iconic-ds-creative-studio-dev
```

Do not discard or overwrite `infra/environments/dev-infra/`; it contains the
uncommitted generated Terraform configuration and resume state. Verify the
module source after the branch update before running another plan:

```bash
grep -A3 'ip_configuration' infra/modules/postgresql/main.tf
```

It must show `ipv4_enabled = false` and `private_network = var.private_network`.

The Cloud Build repository resource must reference owner `theiconic`, repository
`gcc-creative-studio`, and the healthy `us-central1` connection. If Terraform
reports that a manually linked repository already exists, import that resource
into the generated environment state before retrying; do not create another
connection or switch to a personal fork.

## Validation

Before applying, a reviewed plan must show:

- `google_sql_database_instance` with `ipv4_enabled = false` and a
  `private_network`.
- a `google_compute_global_address` for `VPC_PEERING` and a
  `google_service_networking_connection`.
- a `google_vpc_access_connector` in `us-central1`.
- backend Cloud Run `vpc_access` with `PRIVATE_RANGES_ONLY`.
- no public Cloud SQL address or `IPTypes.PUBLIC` deployment setting.

After an approved apply, run:

```bash
gcloud sql instances describe INSTANCE_NAME \
  --project=iconic-ds-creative-studio-dev \
  --format='yaml(ipAddresses,region,state)'

gcloud run services describe cstudio-be \
  --region=us-central1 \
  --project=iconic-ds-creative-studio-dev \
  --format='yaml(spec.template.spec.containers,spec.template.metadata.annotations)'

gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="cstudio-be"' \
  --project=iconic-ds-creative-studio-dev \
  --limit=100
```

Confirm the SQL instance has only a `PRIVATE` address, the backend revision is
ready, and startup/request logs contain no database connection errors. Then use
the Firebase Hosting URL from `terraform output frontend_service_url`, sign in
as a member of `tech.data.datascience@theiconic.com.au`, and perform a workflow
that reads and writes application data. Expected endpoints are the Firebase
Hosting URL and the backend Cloud Run URL from `terraform output`; the database
has no public endpoint.

## Limits And Cost

- A Serverless VPC Access connector incurs ongoing hourly and data-processing
  cost while it exists. Cloud SQL, Cloud Run minimum instances, storage,
  Artifact Registry, Cloud Build, Firebase, and generated media storage also
  incur trial costs.
- `PRIVATE_RANGES_ONLY` does not provide general Internet egress through the
  VPC. If the backend later requires controlled VPC Internet egress, add Cloud
  NAT and review the architecture rather than changing egress ad hoc.
- This configuration is for the internal time-boxed trial only. It does not
  add production HA, backup, monitoring, retention, or long-term support.

## Teardown

1. Preserve any data or logs required by the trial owner, then disable Cloud
   Build triggers to prevent a rebuild during teardown.
2. From the generated environment directory, run and review `terraform plan
   -destroy`, then run `terraform destroy` only after approval.
3. Verify Cloud Run services, Cloud SQL, the connector, Private Services
   Access peering/allocation, buckets, Cloud Build triggers/repositories,
   secrets, Firebase resources, and generated service accounts are gone or
   intentionally retained.
4. Remove manually created Firebase apps, OAuth clients, the Cloud Build
   connection, and the Terraform state bucket only when no other workload uses
   them. Deleting the state bucket is irreversible and must happen last.
5. For Shared VPC, have the host-project network owner confirm that the private
   services allocation and peering are safe to remove; they may be shared with
   other workloads. Remove only resources created specifically for this trial.