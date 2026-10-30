locals {
  alert_channels = [for channel in google_monitoring_notification_channel.budget_email : channel.id]
}

resource "google_monitoring_uptime_check_config" "ready" {
  count        = var.enable_uptime_check ? 1 : 0
  display_name = "chess-coach ready"
  timeout      = "30s"
  period       = var.uptime_check_period
  # Three is the minimum, and the fewest requests to the app.
  selected_regions = ["USA", "EUROPE", "ASIA_PACIFIC"]

  http_check {
    path         = "/api/health/ready"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = trimsuffix(trimprefix(google_cloud_run_v2_service.app.uri, "https://"), "/")
    }
  }

  depends_on = [google_project_service.enabled]
}

# A cold start can outlast one probe, so this needs two regions failing for a whole period.
resource "google_monitoring_alert_policy" "uptime" {
  count                 = var.enable_uptime_check ? 1 : 0
  display_name          = "chess-coach is not ready"
  combiner              = "OR"
  notification_channels = local.alert_channels

  conditions {
    display_name = "Readiness check failing"
    condition_threshold {
      filter          = "metric.type = \"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type = \"uptime_url\" AND metric.labels.check_id = \"${google_monitoring_uptime_check_config.ready[0].uptime_check_id}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = var.uptime_check_period

      aggregations {
        alignment_period     = "1200s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.host"]
      }
    }
  }

  documentation {
    mime_type = "text/markdown"
    content   = "/api/health/ready is failing. It returns which check failed, database or stockfish. See the service logs."
  }

  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_alert_policy" "server_errors" {
  display_name          = "chess-coach 5xx rate"
  combiner              = "OR"
  notification_channels = local.alert_channels

  conditions {
    display_name = "5xx responses per second"
    condition_threshold {
      filter          = "metric.type = \"run.googleapis.com/request_count\" AND resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"${google_cloud_run_v2_service.app.name}\" AND metric.labels.response_code_class = \"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.server_error_alert_per_minute / 60
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  alert_strategy {
    auto_close = "86400s"
  }

  documentation {
    mime_type = "text/markdown"
    content   = "The app is returning 5xx responses. Unhandled exceptions are logged as JSON with severity ERROR, a path and a stack_trace."
  }

  depends_on = [google_project_service.enabled]
}
