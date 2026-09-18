# --- Enable the required Google Cloud APIs ---
resource "google_project_service" "apis" {
  # Use a for_each loop to enable each API from the variable list
  for_each = toset(var.apis_to_enable)

  project = var.project_id
  service = each.key

  # This prevents Terraform from disabling APIs when you run `terraform destroy`
  disable_on_destroy = false
}
