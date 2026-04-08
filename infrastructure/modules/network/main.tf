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

# VPC Network
resource "google_compute_network" "vpc" {
  name                    = var.network_name
  auto_create_subnetworks = false
  project                 = var.project_id
}

# Subnet for Serverless VPC Access Connector
resource "google_compute_subnetwork" "connector_subnet" {
  name          = "${var.network_name}-connector-sub"
  ip_cidr_range = var.subnet_cidr
  region        = var.region
  network       = google_compute_network.vpc.id
  project       = var.project_id
  
  # Enable Private Google Access as best practice
  private_ip_google_access = true
}

# Serverless VPC Access Connector for Cloud Run
resource "google_vpc_access_connector" "connector" {
  name    = "${var.network_name}-conn"
  region  = var.region
  project = var.project_id

  subnet {
    name = google_compute_subnetwork.connector_subnet.name
  }
  
  machine_type  = var.vpc_connector_machine_type
  min_instances = var.vpc_connector_min_instances
  max_instances = var.vpc_connector_max_instances
}

# Cloud SQL Private Services Access
resource "google_compute_global_address" "private_ip_alloc" {
  name          = "${var.network_name}-sqldb-alloc"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.peering_prefix_length
  network       = google_compute_network.vpc.id
  project       = var.project_id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_alloc.name]
}

# Optional Cloud NAT
resource "google_compute_router" "router" {
  count   = var.enable_nat ? 1 : 0
  name    = "${var.network_name}-router"
  region  = var.region
  network = google_compute_network.vpc.id
  project = var.project_id
}

resource "google_compute_router_nat" "nat" {
  count                              = var.enable_nat ? 1 : 0
  name                               = "${var.network_name}-nat"
  router                             = google_compute_router.router[0].name
  region                             = var.region
  project                            = var.project_id
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

# Basic Firewall Rules
resource "google_compute_firewall" "allow_internal" {
  name    = "${var.network_name}-allow-internal"
  network = google_compute_network.vpc.id
  project = var.project_id

  allow {
    protocol = "icmp"
  }

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }

  # Allow traffic from the VPC connector subnet and additional internal ranges
  source_ranges = concat([var.subnet_cidr], var.internal_source_ranges)
}
