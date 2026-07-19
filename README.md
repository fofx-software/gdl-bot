# GDL Bot Manager

Minimal FastAPI scaffold for an OpenAI bot-management service hosted on Google Cloud Run with Firestore access.

## What is included

- Cloud Run-compatible HTTP server listening on `$PORT`
- `/health` liveness endpoint
- `/ready` endpoint that verifies Firestore access
- Firestore client using Google Application Default Credentials (no service-account keys in the app)
- Centralized OpenAI response creation with instructions loaded from Firestore
- Non-root production container
- Small test suite

## Run locally

Python 3.12 and Google Cloud Application Default Credentials are expected.

Copy `.env.example` to `.env` and populate the required secrets before running
the Telegram integration locally. In Cloud Run, store secret values in Secret
Manager rather than deploying a populated `.env` file.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
gcloud auth application-default login
.venv/bin/uvicorn app.main:app --reload
```

Then open <http://localhost:8000/docs>. The liveness endpoint works without credentials; `/ready` queries Firestore.

## Connect Telegram

Create a bot with Telegram's `@BotFather`, copy `.env.example` to `.env`, and
set the bot token, OpenAI API key, and a random webhook secret. The deployment
script discovers the Cloud Run URL and registers its `/telegram` webhook after
every successful deployment:

```bash
scripts/deploy.sh \
  --service-account gdl-bot-runtime@PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated
```

The script uses the active gcloud project. Override its defaults with
`CLOUD_RUN_SERVICE` or `CLOUD_RUN_REGION`, or register separately with
`.venv/bin/python -m app.telegram_setup --project PROJECT_ID`.

Telegram sends text-message updates to `POST /telegram`. The service validates
the webhook secret header, uses the Telegram sender ID as the application user
ID, routes the message through its user-scoped topic state, and replies through
Telegram's `sendMessage` API. Unsupported updates are acknowledged and ignored.

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

Build, deploy, and register the Telegram webhook from this directory:

```bash
scripts/deploy.sh \
  --service-account gdl-bot-runtime@PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated
```

Cloud Run supplies Application Default Credentials to the Firestore client through the assigned service account. Do not add credential JSON files to this repository.

Bot instructions are composed for every OpenAI Responses API call in `app.bot.create_response`. The hard-coded `BASE_INSTRUCTIONS` constant is concatenated directly with the `instructions` string in the user-scoped Firestore document `users/{user_id}/config/bot`. A missing document or field contributes an empty string. Callers must supply the stable application user ID; path-like values are rejected to preserve user isolation.

`app.bot.handle_request` routes each message among user-scoped topic chains. Structured output classifies a message as `continue`, `switch`, or `create`; ambiguous follow-ups continue the active topic. Firestore stores the active pointer at `users/{user_id}/state/conversation` and each topic's latest response ID at `users/{user_id}/topics/{topic_key}`. Both pointers are updated together in one atomic batch after a successful OpenAI response.

The same routing decision can extract a concise `instruction_update` when the user states a general preference or instruction for future requests. The service appends non-empty, non-duplicate updates to `users/{user_id}/config/bot.instructions` before creating the answer, so the preference applies immediately. Request-specific directions are not persisted.

User-facing responses can call three Firestore tools: read one document, list
documents, or create/replace one document. These operations are restricted in
application code to `users/{user_id}/data/{key}`. Keys may contain only letters,
digits, underscores, and hyphens; the model cannot supply a user ID or access
the protected `config`, `state`, or `topics` collections. Tool execution is
limited to five sequential rounds per response.

For a private management API, omit `--allow-unauthenticated` and invoke it with an identity token.
