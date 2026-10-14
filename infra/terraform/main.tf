# Minimal, honest Google Cloud deployment for a sci-rag instance:
# Cloud SQL (Postgres + pgvector), a Cloud Run service for the API/MCP,
# a Cloud Run job for migrations and ingestion, and a corpus bucket.
#
# Costs money while it exists (the database is the steady cost; pick the
# smallest tier that fits). Follow the reviewed update and destroy procedure
# in docs/deploy-gcp.md when you tear it down.

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 7.0"
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

# --- Database ---------------------------------------------------------------

resource "google_sql_database_instance" "db" {
  name             = "${var.name}-db"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    # Pinned, not inherited. Cloud SQL's default edition for new instances
    # moved to ENTERPRISE_PLUS, which rejects the shared-core tiers this
    # module deliberately picks, so `terraform apply` failed on exactly the
    # empty project the deploy guide is written for:
    #   Invalid Tier (db-g1-small) for (ENTERPRISE_PLUS) Edition.
    # ENTERPRISE is also the cheaper of the two, so inheriting the default
    # would have quietly raised the bill for a reader following a dev guide.
    # The dev-database module already learned this; this is the same fix.
    edition = "ENTERPRISE"
    tier    = var.db_tier
    ip_configuration {
      ipv4_enabled = true # access is via the Cloud SQL connector, not open TCP
    }
    backup_configuration {
      enabled = true
    }
  }

  deletion_protection = var.deletion_protection
}

# ABANDON, not DELETE, and this is the fix for issue #284 rather than a
# loosening of it.
#
# A `terraform destroy` that had served traffic failed here:
#   Error 400: failed to delete database sci_rag.
#   Detail: pq: database "sci_rag" is being accessed by other users.
# Deleting a Cloud Run service returns before its instances stop dialling
# Postgres, so the DROP DATABASE that followed raced them and lost. Terraform
# had already removed the service, job, bucket, secrets, and service account,
# leaving the operator holding a running instance the error never named.
#
# A destroy-time wait was tried first and is not sufficient: any fixed window
# is a guess, and a service stuck in a startup-probe retry loop keeps opening
# new sessions for as long as it exists. A 90 second window survived a healthy
# deployment and still lost to a crash-looping one.
#
# Deleting the instance deletes the databases and roles inside it, so during a
# full destroy the separate DROP is redundant work whose only contribution is
# a failure mode. ABANDON drops these from Terraform's state and lets the
# instance deletion, which is still Terraform's, remove the data. Removing
# only this block from a configuration now leaves the database in place rather
# than dropping it, which for a database is the safer default.
resource "google_sql_database" "sci_rag" {
  name     = "sci_rag"
  instance = google_sql_database_instance.db.name

  deletion_policy = "ABANDON"

  depends_on = [google_sql_user.sci_rag]
}


resource "random_password" "db" {
  length  = 24
  special = false
}

resource "google_sql_user" "sci_rag" {
  name     = "sci_rag"
  instance = google_sql_database_instance.db.name
  password = random_password.db.result

  # Same reasoning as the database above: dropping a role that still owns
  # migrated objects, while sessions may still hold them, is the other half of
  # the same race. The instance deletion removes it.
  deletion_policy = "ABANDON"
}

# The async driver reaches Cloud SQL over the mounted unix socket.
locals {
  database_url = "postgresql+asyncpg://${google_sql_user.sci_rag.name}:${random_password.db.result}@/${google_sql_database.sci_rag.name}?host=/cloudsql/${google_sql_database_instance.db.connection_name}"
}

# --- Secrets ----------------------------------------------------------------

resource "google_secret_manager_secret" "database_url" {
  secret_id = "${var.name}-database-url"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = local.database_url
}

resource "google_secret_manager_secret" "api_keys" {
  secret_id = "${var.name}-api-keys"
  replication {
    auto {}
  }
}

# A generated first key, not an empty object. Seeding "{}" created every
# resource and then failed the startup probe, because the server refuses an
# empty allowlist rather than serving open:
#   RuntimeError: SCI_RAG_API_KEYS must be a non-empty JSON object
# That refusal is correct, so the seed is what changes. Generating one key
# the way the database password is generated means the documented deploy
# comes up secured by default, which is the posture docs/deploy-gcp.md
# already advertises. `ignore_changes` still lets an operator replace this
# with their own keys without Terraform reverting them.
resource "random_password" "api_key" {
  length  = 32
  special = false
}

resource "google_secret_manager_secret_version" "api_keys_seed" {
  secret = google_secret_manager_secret.api_keys.id
  secret_data = jsonencode({
    (random_password.api_key.result) = {
      scopes = ["retrieval:query", "retrieval:answer", "corpus:read"]
    }
  })
  lifecycle {
    ignore_changes = [secret_data]
  }
}

# --- Service account (least privilege) --------------------------------------

resource "google_service_account" "runtime" {
  account_id   = "${var.name}-runtime"
  display_name = "sci-rag runtime"
}

resource "google_project_iam_member" "cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "db_url_access" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "api_keys_access" {
  secret_id = google_secret_manager_secret.api_keys.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# --- Corpus bucket ----------------------------------------------------------

resource "google_storage_bucket" "corpus" {
  name                        = "${var.project_id}-${var.name}-corpus"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.force_destroy_corpus
  versioning {
    enabled = true
  }
  soft_delete_policy {
    retention_duration_seconds = var.corpus_soft_delete_retention_seconds
  }
}

resource "google_storage_bucket_iam_member" "corpus_access" {
  bucket = google_storage_bucket.corpus.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

# --- Cloud Run service (REST + MCP) -----------------------------------------

resource "google_cloud_run_v2_service" "api" {
  name     = var.name
  location = var.region

  # The provider protects this by default, independently of the database.
  # Without opting in, `terraform destroy -var deletion_protection=false`
  # removed the database and then refused the service, leaving an operator
  # who followed the teardown instructions with a service still running and
  # no documented way to remove it.
  deletion_protection = var.deletion_protection

  template {
    service_account = google_service_account.runtime.email

    containers {
      image = var.image

      env {
        name = "SCI_RAG_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SCI_RAG_API_KEYS"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.api_keys.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "SCI_RAG_GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "SCI_RAG_GCP_LOCATION"
        value = var.model_location
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 6
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.db.connection_name]
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }
  }

  depends_on = [google_secret_manager_secret_version.database_url]
}

# Public or not is your call; default is authenticated-only at the
# Google layer, with the app's API keys as the second layer.
resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.allow_unauthenticated ? 1 : 0
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Cloud Run job (migrations and ingestion, same image) -------------------

resource "google_cloud_run_v2_job" "ops" {

  # Same reason as the service above: the provider protects this by default,
  # so a documented `terraform destroy -var deletion_protection=false` left
  # the job behind.
  deletion_protection = var.deletion_protection
  name                = "${var.name}-ops"
  location            = var.region

  template {
    template {
      service_account = google_service_account.runtime.email
      max_retries     = 0

      containers {
        image   = var.image
        command = ["sci-rag"]
        args    = ["db", "upgrade"] # override per execution, see outputs

        env {
          name = "SCI_RAG_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }
        env {
          name  = "SCI_RAG_GCP_PROJECT"
          value = var.project_id
        }
        env {
          name  = "SCI_RAG_GCP_LOCATION"
          value = var.model_location
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }

        volume_mounts {
          name       = "corpus"
          mount_path = "/corpus"
        }
      }

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.db.connection_name]
        }
      }

      volumes {
        name = "corpus"
        gcs {
          bucket    = google_storage_bucket.corpus.name
          read_only = true
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_version.database_url]
}
