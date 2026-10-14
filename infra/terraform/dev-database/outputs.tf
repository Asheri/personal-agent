output "connection_name" {
  description = "Cloud SQL connection name used by the Auth Proxy."
  value       = google_sql_database_instance.dev.connection_name
}

output "instance_name" {
  description = "Cloud SQL instance managed by this module."
  value       = google_sql_database_instance.dev.name
}

output "sci_rag_cloud_pg_config" {
  description = "Non-secret environment settings for scripts/cloud_postgres.py."
  value = join("\n", [
    "SCI_RAG_CLOUD_PG_PROJECT=${var.project_id}",
    "SCI_RAG_CLOUD_PG_INSTANCE=${google_sql_database_instance.dev.name}",
    "SCI_RAG_CLOUD_PG_REGION=${var.region}",
    "SCI_RAG_CLOUD_PG_USER=${var.database_user}",
  ])
}
