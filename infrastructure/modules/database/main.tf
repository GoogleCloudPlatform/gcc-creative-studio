# This generates the password in memory during the Terraform run.
# It is immediately discarded after the run completes.
ephemeral "random_password" "db_pass" {
  length  = 24
  special = true
}

resource "random_id" "db_name_suffix" {
  byte_length = 4
}

# --- The Secret Manager Container ---
resource "google_secret_manager_secret" "db_secret" {
  secret_id = "${var.resource_prefix}-${var.environment}-db-password"
  project   = var.project_id

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret_version" "db_secret_version" {
  secret = google_secret_manager_secret.db_secret.id

  # Using a write-only argument prevents the password 
  # from being captured in the terraform.tfstate file.
  secret_data_wo = ephemeral.random_password.db_pass.result
}

resource "google_sql_database_instance" "default" {
  name             = "${var.resource_prefix}-${var.environment}-db-${random_id.db_name_suffix.hex}"
  database_version = var.database_version
  region           = var.region
  project          = var.project_id

  # Ensure networking PSA is established before instance creation
  depends_on = [var.psa_connection_dependency]

  settings {
    tier              = var.db_tier # "db-perf-optimized-N-2"
    availability_type = var.db_availability_type

    # Enable IAM Authentication for better security
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    # --- Storage Flexibility ---
    disk_type             = "PD_SSD"
    disk_size             = var.initial_disk_size
    disk_autoresize       = true              # Allows growth as needed
    disk_autoresize_limit = var.max_disk_size # Prevents unlimited expansion/billing surprises

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      location                       = var.region
    }

    # --- Network Isolation ---
    ip_configuration {
      ipv4_enabled                                  = false # Force Private IP only
      private_network                               = var.vpc_id
      enable_private_path_for_google_cloud_services = true
    }

    # --- Enterprise Metadata ---
    # Merges common labels (from root) with module-specific labels
    user_labels = merge(var.labels, {
      component  = "database"
      managed_by = "terraform"
      region     = var.region
    })

  }

  deletion_protection = var.deletion_protection

  lifecycle {
    # Prevent accidental destruction of production data
    prevent_destroy = false
    # Ignore disk_size changes if auto-resize has grown the disk beyond the TF value
    ignore_changes = [settings[0].disk_size]
  }
}

resource "google_sql_database" "default" {
  name     = var.db_name
  instance = google_sql_database_instance.default.name
  project  = var.project_id
}

resource "google_sql_user" "app_user" {
  name     = var.db_user
  instance = google_sql_database_instance.default.name
  project  = var.project_id

  # We read the ephemeral value while creating the DB user,
  # keeping the DB state clean of plaintext passwords.
  password_wo         = ephemeral.random_password.db_pass.result
  password_wo_version = var.db_password_version
}
