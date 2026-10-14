output "service_url" {
  description = "The Cloud Run URL (docs at /docs, MCP at /mcp)."
  value       = google_cloud_run_v2_service.api.uri
}

output "db_connection_name" {
  description = "Cloud SQL connection name (for the Auth Proxy during ingestion from your laptop)."
  value       = google_sql_database_instance.db.connection_name
}

output "corpus_bucket" {
  value = google_storage_bucket.corpus.name
}

output "run_migrations" {
  description = "Run this once after every deploy that changes the schema."
  value       = "gcloud run jobs execute ${google_cloud_run_v2_job.ops.name} --region=${var.region} --project=${var.project_id} --wait"
}

# The bucket is mounted at /corpus in the ops job, so this command reads the
# manifest and its relative document paths without putting either in the image.
output "run_ops_job_example" {
  description = "Ingest the manifest mounted from the corpus bucket."
  value       = "gcloud run jobs execute ${google_cloud_run_v2_job.ops.name} --region=${var.region} --project=${var.project_id} --args='ingest,--manifest,/corpus/manifest.jsonl' --wait"
}

output "corpus_bucket_purpose" {
  description = "Where to stage a corpus for the ops job."
  value       = "Stage corpora in gs://${google_storage_bucket.corpus.name}. The bucket is mounted read-only at /corpus in the ops job and is not mounted in the REST or MCP service."
}

# Where to read the generated first API key. Deliberately not the key itself:
# a Terraform output lands in state, and state is already a credential we tell
# operators not to circulate. This prints the command instead.
output "read_first_api_key" {
  description = "How to read the API key the deploy generated."
  value       = "gcloud secrets versions access latest --secret=${google_secret_manager_secret.api_keys.secret_id} --project=${var.project_id}"
}
