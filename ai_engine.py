"""Rule-based AI helpers for NetSense AI recommendations and chatbot replies."""

from __future__ import annotations


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _health_score(metrics):
    download = _to_float(metrics.get("download"))
    upload = _to_float(metrics.get("upload"))
    ping = _to_float(metrics.get("ping"))

    throughput_score = min(download / 250.0, 1.0) * 40.0
    upload_score = min(upload / 100.0, 1.0) * 25.0

    if ping <= 5:
        latency_score = 35.0
    elif ping <= 15:
        latency_score = 35.0 - ((ping - 5.0) / 10.0) * 8.0
    elif ping <= 30:
        latency_score = 27.0 - ((ping - 15.0) / 15.0) * 9.0
    elif ping <= 60:
        latency_score = 18.0 - ((ping - 30.0) / 30.0) * 10.0
    elif ping <= 120:
        latency_score = 8.0 - ((ping - 60.0) / 60.0) * 6.0
    else:
        latency_score = max(0.0, 2.0 - ((ping - 120.0) / 80.0) * 2.0)

    penalty = 0.0
    if download < 25:
        penalty += 14.0
    elif download < 50:
        penalty += 7.0

    if upload < 10:
        penalty += 12.0
    elif upload < 20:
        penalty += 6.0

    if ping > 100:
        penalty += 14.0
    elif ping > 60:
        penalty += 7.0

    return int(max(0, min(100, round(throughput_score + upload_score + latency_score - penalty))))


def generate_ai_recommendation(metrics):
    """Analyze current metrics and return a recommendation payload."""
    download = _to_float(metrics.get("download"))
    upload = _to_float(metrics.get("upload"))
    ping = _to_float(metrics.get("ping"))
    score = _health_score(metrics)

    issues = []
    recommendations = []

    if ping >= 100:
        issues.append("Ping is very high, so gaming, calls, and browsing may feel delayed.")
        recommendations.extend(
            [
                "Reduce background traffic on the network before testing again.",
                "Move closer to the router or switch to Ethernet for latency-sensitive work.",
                "Restart the router if high latency continues across several tests.",
            ]
        )
    elif ping >= 60:
        issues.append("Ping is elevated, so responsiveness may dip during busy periods.")
        recommendations.append("Limit competing traffic when low latency matters.")

    if download < 25:
        issues.append("Download speed is weak for streaming, larger downloads, or multi-device use.")
        recommendations.extend(
            [
                "Check whether other devices are saturating the connection.",
                "Test from a stronger WiFi position or closer to the router.",
                "Contact the ISP if low download speed persists across multiple fresh tests.",
            ]
        )
    elif download < 75:
        issues.append("Download speed is usable, but it has room for improvement.")
        recommendations.append("Compare WiFi performance from another room or band to find signal loss.")

    if upload < 10:
        issues.append("Upload speed is low and may affect video calls, backups, or cloud sync.")
        recommendations.extend(
            [
                "Pause large uploads or sync jobs on other devices.",
                "Prefer a stronger WiFi location or 5 GHz band if you are nearby.",
            ]
        )
    elif upload < 20:
        issues.append("Upload speed is moderate and may dip during shared usage.")
        recommendations.append("Reduce simultaneous uploads if meetings or gaming feel unstable.")

    if score >= 90:
        status = "healthy"
        summary = "Your network looks strong right now with high throughput and low latency."
        if not recommendations:
            recommendations = [
                "Keep the router in an open location to maintain signal quality.",
                "Run another fresh test when the network is busy to compare results.",
            ]
    elif score >= 70:
        status = "watch"
        summary = "Your network is usable, but one or more metrics could be improved."
    else:
        status = "attention"
        summary = "Your network may need attention because multiple metrics are below target."

    unique_recommendations = []
    for item in recommendations:
        if item not in unique_recommendations:
            unique_recommendations.append(item)

    return {
        "status": status,
        "issue_summary": summary,
        "issues": issues,
        "recommendations": unique_recommendations,
        "health_score": score,
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
