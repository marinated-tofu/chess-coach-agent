variable "project_id" {
  description = "Google Cloud project that holds everything for the app."
  type        = string
}

variable "billing_account_id" {
  description = "Billing account linked to the project, e.g. 01B90D-XXXXXX-XXXXXX. Used for the budget."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Cloud SQL and Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "github_repository" {
  description = "owner/name of the repository allowed to deploy through Workload Identity Federation."
  type        = string
  default     = "marinated-tofu/chess-coach-agent"
}

variable "image" {
  description = "Container image for the first deploy. Later deploys come from GitHub Actions and are ignored here."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "public_base_url" {
  description = "Public origin used for OAuth redirects. Leave empty until a domain is mapped."
  type        = string
  default     = ""
}

variable "max_instances" {
  description = "Hard ceiling on Cloud Run instances. This caps the worst-case compute bill."
  type        = number
  default     = 2
}

variable "min_instances" {
  description = "Instances kept warm. 0 is cheapest but the first request after idle waits for a cold start."
  type        = number
  default     = 0
}

variable "db_tier" {
  description = "Cloud SQL machine type. db-f1-micro is the cheapest shared-core tier."
  type        = string
  default     = "db-f1-micro"
}

variable "monthly_budget_usd" {
  description = "Monthly budget in USD. Alerts fire at 50%, 90% and 100%."
  type        = number
  default     = 50
}

variable "budget_alert_emails" {
  description = "Addresses that get budget alerts in addition to the billing account admins."
  type        = list(string)
  default     = []
}

variable "enable_kill_switch" {
  description = "Detach billing from the project when spend passes the budget. Stops every service, including the database."
  type        = bool
  default     = true
}

variable "openrouter_model" {
  description = "Model the coach uses through OpenRouter."
  type        = string
  default     = "anthropic/claude-haiku-5.5"
}

variable "enable_uptime_check" {
  description = "Probe /api/health/ready from three regions. The probes keep an instance running, which ends scale to zero: see the README before turning this on with a low budget."
  type        = bool
  default     = true
}

variable "uptime_check_period" {
  description = "How often each region probes. One of 60s, 300s, 600s or 900s."
  type        = string
  default     = "900s"
}

variable "server_error_alert_per_minute" {
  description = "Alert when 5xx responses average more than this many per minute over 5 minutes."
  type        = number
  default     = 1
}
