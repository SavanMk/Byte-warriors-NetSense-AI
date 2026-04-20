"""Rule-based AI helpers for Day 4 recommendations and chatbot replies."""

from __future__ import annotations


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def generate_ai_recommendation(metrics):
    """Analyze current metrics and return a simple recommendation payload."""
    download = _to_float(metrics.get("download"))
    upload = _to_float(metrics.get("upload"))
    ping = _to_float(metrics.get("ping"))

    issues = []
    recommendations = []
    severity_score = 0

    if ping >= 80:
        issues.append("Ping is high, which can cause lag and unstable browsing or calls.")
        recommendations.extend(
            [
                "Reduce background downloads or streaming on the network.",
                "Move closer to the router or remove signal obstacles.",
                "Restart the router if latency has stayed high for several tests.",
            ]
        )
        severity_score += 2
    elif ping >= 40:
        issues.append("Ping is slightly elevated, so responsiveness may dip during busy periods.")
        recommendations.append("Limit heavy background activity when low-latency use matters.")
        severity_score += 1

    if download < 25:
        issues.append("Download speed is below the healthy range for a modern home network.")
        recommendations.extend(
            [
                "Reposition the router for a clearer signal path.",
                "Check whether other devices are saturating the connection.",
                "Contact the ISP if slow download speeds persist across multiple tests.",
            ]
        )
        severity_score += 2
    elif download < 60:
        issues.append("Download speed is usable, but it has room for improvement.")
        recommendations.append("Try testing closer to the router to compare WiFi quality.")
        severity_score += 1

    if upload < 10:
        issues.append("Upload speed is low and may affect video calls, backups, or cloud sync.")
        recommendations.extend(
            [
                "Pause simultaneous uploads such as backups or file sync tasks.",
                "Prefer the 5 GHz band if you are close to the router.",
            ]
        )
        severity_score += 2
    elif upload < 20:
        issues.append("Upload speed is moderate but may slow down during shared usage.")
        recommendations.append("Reduce simultaneous uploads if meetings or gaming feel unstable.")
        severity_score += 1

    if not issues:
        status = "healthy"
        summary = "Your network looks healthy right now with stable overall performance."
        recommendations = [
            "Keep the router in an open location to maintain signal quality.",
            "Continue periodic tests to catch changes early.",
        ]
    elif severity_score >= 4:
        status = "attention"
        summary = "Your network may need attention because multiple metrics are below target."
    else:
        status = "watch"
        summary = "Your network is usable, but a few signals suggest optimization is worth trying."

    unique_recommendations = []
    for item in recommendations:
        if item not in unique_recommendations:
            unique_recommendations.append(item)

    return {
        "status": status,
        "issue_summary": summary,
        "issues": issues,
        "recommendations": unique_recommendations,
    }


def generate_chat_response(message, metrics):
    """Respond to common network questions using the latest metrics."""
    cleaned = (message or "").strip()
    normalized = cleaned.lower()

    recommendation = generate_ai_recommendation(metrics)
    download = _to_float(metrics.get("download"))
    upload = _to_float(metrics.get("upload"))
    ping = _to_float(metrics.get("ping"))
    timestamp = metrics.get("timestamp", "the latest saved snapshot")

    if not cleaned:
        response = "Ask about your network health, ping, speed, or how to improve performance."
    elif "download" in normalized and "speed" in normalized:
        response = f"Your current download speed is {download:.2f} Mbps based on the reading saved at {timestamp}."
    elif "upload" in normalized and "speed" in normalized:
        response = f"Your current upload speed is {upload:.2f} Mbps based on the reading saved at {timestamp}."
    elif "ping" in normalized and ("why" in normalized or "high" in normalized):
        if ping >= 80:
            response = (
                f"Your ping is {ping:.2f} ms, which is high. That usually points to congestion, distance from the router, "
                "or interference. Try reducing background usage and moving closer to the router."
            )
        elif ping >= 40:
            response = (
                f"Your ping is {ping:.2f} ms, which is slightly elevated. It may improve if you reduce competing traffic "
                "or test from a stronger WiFi location."
            )
        else:
            response = f"Your ping is {ping:.2f} ms, which looks healthy right now."
    elif "improve" in normalized or "improve speed" in normalized or "faster" in normalized:
        response = "Here are the best next steps: " + " ".join(recommendation["recommendations"][:3])
    elif "how is my network" in normalized or "network" in normalized or "health" in normalized:
        response = (
            f"Network status: {recommendation['status']}. {recommendation['issue_summary']} "
            f"Current metrics are {download:.2f} Mbps down, {upload:.2f} Mbps up, and {ping:.2f} ms ping."
        )
    else:
        response = (
            f"I can help with network health, ping, download speed, upload speed, and improvement tips. "
            f"Right now I see {download:.2f} Mbps down, {upload:.2f} Mbps up, and {ping:.2f} ms ping."
        )

    return {
        "message": cleaned,
        "reply": response,
        "metrics_timestamp": timestamp,
        "recommendation": recommendation,
    }
