variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "environment" {
  type    = string
  default = "development"
}

variable "apis_to_enable" {
  type = list(string)
  default = [
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
    "drive.googleapis.com",
    "servicenetworking.googleapis.com", # Required for Private VPC Peering (Cloud SQL)
    "sqladmin.googleapis.com",          # Required for Cloud SQL instance management
    "secretmanager.googleapis.com",     # Required for application secret management
    "vpcaccess.googleapis.com"          # Required for Serverless Direct VPC routing
  ]
}

variable "custom_domain" {
  type        = string
  description = "Optional custom domain name to link to Firebase Hosting (e.g., 'app.creativestudio.com'). Leave blank to skip."
  default     = ""
}

variable "application_secrets" {
  type        = set(string)
  description = "The list of application secret identifiers required by the backend application layer."
  default     = ["database_url", "agent_engine_resource_name", "agent_engine_user_auth_token_key"]
}

variable "frontend_secrets" {
  type        = set(string)
  description = "The list of application secret identifiers required by the frontend application layer."
  default     = [
    "FIREBASE_API_KEY",
    "FIREBASE_AUTH_DOMAIN",
    "FIREBASE_PROJECT_ID",
    "FIREBASE_STORAGE_BUCKET",
    "FIREBASE_MESSAGING_SENDER_ID",
    "FIREBASE_APP_ID",
    "FIREBASE_MEASUREMENT_ID",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_TOKEN_AUDIENCE"
  ]
}

variable "resource_prefix" {
  type        = string
  description = "Standard naming prefix assigned to the deployment."
}

variable "cloud_run_cidr" {
  type        = string
  description = "Dedicated CIDR range for Cloud Run Direct VPC egress."
  default     = "10.0.0.0/26"
}

variable "backend_image_name" {
  type        = string
  description = "The name of the backend container image."
  default     = "backend"
}

variable "backend_image_tag" {
  type        = string
  description = "The tag of the backend container image."
  default     = "latest"
}



variable "firebase_site_id" {
  type        = string
  description = "The Firebase Hosting Site ID. If empty, defaults to the project ID."
  default     = ""
}

variable "labels" {
  type        = map(string)
  description = "Standard resource labels to apply across resources."
  default     = {}
}

variable "app_version" {
  type = string
  description = "version of the creative studio app we're deploying"
  default = "latest"
}

variable "agent_engine_resource_name" {
  type        = string
  description = "Resource name of the Agent Engine"
  default     = ""
}

variable "agent_location" {
  type        = string
  description = "Location for the Agent Engine"
  default     = ""
}

variable "agent_engine_user_auth_token_key" {
  type        = string
  description = "Auth token key for Agent Engine"
  default     = ""
}
