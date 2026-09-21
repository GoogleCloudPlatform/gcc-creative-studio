# Creative Studio Infrastructure

This directory contains the Terraform configuration and infrastructure-as-code definitions for deploying Creative Studio on Google Cloud Platform.

## Database Migrations & Safe Upgrades

When making major changes to the database infrastructure (e.g., migrating from an old Public IP setup to a Private IP setup), Terraform must update network settings. This causes a brief window where the active Cloud Run container can no longer connect to the database, resulting in a startup crash that creates a deadlock for Terraform.

To safely prevent this, the `bootstrap.sh` script employs a smart **Migration Flow**:

1. **Step 8 — Backup.** It safely exports your database to the Terraform state bucket as `migration_backup.sql.gz`.
2. **Step 9 — Sever the link.** It deploys a temporary, database-agnostic "dummy" container (`us-docker.pkg.dev/cloudrun/container/hello`) to the Cloud Run backend, completely removing its database dependency.
3. **Step 10 — Apply.** It runs `terraform apply` cleanly without triggering Cloud Run deadlocks.
4. **Step 10 (import) — Restore.** It wipes and recreates the target database, then imports the backup into the newly provisioned instance.
5. **Step 13 — Redeploy.** It triggers Cloud Build to re-deploy your real application code safely.

### How to trigger a Safe Migration

The script employs a hybrid detection mechanism to protect you automatically while keeping the "happy path" silent:

- **Automatic Trigger (V1 Legacy DBs):** If the script detects you are upgrading from an ancient V1 Public IP database (exactly `creative-studio-db`), it automatically pauses and asks if you want to run the migration flow. Answering `n` skips it entirely.
- **Automatic Trigger (Orphaned Backups):** If the script detects a `migration_backup.sql.gz` file sitting in your **Terraform state bucket**, it will ask if you want to restore it using the migration flow. Only that bucket is scanned, because it is the bucket responsible for infrastructure artifacts.
- **Manual Trigger (`--migrate-db`):** If you are intentionally making a dangerous infrastructure change (e.g. changing database regions or network paths manually), you can manually force this safety flow by running:
  ```bash
  ./bootstrap.sh --migrate-db
  ```
  Unlike the automatic triggers, this one intercepts **any** database it finds — public *or* private.

If you do NOT pass the flag, and the script doesn't detect a legacy database, it assumes a standard "happy path" deployment and relies entirely on Cloud SQL's automated **Point-In-Time Recovery (PITR)**. Steps 8, 9 and the import are all no-ops in that case — zero prompts, zero downtime.

> [!CAUTION]
> Immediately before restoring, the script **drops and recreates** the `creative_studio` database on the target instance. This guarantees a blank schema so the import cannot fail with `relation "..." already exists`. Any data written to the new instance before the restore is discarded in favour of the backup.

> [!NOTE]
> The dummy container is deployed to **both** the legacy backend service name (`cstudio-be`) and the current one (`cs-[ENV_NAME]-backend`). Each is checked for existence first, so nothing is created that did not already exist.

> [!TIP]
> The backup file is intentionally left in the bucket after a successful import as a permanent safeguard. Delete `migration_backup.sql.gz`, or pass `--skip-db-import`, to stop being prompted about it on future runs.

## Troubleshooting

### Manual Database Import
If a migration was interrupted, your data is always safe in your project's Terraform state bucket (`gs://[PROJECT_ID]-terraform-state/migration_backup.sql.gz`). You can manually restore it via the GCP Console or CLI:
```bash
gcloud sql import sql YOUR_NEW_DB_INSTANCE_NAME \
  gs://YOUR_TF_BUCKET_NAME/migration_backup.sql.gz \
  --database="creative_studio" \
  --project="YOUR_PROJECT_ID"
```
