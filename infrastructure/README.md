# Creative Studio Infrastructure

This directory contains the Terraform configuration and infrastructure-as-code definitions for deploying Creative Studio on Google Cloud Platform.

## Troubleshooting

### Manual Legacy Database Import
If your `bootstrap.sh` script crashed *after* exporting the legacy database but *before* importing it into the new database (e.g. during Terraform apply), the script loses track of the export file on subsequent runs. 

Your data is fully safe and backed up in your Terraform State Bucket! To manually restore it:

1. **Find your SQL dump:** Go to Google Cloud Storage and open your Terraform State bucket. You will see a file named `migration_backup.sql.gz`.
2. **Grant read permissions:** First, ensure the new Cloud SQL service account has read access to the bucket.
3. **Run the manual import command:**
   ```bash
   gcloud sql import sql YOUR_NEW_DB_INSTANCE_NAME \
     gs://YOUR_TF_BUCKET_NAME/migration_backup.sql.gz \
     --database="creative_studio" \
     --project="YOUR_PROJECT_ID"
   ```
