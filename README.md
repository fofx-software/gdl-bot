# GDL Bot Manager

Minimal FastAPI scaffold for an OpenAI bot-management service hosted on Google Cloud Run with Firestore access.

## What is included

- Cloud Run-compatible HTTP server listening on `$PORT`
- `/health` liveness endpoint
- `/ready` endpoint that verifies Firestore access
- Firestore client using Google Application Default Credentials (no service-account keys in the app)
- Non-root production container
- Small test suite

## Run locally

Python 3.12 and Google Cloud Application Default Credentials are expected.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
gcloud auth application-default login
.venv/bin/uvicorn app.main:app --reload
```

Then open <http://localhost:8000/docs>. The liveness endpoint works without credentials; `/ready` queries Firestore.

## Test

```bash
.venv/bin/pytest
```

## Deploy to Cloud Run

Choose an existing Google Cloud project, enable the required APIs, and create a Firestore database in Native mode if the project does not already have one:

```bash
gcloud config set project PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com firestore.googleapis.com
gcloud firestore databases create --location=us-east4
```

Create a dedicated runtime service account and grant it Firestore access:

```bash
gcloud iam service-accounts create gdl-bot-runtime \
  --display-name="GDL Bot Cloud Run runtime"

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:gdl-bot-runtime@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
```

Build and deploy from this directory:

```bash
gcloud run deploy gdl-bot \
  --source . \
  --region us-east4 \
  --service-account gdl-bot-runtime@PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated
```

Cloud Run supplies Application Default Credentials to the Firestore client through the assigned service account. Do not add credential JSON files to this repository.

For a private management API, omit `--allow-unauthenticated` and invoke it with an identity token.
