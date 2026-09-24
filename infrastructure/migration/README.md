# Database Migration to Private Cloud SQL

This directory contains the script required to migrate data from the existing public Cloud SQL PostgreSQL instance to the new private instance.

## Strategy: Export / Import via Cloud Storage (Requires Downtime)
Because the target database is on a private network, we use a Google Cloud Storage bucket as a secure intermediary to transfer the database dump.

## Transition Period Instructions

1. **Preparation:**
   - Ensure the new private database infrastructure has been deployed via Terraform.
   - Create a temporary Google Cloud Storage bucket for the migration (e.g., `gs://my-db-migration-bucket`).

2. **Start Maintenance Mode (Downtime Begins):**
   - Stop all application traffic to the existing public database. Scale down your backend workloads (e.g., Cloud Run or GKE deployments to 0 replicas) to ensure no new writes occur.

3. **Execute the Migration Script:**
   - Run the migration script with the required environment variables:
     ```bash
     SOURCE_INSTANCE="public-db-instance-name" \
     TARGET_INSTANCE="private-db-instance-name" \
     DATABASE_NAME="creative_studio_db" \
     BUCKET_NAME="my-db-migration-bucket" \
     ./migrate_to_private_db.sh
     ```

4. **Verify and Reconfigure:**
   - Verify that the tables and data exist in the new private instance.
   - Update the backend's environment variables (e.g., `DATABASE_URL`) to point to the new private instance connection name or IP.

5. **End Maintenance Mode (Downtime Ends):**
   - Scale back up the backend workloads.
   - Verify that the application is fully functional and connecting correctly to the private database.
