# Creative Studio Infrastructure

This directory contains the Terraform configuration and infrastructure-as-code definitions for deploying Creative Studio on Google Cloud Platform.

## Database Migrations & Safe Upgrades

When making major changes to the database infrastructure (e.g., migrating from an old Public IP setup to a Private IP setup), Terraform must update network settings. This causes a brief window where the active Cloud Run container can no longer connect to the database, resulting in a startup crash that creates a deadlock for Terraform.

To safely prevent this, the `bootstrap.sh` script employs a smart **Migration Flow**:
1. It safely backs up your database to Google Cloud Storage.
2. It explicitly deploys a temporary, database-agnostic "dummy" container (`us-docker.pkg.dev/cloudrun/container/hello`) to the Cloud Run service, completely severing its database dependency.
3. It runs `terraform apply` cleanly without triggering Cloud Run deadlocks.
4. It imports the backup data into the newly provisioned infrastructure.
5. It triggers Cloud Build to re-deploy your real application code safely.

### How to trigger a Safe Migration

The script employs a hybrid detection mechanism to protect you automatically while keeping the "happy path" silent:

- **Automatic Trigger (V1 Legacy DBs):** If the script detects you are upgrading from an ancient V1 Public IP database (`creative-studio-db`), it automatically pauses and asks if you want to run the migration flow.
- **Automatic Trigger (Orphaned Backups):** If the script detects a `migration_backup.sql.gz` file sitting in your asset bucket, it will ask if you want to restore it using the migration flow.
- **Manual Trigger (`--migrate-db`):** If you are intentionally making a dangerous infrastructure change (e.g. changing database regions or network paths manually), you can manually force this safety flow by running:
  ```bash
  ./bootstrap.sh --migrate-db
  ```

If you do NOT pass the flag, and the script doesn't detect a legacy database, it assumes a standard "happy path" deployment and relies entirely on Cloud SQL's automated **Point-In-Time Recovery (PITR)**.

## Troubleshooting

### Manual Database Import
If a migration was interrupted, your data is always safe in your project's Terraform state bucket (`gs://[PROJECT_ID]-terraform-state/migration_backup.sql.gz`). You can manually restore it via the GCP Console or CLI:
```bash
gcloud sql import sql YOUR_NEW_DB_INSTANCE_NAME \
  gs://YOUR_TF_BUCKET_NAME/migration_backup.sql.gz \
  --database="creative_studio" \
  --project="YOUR_PROJECT_ID"
```
