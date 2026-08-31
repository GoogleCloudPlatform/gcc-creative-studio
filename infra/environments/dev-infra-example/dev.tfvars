gcp_project_id = "rain-frontrunner-wkld-01"
gcp_region     = "africa-south1"  # POPIA residency: gcp.resourceLocations on teams/
environment    = "development"

# --- Service Names ---
backend_service_name  = "cstudio-backend-dev"
frontend_service_name = "cstudio-frontend-dev" # This is the Cloud Run service name
firebase_site_id      = "" # empty => defaults to gcp_project_id

# --- GitHub Repo Details ---
# Must match a Cloud Build GitHub connection created in the console first
# (Cloud Build > Repositories > Connect host). Terraform cannot create it.
github_conn_name   = "rain-poc-workload-con"
github_repo_owner  = "rainsouthafrica"
github_repo_name   = "poc-workload"
github_branch_name = "main"

# --- Custom Audiences ---
backend_custom_audiences  = ["YOUR_OAUTH_WEB_CLIENT_ID_HERE", "rain-frontrunner-wkld-01"]
frontend_custom_audiences = ["YOUR_OAUTH_WEB_CLIENT_ID_HERE", "rain-frontrunner-wkld-01"]

# --- Service-Specific Environment Variables ---
be_env_vars = {
  common = {
    LOG_LEVEL = "INFO"
  }
  development = {
    ENVIRONMENT  = "development"
    GOOGLE_TOKEN_AUDIENCE = "YOUR_OAUTH_WEB_CLIENT_ID_HERE"
    IDENTITY_PLATFORM_ALLOWED_ORGS = "" # If empty then any org is allowed
  }
  production = {
    ENVIRONMENT  = "production"
    GOOGLE_TOKEN_AUDIENCE = "YOUR_OAUTH_WEB_CLIENT_ID_HERE"
    IDENTITY_PLATFORM_ALLOWED_ORGS = "" # If empty then any org is allowed
  }
}

fe_build_substitutions = {
  _ANGULAR_BUILD_COMMAND = "build-dev"
}

frontend_secrets = [
  "FIREBASE_API_KEY",          # Your Firebase Web API Key
  "FIREBASE_AUTH_DOMAIN",      # Your Firebase Auth Domain (e.g., project-id.firebaseapp.com)
  "FIREBASE_PROJECT_ID",       # Your Firebase Project ID
  "FIREBASE_STORAGE_BUCKET",   # Your Firebase Storage Bucket (e.g., project-id.appspot.com)
  "FIREBASE_MESSAGING_SENDER_ID", # Your Firebase Cloud Messaging Sender ID
  "FIREBASE_APP_ID",           # Your Firebase Web App ID
  "FIREBASE_MEASUREMENT_ID",   # Your Google Analytics Measurement ID
  "GOOGLE_CLIENT_ID",          # Your Google OAuth 2.0 Client ID for web
]

backend_secrets = [
  "GOOGLE_TOKEN_AUDIENCE",
]

backend_runtime_secrets = {
  "GOOGLE_TOKEN_AUDIENCE" = "GOOGLE_TOKEN_AUDIENCE"
}

apis_to_enable = [
  "serviceusage.googleapis.com",     # Required to enable other APIs
  "iam.googleapis.com",              # Required for IAM management
  "cloudbuild.googleapis.com",       # Required for Cloud Build
  "artifactregistry.googleapis.com", # Required for Artifact Registry
  "run.googleapis.com",              # Required for Cloud Run
  "cloudresourcemanager.googleapis.com",
  "compute.googleapis.com",
  "cloudfunctions.googleapis.com",
  "iamcredentials.googleapis.com",
  "aiplatform.googleapis.com",
  "firestore.googleapis.com",
  "texttospeech.googleapis.com",
  "workflows.googleapis.com",
]
