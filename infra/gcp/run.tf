resource "google_cloud_run_v2_service" "app" {
  name                = "chess-coach"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "300s"
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
        # Game syncs run as background tasks after the request returns. With CPU
        # throttled between requests they would stall, so keep CPU allocated.
        cpu_idle          = false
        startup_cpu_boost = true
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        http_get {
          path = "/api/health"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 36
      }

      dynamic "env" {
        for_each = {
          OPENROUTER_MODEL        = var.openrouter_model
          STOCKFISH_DEPTH         = "7"
          ENABLE_LOCAL_EMBEDDINGS = "true"
          LICHESS_CLIENT_ID       = "chess-coach-agent"
          PUBLIC_BASE_URL         = var.public_base_url
          MONITORING_LOG_PATH     = "/tmp/chess-coach-events.jsonl"
        }
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = toset(concat(local.manual_secrets, ["SESSION_SECRET", "DATABASE_URL"]))
        content {
          name = env.value
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    # GitHub Actions deploys new images; don't roll them back on the next apply.
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_secret_manager_secret_iam_member.runtime_access,
    google_secret_manager_secret_version.database_url,
    google_secret_manager_secret_version.session_secret,
    google_project_iam_member.runtime_sql,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.app.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
