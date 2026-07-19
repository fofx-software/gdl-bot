"""Discover the Cloud Run URL and register its Telegram webhook."""

import argparse
import subprocess

from app.config import get_settings
from app.telegram import TelegramClient


def cloud_run_url(service: str, region: str, project: str | None = None) -> str:
    command = [
        "gcloud",
        "run",
        "services",
        "describe",
        service,
        "--region",
        region,
        "--format=value(status.url)",
    ]
    if project:
        command.extend(["--project", project])
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    url = result.stdout.strip().rstrip("/")
    if not url.startswith("https://"):
        raise RuntimeError("Cloud Run did not return a public HTTPS service URL")
    return url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", default="gdl-bot")
    parser.add_argument("--region", default="us-east4")
    parser.add_argument("--project")
    args = parser.parse_args()

    settings = get_settings()
    webhook_url = f"{cloud_run_url(args.service, args.region, args.project)}/telegram"
    TelegramClient(settings.telegram_bot_token).set_webhook(
        webhook_url,
        settings.telegram_webhook_secret,
    )
    print(f"Telegram webhook registered: {webhook_url}")


if __name__ == "__main__":
    main()
