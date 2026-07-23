#!/bin/bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -e

# Retry loop helper function
retry_command() {
    local max_attempts=5
    local delay=15
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if "$@"; then
            return 0
        else
            echo "Command failed (attempt $attempt/$max_attempts). Retrying in $delay seconds..."
            sleep $delay
            attempt=$((attempt + 1))
        fi
    done

    echo "Command failed after $max_attempts attempts."
    return 1
}

# Migration Script: Public Cloud SQL to Private Cloud SQL
# This script uses Google Cloud Storage to perform an offline migration.

if [ -z "$SOURCE_INSTANCE" ] || [ -z "$TARGET_INSTANCE" ] || [ -z "$DATABASE_NAME" ] || [ -z "$BUCKET_NAME" ]; then
    echo "Usage: SOURCE_INSTANCE=<src> TARGET_INSTANCE=<tgt> DATABASE_NAME=<db> BUCKET_NAME=<bucket> $0"
    exit 1
fi

BUCKET_NAME="${BUCKET_NAME#gs://}"
EXPORT_FILE="migration_$(date +%s).sql.gz"

# Check if target database already contains data to prevent accidental overwrites
if [ "$FORCE" != "true" ]; then
    echo "Checking if target database $DATABASE_NAME already contains tables..."
    TABLE_COUNT=$(gcloud sql execute "$TARGET_INSTANCE" --database="$DATABASE_NAME" "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" --format="value(count)" 2>/dev/null || echo "0")
    if [ "$TABLE_COUNT" -gt 0 ]; then
        echo "ERROR: Target database '$DATABASE_NAME' on '$TARGET_INSTANCE' already contains $TABLE_COUNT table(s)."
        echo "Aborting migration to prevent accidental data loss. To force migration anyway, re-run with FORCE=true."
        exit 1
    fi
fi

echo "Starting migration from $SOURCE_INSTANCE to $TARGET_INSTANCE for database $DATABASE_NAME..."

# 1. Grant Source Instance Service Account access to write to GCS
SOURCE_SA=$(gcloud sql instances describe "$SOURCE_INSTANCE" --format="value(serviceAccountEmailAddress)")
echo "Granting write access to source instance ($SOURCE_SA)..."
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" \
    --member="serviceAccount:$SOURCE_SA" \
    --role="roles/storage.objectAdmin"

# 2. Export data from source instance
echo "Exporting data to gs://$BUCKET_NAME/$EXPORT_FILE..."
retry_command gcloud sql export sql "$SOURCE_INSTANCE" "gs://$BUCKET_NAME/$EXPORT_FILE" \
    --database="$DATABASE_NAME" \
    --quiet

# 3. Grant Target Instance Service Account access to read from GCS
TARGET_SA=$(gcloud sql instances describe "$TARGET_INSTANCE" --format="value(serviceAccountEmailAddress)")
echo "Granting read access to target instance ($TARGET_SA)..."
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" \
    --member="serviceAccount:$TARGET_SA" \
    --role="roles/storage.objectViewer"

# 4. Import data to target instance
echo "Importing data into $TARGET_INSTANCE..."
retry_command gcloud sql import sql "$TARGET_INSTANCE" "gs://$BUCKET_NAME/$EXPORT_FILE" \
    --database="$DATABASE_NAME" \
    --quiet

echo "Migration completed successfully!"
