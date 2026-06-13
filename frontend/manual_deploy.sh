#!/bin/bash
set -e

export FIREBASE_API_KEY=$(gcloud secrets versions access latest --secret="FIREBASE_API_KEY" --project="YOUR_GCP_PROJECT_ID")
export FIREBASE_AUTH_DOMAIN=$(gcloud secrets versions access latest --secret="FIREBASE_AUTH_DOMAIN" --project="YOUR_GCP_PROJECT_ID")
export FIREBASE_PROJECT_ID=$(gcloud secrets versions access latest --secret="FIREBASE_PROJECT_ID" --project="YOUR_GCP_PROJECT_ID")
export FIREBASE_STORAGE_BUCKET=$(gcloud secrets versions access latest --secret="FIREBASE_STORAGE_BUCKET" --project="YOUR_GCP_PROJECT_ID")
export FIREBASE_SENDER_ID=$(gcloud secrets versions access latest --secret="FIREBASE_SENDER_ID" --project="YOUR_GCP_PROJECT_ID")
export FIREBASE_APP_ID=$(gcloud secrets versions access latest --secret="FIREBASE_APP_ID" --project="YOUR_GCP_PROJECT_ID")
export FIREBASE_MEASUREMENT_ID=$(gcloud secrets versions access latest --secret="FIREBASE_MEASUREMENT_ID" --project="YOUR_GCP_PROJECT_ID")
export GOOGLE_CLIENT_ID=$(gcloud secrets versions access latest --secret="GOOGLE_CLIENT_ID" --project="YOUR_GCP_PROJECT_ID")
export ENTRA_CLIENT_ID=$(gcloud secrets versions access latest --secret="ENTRA_CLIENT_ID" --project="YOUR_GCP_PROJECT_ID")
export ENTRA_TENANT_ID=$(gcloud secrets versions access latest --secret="ENTRA_TENANT_ID" --project="YOUR_GCP_PROJECT_ID")
export BACKEND_URL="https://YOUR_FIREBASE_SITE_ID.web.app/api"

# Make a backup of environment.prod.ts so we don't mess up the repo permanently
cp src/environments/environment.prod.ts src/environments/environment.prod.ts.bak

sed -i "s|FIREBASE_API_KEY_PLACEHOLDER|$FIREBASE_API_KEY|g" src/environments/environment.prod.ts
sed -i "s|FIREBASE_AUTH_DOMAIN_PLACEHOLDER|$FIREBASE_AUTH_DOMAIN|g" src/environments/environment.prod.ts
sed -i "s|FIREBASE_PROJECT_ID_PLACEHOLDER|$FIREBASE_PROJECT_ID|g" src/environments/environment.prod.ts
sed -i "s|FIREBASE_STORAGE_BUCKET_PLACEHOLDER|$FIREBASE_STORAGE_BUCKET|g" src/environments/environment.prod.ts
sed -i "s|FIREBASE_SENDER_ID_PLACEHOLDER|$FIREBASE_SENDER_ID|g" src/environments/environment.prod.ts
sed -i "s|FIREBASE_APP_ID_PLACEHOLDER|$FIREBASE_APP_ID|g" src/environments/environment.prod.ts
sed -i "s|FIREBASE_MEASUREMENT_ID_PLACEHOLDER|$FIREBASE_MEASUREMENT_ID|g" src/environments/environment.prod.ts
sed -i "s|BACKEND_URL_PLACEHOLDER|$BACKEND_URL|g" src/environments/environment.prod.ts
sed -i "s|GOOGLE_CLIENT_ID_PLACEHOLDER|$GOOGLE_CLIENT_ID|g" src/environments/environment.prod.ts
sed -i "s|ENTRA_CLIENT_ID_PLACEHOLDER|$ENTRA_CLIENT_ID|g" src/environments/environment.prod.ts
sed -i "s|ENTRA_TENANT_ID_PLACEHOLDER|$ENTRA_TENANT_ID|g" src/environments/environment.prod.ts

npm install
rm -rf .angular/cache
npm run build -- --configuration=production
cp firebase.json firebase.json.bak
sed -i "s|SITE_ID_PLACEHOLDER|YOUR_FIREBASE_SITE_ID|g" firebase.json
sed -i "s|BACKEND_SERVICE_ID_PLACEHOLDER|cstudio-be|g" firebase.json

npx firebase deploy --only hosting --project YOUR_GCP_PROJECT_ID

mv firebase.json.bak firebase.json

# Restore the backup
mv src/environments/environment.prod.ts.bak src/environments/environment.prod.ts
