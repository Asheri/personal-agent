terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.30"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "required" {
  for_each = toset([
    "secretmanager.googleapis.com",
    "sqladmin.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_sql_database_instance" "dev" {
  name             = var.instance_name
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_autoresize   = true

    ip_configuration {
      # No authorized networks are configured. IAM-authenticated proxy
      # connections are the only developer path to this public endpoint.
      ipv4_enabled = true
    }

    backup_configuration {
      enabled = false
    }
  }

  deletion_protection = var.deletion_protection
  depends_on          = [google_project_service.required]

  lifecycle {
    # The helper owns this single operational field for explicit cost control.
    ignore_changes = [settings[0].activation_policy]
  }
}

resource "random_password" "database" {
  length  = 24
  special = false
}

resource "google_sql_user" "sci_rag" {
  name     = var.database_user
  instance = google_sql_database_instance.dev.name
  password = random_password.database.result
}

resource "google_secret_manager_secret" "password" {
  secret_id = "${var.instance_name}-password"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "password" {
  secret      = google_secret_manager_secret.password.id
  secret_data = random_password.database.result
}

resource "google_project_iam_member" "developer_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.editor"
  member  = var.developer_principal

  condition {
    title       = "sci_rag_dev_instance_only"
    description = "Limit database creation, pause, resume, and proxy access to the dev instance."
    expression  = "resource.name.startsWith('projects/${var.project_id}/instances/${var.instance_name}') && resource.service == 'sqladmin.googleapis.com'"
  }
}

resource "google_secret_manager_secret_iam_member" "developer_password" {
  secret_id = google_secret_manager_secret.password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = var.developer_principal
}
