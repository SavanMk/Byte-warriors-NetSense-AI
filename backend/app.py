# app.py
from flask import Flask, jsonify, render_template, request
import json
import os
import threading
import time

from ai_engine import generate_ai_recommendation, generate_chat_response
from network_monitor import run_monitor

app = Flask(
    __name__,
    template_folder='../frontend/templates',
    static_folder='../frontend/static'
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'data.json')
monitor_lock = threading.Lock()
refresh_event = threading.Event()
monitor_state = {
    "last_run_started": None,
    "last_run_finished": None,
    "last_error": None,
}


def load_metrics():
    if not os.path.exists(DATA_FILE):
        return None

    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def run_monitor_cycle():
    with monitor_lock:
        monitor_state["last_run_started"] = time.time()
        monitor_state["last_error"] = None

        try:
            run_monitor(DATA_FILE)
        except Exception as exc:
            monitor_state["last_error"] = str(exc)
            raise
        finally:
            monitor_state["last_run_finished"] = time.time()


def background_monitor():
    refresh_event.set()

    while True:
        refresh_event.wait(timeout=45)
        refresh_event.clear()

        try:
            run_monitor_cycle()
        except Exception as exc:
            print("Error in background speed test:", exc)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/metrics', methods=['GET'])
def get_metrics():
    # Serve the latest saved metrics while the background worker keeps the cache fresh.
    data = load_metrics()

    if data is None:
        return jsonify({"error": "No data yet, please wait..."}), 404

    payload = {
        **data,
        "ai_recommendation": generate_ai_recommendation(data),
        "running": monitor_lock.locked(),
        "last_error": monitor_state["last_error"],
    }
    return jsonify(payload)


@app.route('/trigger-performance', methods=['POST'])
def trigger_performance():
    data = load_metrics()
    refresh_event.set()

    if data is None:
        return jsonify({
            "status": "warming_up",
            "message": "Preparing your first network snapshot.",
            "running": monitor_lock.locked(),
            "recommendation": {
                "status": "warming_up",
                "issue_summary": "The AI engine is waiting for the first saved metrics snapshot.",
                "issues": [],
                "recommendations": ["Keep the dashboard open and the latest saved result will appear after the first test completes."],
            },
        }), 202

    return jsonify({
        "status": "queued",
        "message": "Showing the latest saved result while a fresh test runs in the background.",
        "running": monitor_lock.locked(),
        "data": {
            **data,
            "ai_recommendation": generate_ai_recommendation(data),
        },
    })


@app.route('/chat', methods=['POST'])
def chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "")
    metrics = load_metrics()

    if metrics is None:
        return jsonify({
            "reply": "I do not have a saved network snapshot yet. Run Test Performance first and I will analyze it.",
            "recommendation": {
                "status": "warming_up",
                "issue_summary": "The analyzer is waiting for the first saved metrics snapshot.",
                "issues": [],
                "recommendations": ["Press Test Performance to load the latest saved result."],
            },
        }), 200

    response = generate_chat_response(message, metrics)
    return jsonify(response)


def start_background_thread():
    thread = threading.Thread(target=background_monitor, daemon=True)
    thread.start()


if __name__ == '__main__':
    print("🚀 Backend running...")
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_background_thread()

    app.run(debug=True, port=5000)
