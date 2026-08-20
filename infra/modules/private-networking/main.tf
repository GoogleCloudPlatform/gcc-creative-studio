resource "google_compute_network" "this" {
  count = var.network_self_link == "" ? 1 : 0

  name                    = var.network_name
  project                 = var.network_project_id
  auto_create_subnetworks = false
}

locals {
  network_self_link = var.network_self_link != "" ? var.network_self_link : google_compute_network.this[0].self_link
}

resource "google_compute_global_address" "private_services" {
  name          = var.private_services_range_name
  project       = var.network_project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = var.private_services_range_address
  prefix_length = var.private_services_range_prefix_length
  network       = local.network_self_link
}

resource "google_service_networking_connection" "private_services" {
  project                 = var.network_project_id
  network                 = local.network_self_link
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

resource "google_vpc_access_connector" "backend" {
  name          = var.vpc_connector_name
  project       = var.project_id
  region        = var.region
  network       = local.network_self_link
  ip_cidr_range = var.vpc_connector_cidr

  min_instances = 2
  max_instances = 3

  depends_on = [google_service_networking_connection.private_services]
}