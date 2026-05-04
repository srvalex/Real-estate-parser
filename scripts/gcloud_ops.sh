#!/usr/bin/env bash
# gcloud_ops.sh
# Reference script for Cloud Run Job + Cloud Scheduler management.
# Run individual commands as needed — this is NOT meant to be executed all at once.
#
# Prerequisites:
#   gcloud auth login
#   gcloud config set project your-gcp-project-id

# Fill these in before running — do NOT commit real values here.
PROJECT=your-gcp-project-id
REGION=europe-west1
IMAGE=europe-west1-docker.pkg.dev/${PROJECT}/repo-crawler/crawler:latest
SA=your-compute-sa@${PROJECT}.iam.gserviceaccount.com
SUPABASE_URL=https://your-project.supabase.co   # from .env

# ─────────────────────────────────────────────────────────────────────────────
# 1. UPDATE CRAWLER SCHEDULE: every 6h → daily at 02:00 UTC
# ─────────────────────────────────────────────────────────────────────────────
gcloud scheduler jobs update http crawl-incremental \
  --schedule "0 2 * * *" \
  --location ${REGION}

# ─────────────────────────────────────────────────────────────────────────────
# 2. CREATE DEDICATED AVAILABILITY-CHECK JOB
#    Uses the same crawler image; different --args entry point.
#    Separate job = independent scheduling, retries, and monitoring in Console.
# ─────────────────────────────────────────────────────────────────────────────
gcloud run jobs create avail-check-job \
  --image          ${IMAGE} \
  --args           "--mode,availability-check" \
  --region         ${REGION} \
  --memory         4Gi \
  --cpu            2 \
  --task-timeout   7200 \
  --set-secrets    "SUPABASE_KEY=supabase-key:latest,PROXY_LIST=proxy-list:latest" \
  --set-env-vars   "SUPABASE_URL=${SUPABASE_URL}" \
  --service-account ${SA}

# ─────────────────────────────────────────────────────────────────────────────
# 3. RETARGET EXISTING AVAILABILITY-CHECK SCHEDULERS → avail-check-job
#    Both avail-check-mon and avail-check-thu currently point at crawler-job.
# ─────────────────────────────────────────────────────────────────────────────
AVAIL_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/avail-check-job:run"

gcloud scheduler jobs update http avail-check-mon \
  --uri             "${AVAIL_URI}" \
  --location        ${REGION}

gcloud scheduler jobs update http avail-check-thu \
  --uri             "${AVAIL_URI}" \
  --location        ${REGION}

# ─────────────────────────────────────────────────────────────────────────────
# 4. BUILD AND DEPLOY EMBEDDER JOB
#    Build context is the PROJECT ROOT (not embedding-service/) so db_utils.py
#    can be copied into the image alongside embed_job.py.
# ─────────────────────────────────────────────────────────────────────────────
EMBEDDER_IMAGE=europe-west1-docker.pkg.dev/${PROJECT}/repo-crawler/embedder:latest

# Build from project root
docker build -f embedding-service/Dockerfile -t ${EMBEDDER_IMAGE} .
docker push ${EMBEDDER_IMAGE}

# Create Cloud Run Job (runs embed_job.py by default per Dockerfile CMD)
gcloud run jobs create embedder-job \
  --image          ${EMBEDDER_IMAGE} \
  --region         ${REGION} \
  --memory         4Gi \
  --cpu            2 \
  --task-timeout   3600 \
  --set-secrets    "SUPABASE_KEY=supabase-key:latest" \
  --set-env-vars   "SUPABASE_URL=${SUPABASE_URL}" \
  --service-account ${SA}

# If the job already exists and you need to update it after a new image push:
# gcloud run jobs update embedder-job --image ${EMBEDDER_IMAGE} --region ${REGION}

# ─────────────────────────────────────────────────────────────────────────────
# 5. DELETE THE EMBEDDER CLOUD RUN SERVICE (eliminates the $1.05/day idle cost)
#    Do this AFTER verifying embedder-job works correctly with a test run.
#    Also clear EMBED_SERVICE_URL from your .env so Streamlit uses local ST.
# ─────────────────────────────────────────────────────────────────────────────
# gcloud run services delete embedder --region ${REGION}

# ─────────────────────────────────────────────────────────────────────────────
# 7. UPDATE PROXY LIST (run when new proxies are available)
#    Both jobs reference proxy-list:latest — updating the secret is enough.
#    Format: Webshare host:port:user:pass, one per line or comma-separated.
# ─────────────────────────────────────────────────────────────────────────────
# From a file:
#   gcloud secrets versions add proxy-list --data-file="new_proxies.txt"
#
# Inline:
#   echo "host1:port:user:pass,host2:port:user:pass" | \
#     gcloud secrets versions add proxy-list --data-file=-

# ─────────────────────────────────────────────────────────────────────────────
# 8. MANUAL TEST RUNS
# ─────────────────────────────────────────────────────────────────────────────
# gcloud run jobs execute crawler-job     --region ${REGION} --wait
# gcloud run jobs execute avail-check-job --region ${REGION} --wait
# gcloud run jobs execute embedder-job    --region ${REGION} --wait

# ─────────────────────────────────────────────────────────────────────────────
# 9. VIEW LOGS
# ─────────────────────────────────────────────────────────────────────────────
# gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=embedder-job" \
#   --limit 100 --format "table(timestamp,textPayload)"
# gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=avail-check-job" \
#   --limit 100 --format "table(timestamp,textPayload)"
