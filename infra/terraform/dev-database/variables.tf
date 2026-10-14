# The two inputs that decide what a mutation is aimed at have no defaults.
# This module used to ship the maintainer's project and the live shared
# instance name, so anyone who ran it without both overrides planned changes
# against infrastructure they did not name. Terraform now refuses at input
# validation, before it reads state or plans anything.
#
# Region, tier, and database user keep their defaults. They are development
# cost and shape choices, and none of them can point a change at somebody
# else's instance.

variable "project_id" {
  description = "Google Cloud project that will own the development database. Required: pass -var project_id=YOUR_PROJECT."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a Google Cloud project id, for example my-team-dev-1234. Name your own project; there is no default."
  }
}

variable "region" {
  description = "Cloud SQL region. Choose one near the developers using the proxy."
  type        = string
  default     = "us-west1"
}

variable "instance_name" {
  description = "Name for the development-only Cloud SQL instance this module creates. Required: pass -var instance_name=YOUR_INSTANCE."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,61}[a-z0-9]$", var.instance_name))
    error_message = "instance_name must be a Cloud SQL instance name you own. Name it yourself; there is no default, so this module cannot reach an instance you did not ask for."
  }
}

variable "db_tier" {
  description = "Smallest sensible development tier; increase only after measurement."
  type        = string
  default     = "db-g1-small"
}

variable "database_user" {
  description = "Built-in PostgreSQL user shared by workspace databases."
  type        = string
  default     = "sci_rag"
}

variable "developer_principal" {
  description = "IAM principal that runs the helper, for example user:name@example.org."
  type        = string
}

variable "deletion_protection" {
  description = "Protect the disposable dev instance from terraform destroy."
  type        = bool
  default     = false
}
