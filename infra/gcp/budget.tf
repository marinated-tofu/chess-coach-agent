data "google_project" "current" {}

resource "google_pubsub_topic" "budget" {
  name       = "billing-budget"
  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_notification_channel" "budget_email" {
  for_each     = toset(var.budget_alert_emails)
  display_name = "Budget alert ${each.value}"
  type         = "email"
  labels = {
    email_address = each.value
  }
}

# A budget only sends alerts. The kill switch below is what actually stops spending.
resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account_id
  display_name    = "chess-coach monthly"

  budget_filter {
    projects = ["projects/${data.google_project.current.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }

  dynamic "threshold_rules" {
    for_each = [0.5, 0.9, 1.0]
    content {
      threshold_percent = threshold_rules.value
    }
  }

  all_updates_rule {
    pubsub_topic                     = google_pubsub_topic.budget.id
    monitoring_notification_channels = [for channel in google_monitoring_notification_channel.budget_email : channel.id]
    disable_default_iam_recipients   = false
  }

  depends_on = [google_project_service.enabled]
}

resource "google_service_account" "kill_switch" {
  count        = var.enable_kill_switch ? 1 : 0
  account_id   = "billing-kill-switch"
  display_name = "Detaches billing when the budget is exceeded"
}

# Needed to unlink the project from its billing account.
resource "google_project_iam_member" "kill_switch_billing" {
  count   = var.enable_kill_switch ? 1 : 0
  project = var.project_id
  role    = "roles/billing.projectManager"
  member  = "serviceAccount:${google_service_account.kill_switch[0].email}"
}

resource "google_storage_bucket" "functions" {
  count                       = var.enable_kill_switch ? 1 : 0
  name                        = "${var.project_id}-functions-src"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
}

data "archive_file" "kill_switch" {
  type        = "zip"
  source_dir  = "${path.module}/kill_switch"
  output_path = "${path.module}/.build/kill_switch.zip"
}

resource "google_storage_bucket_object" "kill_switch" {
  count  = var.enable_kill_switch ? 1 : 0
  name   = "kill_switch-${data.archive_file.kill_switch.output_md5}.zip"
  bucket = google_storage_bucket.functions[0].name
  source = data.archive_file.kill_switch.output_path
}

resource "google_cloudfunctions2_function" "kill_switch" {
  count    = var.enable_kill_switch ? 1 : 0
  name     = "billing-kill-switch"
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = "stop_billing"
    source {
      storage_source {
        bucket = google_storage_bucket.functions[0].name
        object = google_storage_bucket_object.kill_switch[0].name
      }
    }
  }

  service_config {
    max_instance_count    = 1
    available_memory      = "256M"
    service_account_email = google_service_account.kill_switch[0].email
    environment_variables = {
      PROJECT_ID = var.project_id
    }
  }

  event_trigger {
    trigger_region        = var.region
    event_type            = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic          = google_pubsub_topic.budget.id
    retry_policy          = "RETRY_POLICY_RETRY"
    service_account_email = google_service_account.kill_switch[0].email
  }

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_member" "kill_switch_invoker" {
  count   = var.enable_kill_switch ? 1 : 0
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.kill_switch[0].email}"
}
