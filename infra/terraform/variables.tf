variable "project_id" {
  description = "Google Cloud project id."
  type        = string
}

variable "region" {
  description = "Region for everything (Cloud SQL, Cloud Run, bucket)."
  type        = string
  default     = "us-central1"
}

variable "name" {
  description = "Base name for resources (service, db, secrets)."
  type        = string
  default     = "sci-rag"
}

variable "image" {
  description = "Container image (for example REGION-docker.pkg.dev/PROJECT/REPO/sci-rag:TAG). Build it from the repo Dockerfile."
  type        = string
}

variable "model_location" {
  description = "Vertex AI location for model calls (SCI_RAG_GCP_LOCATION). Separate from var.region, which places infrastructure. The default Gemini model is served from global, not from a region."
  type        = string
  default     = "global"
}

variable "db_tier" {
  description = "Cloud SQL machine tier. db-g1-small is the smallest sensible dev tier; size up for real load."
  type        = string
  default     = "db-g1-small"
}

variable "max_instances" {
  description = "Cloud Run max instances."
  type        = number
  default     = 3
}

variable "allow_unauthenticated" {
  description = "Expose the service publicly at the Google layer (the app's own API keys still apply)."
  type        = bool
  default     = false
}

variable "deletion_protection" {
  description = "Protect the database, Cloud Run service, and Cloud Run job from accidental terraform destroy."
  type        = bool
  default     = true
}

variable "force_destroy_corpus" {
  description = "Allow Terraform to delete live and noncurrent corpus objects. Keep false for recoverable deployments."
  type        = bool
  default     = false
}

variable "corpus_soft_delete_retention_seconds" {
  description = "Cloud Storage soft-delete retention in seconds. Use 0 only for a disposable corpus, or 604800 through 7776000."
  type        = number
  default     = 604800

  validation {
    condition = var.corpus_soft_delete_retention_seconds == 0 || (
      var.corpus_soft_delete_retention_seconds >= 604800 &&
      var.corpus_soft_delete_retention_seconds <= 7776000
    )
    error_message = "corpus_soft_delete_retention_seconds must be 0 or between 604800 and 7776000."
  }
}
