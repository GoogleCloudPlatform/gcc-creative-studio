# --- Custom VPC Network ---
resource "google_compute_network" "vpc" {
  name                    = "${var.resource_prefix}-${var.environment}-vpc"
  project                 = var.project_id
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

# --- Subnet for Cloud Run Direct VPC Egress ---
# Cloud Run requires a dedicated subnet to inject private traffic into the VPC.
resource "google_compute_subnetwork" "cloud_run_subnet" {
  name          = "${var.resource_prefix}-${var.environment}-run-subnet"
  project       = var.project_id
  network       = google_compute_network.vpc.id
  region        = var.region
  ip_cidr_range = var.cloud_run_cidr

  # Crucial enterprise guardrail: allows internal routing to Google APIs without public IPs
  private_ip_google_access = true
}

# --- Private Services Access (Cloud SQL Peering) ---
# Reserve a private IP block strictly for Google-managed services peering.
resource "google_compute_global_address" "private_service_access" {
  name          = "${var.resource_prefix}-${var.environment}-psa-range"
  project       = var.project_id
  network       = google_compute_network.vpc.id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 24
}

# Establish the private network peering connection with Google Services.
resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_access.name]
}

# --- Baseline Firewall Rules ---
# Custom VPCs have an implied deny-all ingress rule. We explicitly permit internal 
# traffic originating from our Cloud Run subnet to enable database reachability.
resource "google_compute_firewall" "allow_internal_egress" {
  name    = "${var.resource_prefix}-${var.environment}-allow-internal"
  project = var.project_id
  network = google_compute_network.vpc.id

  allow {
    protocol = "tcp"
  }

  allow {
    protocol = "udp"
  }

  source_ranges = [var.cloud_run_cidr]
  description   = "Allow Cloud Run internal subnet traffic to traverse the VPC"

  # Apply audit logging to internal cross-resource connections
  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}

