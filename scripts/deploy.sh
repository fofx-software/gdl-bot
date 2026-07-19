#!/usr/bin/env bash
set -euo pipefail

service="${CLOUD_RUN_SERVICE:-gdl-bot}"
region="${CLOUD_RUN_REGION:-us-east4}"

gcloud run deploy "$service" --source . --region "$region" "$@"
.venv/bin/python -m app.telegram_setup --service "$service" --region "$region"
