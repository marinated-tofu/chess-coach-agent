# Google Cloud infrastructure

OpenTofu config for running the app on Google Cloud instead of Render.

| Piece | Service | Notes |
| --- | --- | --- |
| App server | Cloud Run | Scales to zero. `max_instances` caps the compute bill. |
| Database | Cloud SQL Postgres 16 | `db-f1-micro`, daily backups kept 7 days, point-in-time recovery. pgvector is enabled by the migrations. |
| Secrets | Secret Manager | `DATABASE_URL` and `SESSION_SECRET` are generated. `OPENROUTER_API_KEY` and `LICHESS_API_TOKEN` you add by hand. |
| Images | Artifact Registry | Keeps the 5 newest images and deletes anything older than 30 days. |
| Deploys | GitHub Actions + Workload Identity Federation | No service account keys. Only `marinated-tofu/chess-coach-agent` can deploy. |
| Spending cap | Billing budget + kill switch | Emails at 50%, 90% and 100%. At 100% a Cloud Function detaches billing, which stops everything. |

The coach still calls Claude through OpenRouter. Moving it to Vertex AI is a separate change.

## Rough monthly cost

Estimates from list prices; check them in the [pricing calculator](https://cloud.google.com/products/calculator).

| Item | Estimate |
| --- | --- |
| Cloud SQL `db-f1-micro` + 10 GB SSD + backups | about $10–12 |
| Cloud Run, scale to zero, light traffic | $0–10 |
| Cloud Run with `min_instances = 1` | add about $30–45 |
| Secret Manager, Artifact Registry, Pub/Sub, function | under $1 |

## First deploy

Billing must be open on the account first (Console → Billing).

```bash
gcloud projects create chess-coach-prod
gcloud billing projects link chess-coach-prod --billing-account=<ACCOUNT_ID>
gcloud auth application-default login

cd infra/gcp
cp terraform.tfvars.example terraform.tfvars   # fill in project and billing account
tofu init

# 1. Create the secret containers, then add the values you supply.
tofu apply -target=google_secret_manager_secret.manual
printf '%s' "$OPENROUTER_API_KEY" | gcloud secrets versions add OPENROUTER_API_KEY --data-file=-
printf '%s' "$LICHESS_API_TOKEN"  | gcloud secrets versions add LICHESS_API_TOKEN --data-file=-

# 2. Everything else. Cloud SQL takes about 10 minutes.
tofu apply
```

The first apply runs a placeholder image. To deploy the app, set these repository variables in GitHub (Settings → Secrets and variables → Actions → Variables), using `tofu output`:

| Variable | From |
| --- | --- |
| `GCP_PROJECT_ID` | your project id |
| `GCP_REGION` | `us-central1` unless you changed it |
| `GCP_WIF_PROVIDER` | `tofu output workload_identity_provider` |
| `GCP_DEPLOYER_SA` | `tofu output deployer_service_account` |

Then run the **Deploy to Cloud Run** workflow from the Actions tab.

## Moving data from Render

```bash
pg_dump --no-owner --no-acl "$RENDER_DATABASE_URL" > render.sql
gcloud sql import sql chess-coach-db gs://<bucket>/render.sql --database=chess_coach
```

## If the kill switch fires

Billing is detached and every service stops. Raise `monthly_budget_usd` or find what spent the money, then re-link billing:

```bash
gcloud billing projects link <PROJECT_ID> --billing-account=<ACCOUNT_ID>
```

Set `enable_kill_switch = false` if you would rather get alerts only.
