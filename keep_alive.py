"""Render health endpoint and optional, rate-limited self-ping helper.

The self-ping is a liveness aid only. It must not be treated as a guarantee
against Render Free service spin-down or restarts.
"""

import logging
import os
import threading
import time

import requests
from flask import Flask, jsonify

logging.getLogger("werkzeug").setLevel(logging.ERROR)
logger = logging.getLogger("card-autocatcher.keep-alive")

app = Flask(__name__)
PORT = int(os.getenv("PORT", "10000"))
SELF_PING_INTERVAL = max(60, int(os.getenv("SELF_PING_INTERVAL", "180")))
SELF_PING_START_DELAY = max(0, int(os.getenv("SELF_PING_START_DELAY", "10")))
SELF_PING_TIMEOUT = max(3, int(os.getenv("SELF_PING_TIMEOUT", "10")))


def _service_url() -> str:
    configured = os.getenv("SELF_PING_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    if render_url:
        return render_url.rstrip("/")
    return f"http://127.0.0.1:{PORT}"


@app.get("/")
@app.get("/health")
@app.get("/healthz")
@app.get("/<path:path>")
def health(path: str = ""):
    return jsonify(
        {
            "status": "ok",
            "service": "telegram-card-autocatcher",
            "self_ping": "enabled",
        }
    ), 200


def self_ping_loop() -> None:
    time.sleep(SELF_PING_START_DELAY)
    url = f"{_service_url()}/healthz"
    while True:
        try:
            response = requests.get(url, timeout=SELF_PING_TIMEOUT)
            logger.info("Keep-alive ping %s -> HTTP %s", url, response.status_code)
        except requests.RequestException as exc:
            logger.warning("Keep-alive ping failed: %s", exc)
        time.sleep(SELF_PING_INTERVAL)


def start_keep_alive() -> None:
    """Start the HTTP server and self-ping loop as daemon threads."""
    threading.Thread(target=self_ping_loop, daemon=True, name="self-ping").start()
    threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=PORT,
            debug=False,
            use_reloader=False,
        ),
        daemon=True,
        name="health-server",
    ).start()
