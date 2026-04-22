"""Hybrid chatbot service for NetSense AI.

This module keeps critical actions deterministic and uses Gemini only for
short explanations and next-step suggestions.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REQUEST_TIMEOUT_SECONDS = 8
MAX_COMPLETION_TOKENS = 90


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_local_env_value(key: str) -> str | None:
    """Read a single key from backend-side .env files for local development."""
    env_files = [
        os.path.join(BASE_DIR, ".env"),
        os.path.join(os.path.dirname(BASE_DIR), ".env"),
    ]

    for env_file in env_files:
        if not os.path.exists(env_file):
            continue

        try:
            with open(env_file, "r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue

                    name, value = line.split("=", 1)
                    if name.strip() != key:
                        continue

                    return value.strip().strip("'\"")
        except OSError:
            continue

    return None


def _get_setting(key: str) -> str | None:
    """Prefer real environment variables, then fall back to local .env files."""
    return os.getenv(key) or _load_local_env_value(key)


def _get_model() -> str:
    return _get_setting("GEMINI_MODEL") or "gemini-2.5-flash"


def _get_base_url() -> str:
    return _get_setting("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta/models"


def detect_intent(user_input: str) -> str:
    """Return a lightweight intent label for the incoming message."""
    normalized = (user_input or "").strip().lower()

    if any(keyword in normalized for keyword in ("fix", "repair", "solve", "troubleshoot")):
        return "fix"

    return "explain"


def _format_metrics(metrics: dict[str, Any]) -> str:
    download = _to_float(metrics.get("download"))
    upload = _to_float(metrics.get("upload"))
    ping = _to_float(metrics.get("ping"))
    timestamp = metrics.get("timestamp", "unknown")

    return (
        f"Download: {download:.2f} Mbps\n"
        f"Upload: {upload:.2f} Mbps\n"
        f"Ping: {ping:.2f} ms\n"
        f"Timestamp: {timestamp}"
    )


def _network_condition_summary(metrics: dict[str, Any]) -> str:
    """Summarize the current network condition using all available metrics."""
    download = _to_float(metrics.get("download"))
    upload = _to_float(metrics.get("upload"))
    ping = _to_float(metrics.get("ping"))

    assessments = []

    if ping >= 100:
        assessments.append("latency is very high")
    elif ping >= 60:
        assessments.append("latency is elevated")
    else:
        assessments.append("latency is stable")

    if download < 25:
        assessments.append("download speed is weak")
    elif download < 75:
        assessments.append("download speed is moderate")
    else:
        assessments.append("download speed is strong")

    if upload < 10:
        assessments.append("upload speed is weak")
    elif upload < 20:
        assessments.append("upload speed is usable")
    else:
        assessments.append("upload speed is strong")

    return ", ".join(assessments)


def _fallback_explanation(user_input: str, metrics: dict[str, Any]) -> str:
    """Return a compact 2 to 3 line reply when the model output is weak or truncated."""
    download = _to_float(metrics.get("download"))
    upload = _to_float(metrics.get("upload"))
    ping = _to_float(metrics.get("ping"))
    normalized = (user_input or "").strip().lower()

    first_line = (
        f"Your network currently shows {download:.2f} Mbps download, {upload:.2f} Mbps upload, "
        f"and {ping:.2f} ms ping."
    )

    if ping >= 100:
        second_line = "The main issue is very high latency, so gaming, calls, and page response may feel laggy."
        suggestion = "Pause background traffic, move closer to the router, and restart the router if high ping continues."
    elif ping >= 60:
        second_line = "Latency is above ideal, so the connection may feel inconsistent during calls, streaming, or gaming."
        suggestion = "Reduce competing traffic, prefer 5 GHz nearby, and retest from a stronger WiFi spot."
    elif download < 25 and upload < 10:
        second_line = "Both download and upload are low, so streaming, meetings, and cloud sync may struggle."
        suggestion = "Check signal strength, reduce device load, and contact your ISP if speeds stay low after a reboot."
    elif download < 25:
        second_line = "Download speed is the main limit right now, so browsing and streaming may feel slower than expected."
        suggestion = "Test closer to the router and reduce heavy usage on other devices before retesting."
    elif upload < 10:
        second_line = "Upload speed is the weakest area, which can hurt video calls, uploads, and backups."
        suggestion = "Pause uploads on other devices and switch to a stronger WiFi band or location."
    else:
        second_line = "Overall the connection looks balanced for normal browsing, work, and streaming."
        suggestion = "If issues continue, retest while checking app load, WiFi signal, and router congestion."

    if "ping" in normalized or "latency" in normalized:
        second_line = (
            f"Ping is the key factor here: {ping:.2f} ms means {_network_condition_summary(metrics)}, "
            "which affects responsiveness more than raw speed."
        )
    elif "download" in normalized:
        second_line = (
            f"Download speed is {download:.2f} Mbps, and with upload at {upload:.2f} Mbps and ping at {ping:.2f} ms, "
            "the full picture suggests " + _network_condition_summary(metrics) + "."
        )
    elif "upload" in normalized:
        second_line = (
            f"Upload speed is {upload:.2f} Mbps, and alongside {download:.2f} Mbps download and {ping:.2f} ms ping, "
            "that suggests " + _network_condition_summary(metrics) + "."
        )

    return "\n".join([first_line, second_line, suggestion])


def _looks_incomplete(response_text: str) -> bool:
    """Detect likely truncated responses before sending them to the UI."""
    text = (response_text or "").strip()
    if not text:
        return True

    if len(text) < 45:
        return True

    if text.endswith(("or", "and", "because", "but", "with", "to", "of", "by", ",")):
        return True

    if text[-1] not in ".!?":
        return True

    return False


def _system_instruction() -> str:
    return (
        "You are NetSense AI, a helpful network assistant. "
        "Answer using the provided network metrics. "
        "Use all three values: download, upload, and ping. "
        "Keep the reply short in exactly 2 or 3 complete lines. "
        "Each line must be a complete sentence and under 18 words where possible. "
        "Give a clear explanation plus one actionable suggestion. "
        "Avoid filler, greetings, and repetition. "
        "Do not claim to have fixed anything yourself."
    )


def _build_prompt(user_input: str, metrics: dict[str, Any]) -> str:
    """Create the user prompt payload for Gemini."""
    return (
        "User question:\n"
        f"{(user_input or '').strip()}\n\n"
        "Current network metrics:\n"
        f"{_format_metrics(metrics)}\n\n"
        "Context summary:\n"
        f"{_network_condition_summary(metrics)}\n\n"
        "Instruction: respond as a network assistant using all three metrics in only 2 or 3 short lines, "
        "with one concise recommendation and no extra filler."
    )


def _manual_fix_message(metrics: dict[str, Any]) -> str:
    """Return deterministic troubleshooting guidance for critical actions."""
    download = _to_float(metrics.get("download"))
    upload = _to_float(metrics.get("upload"))
    ping = _to_float(metrics.get("ping"))

    steps = [
        "1. Restart your router and modem, then reconnect this device.",
        "2. Move closer to the router or switch to 5 GHz if available.",
        "3. Pause heavy downloads, uploads, or streaming on other devices.",
    ]

    if ping >= 80:
        steps.append("4. High ping suggests congestion or interference, so test again after reducing competing traffic.")
    elif download < 25 or upload < 10:
        steps.append("4. If speeds stay low after a reboot, check with your ISP for a line issue or plan cap.")
    else:
        steps.append("4. If the issue continues despite healthy metrics, forget and reconnect the WiFi network on this device.")

    return "\n".join(steps)


def ask_ai(user_input: str, metrics: dict[str, Any]) -> str:
    """Ask Gemini for a short network explanation."""
    api_key = _get_setting("GEMINI_API_KEY")
    if not api_key:
        return (
            "AI chat is not configured yet. Add GEMINI_API_KEY to your backend environment "
            "or backend/.env file, then ask again for a metrics-aware network explanation."
        )

    payload = {
        "system_instruction": {
            "parts": [
                {"text": _system_instruction()},
            ],
        },
        "contents": [
            {
                "parts": [
                    {"text": _build_prompt(user_input, metrics)},
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": MAX_COMPLETION_TOKENS,
        },
    }

    base_url = _get_base_url().rstrip("/")
    chat_url = f"{base_url}/{_get_model()}:generateContent"

    req = request.Request(
        chat_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return (
            "I could not reach the AI assistant right now. "
            f"Provider error: HTTP {exc.code}. {detail[:180]}".strip()
        )
    except error.URLError:
        return "I could not reach the AI assistant right now. Please try again in a moment."
    except (TimeoutError, json.JSONDecodeError, OSError):
        return "I could not generate an AI explanation right now. Please try again shortly."

    choices = body.get("choices") or []
    if not choices:
        choices = body.get("candidates") or []

    if not choices:
        return _fallback_explanation(user_input, metrics)

    content = choices[0].get("content") or {}
    parts = content.get("parts") or []
    text_parts = [part.get("text", "").strip() for part in parts if part.get("text")]
    response_text = "\n".join(part for part in text_parts if part).strip()

    if _looks_incomplete(response_text):
        return _fallback_explanation(user_input, metrics)

    return response_text


def chatbot_response(user_input: str, metrics: dict[str, Any]) -> str:
    """Route critical fix requests to rules and everything else to AI."""
    intent = detect_intent(user_input)

    if intent == "fix":
        return _manual_fix_message(metrics)

    return ask_ai(user_input, metrics)
