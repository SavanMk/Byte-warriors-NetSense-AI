import json
import os
import threading
import time
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

try:
    from google import genai
except ImportError:
    genai = None

from ai_engine import generate_ai_recommendation
from network_monitor import run_monitor

app = Flask(
    __name__,
    template_folder='../frontend/templates',
    static_folder='../frontend/static'
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'data.json')
HISTORY_FILE = os.path.join(BASE_DIR, 'history.json')
MAX_HISTORY_ITEMS = 10
CACHE_FRESH_WINDOW_SECONDS = int(os.getenv('CACHE_FRESH_WINDOW_SECONDS', '300'))
GEMINI_DEFAULT_MODEL = 'gemini-2.5-flash'
GEMINI_FALLBACK_DEFAULT_MODEL = 'gemini-2.5-flash-lite'

monitor_lock = threading.Lock()
monitor_state = {
    'status': 'idle',
    'last_run_started': None,
    'last_run_finished': None,
    'last_error': None,
    'last_trigger': None,
    'last_completed_timestamp': None,
    'last_completed_source': None,
    'last_refresh_requested_at': None,
    'last_manual_request_at': None,
    'cached_available': False,
    'completed_runs': 0,
    'scheduler_enabled': False,
}

load_dotenv(os.path.join(BASE_DIR, '.env'))
load_dotenv(os.path.join(os.path.dirname(BASE_DIR), '.env'))


class MonitorAlreadyRunning(Exception):
    """Raised when a new metrics run is requested while one is already active."""


def _log_netsense(message: str) -> None:
    print(f'[NetSense] {message}', flush=True)


def _load_local_env_value(key: str) -> str | None:
    env_files = [
        os.path.join(BASE_DIR, '.env'),
        os.path.join(os.path.dirname(BASE_DIR), '.env'),
    ]

    for env_file in env_files:
        if not os.path.exists(env_file):
            continue

        try:
            with open(env_file, 'r', encoding='utf-8') as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue

                    name, value = line.split('=', 1)
                    if name.strip() == key:
                        return value.strip().strip('"\'')
        except OSError:
            continue

    return None


def _get_setting(key: str, default: str | None = None) -> str | None:
    return os.getenv(key) or _load_local_env_value(key) or default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: str, default: Any):
    if not os.path.exists(path):
        return default

    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: str, payload: Any) -> None:
    temp_path = f'{path}.tmp'
    with open(temp_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp_path, path)


def no_store_json(payload: Any, status: int = 200):
    response = jsonify(payload)
    response.status_code = status
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def load_metrics() -> dict[str, Any] | None:
    data = _read_json(DATA_FILE, None)
    return data if isinstance(data, dict) else None


def load_history() -> list[dict[str, Any]]:
    history = _read_json(HISTORY_FILE, [])
    return history if isinstance(history, list) else []


def _serialize_suggestions(suggestions: list[str]) -> str:
    return json.dumps(suggestions or [], ensure_ascii=True)


def calculate_health_score(metrics: dict[str, Any]) -> dict[str, Any]:
    download = _to_float(metrics.get('download'))
    upload = _to_float(metrics.get('upload'))
    ping = _to_float(metrics.get('ping'))

    throughput_component = min(download / 250.0, 1.0) * 40.0
    upload_component = min(upload / 100.0, 1.0) * 25.0

    if ping <= 5:
        latency_component = 35.0
    elif ping <= 15:
        latency_component = 35.0 - ((ping - 5.0) / 10.0) * 8.0
    elif ping <= 30:
        latency_component = 27.0 - ((ping - 15.0) / 15.0) * 9.0
    elif ping <= 60:
        latency_component = 18.0 - ((ping - 30.0) / 30.0) * 10.0
    elif ping <= 120:
        latency_component = 8.0 - ((ping - 60.0) / 60.0) * 6.0
    else:
        latency_component = max(0.0, 2.0 - ((ping - 120.0) / 80.0) * 2.0)

    penalties: list[dict[str, Any]] = []
    penalty_total = 0.0

    if download < 25:
        penalties.append({'metric': 'download', 'reason': 'download_below_25', 'value': 14})
        penalty_total += 14.0
    elif download < 50:
        penalties.append({'metric': 'download', 'reason': 'download_below_50', 'value': 7})
        penalty_total += 7.0

    if upload < 10:
        penalties.append({'metric': 'upload', 'reason': 'upload_below_10', 'value': 12})
        penalty_total += 12.0
    elif upload < 20:
        penalties.append({'metric': 'upload', 'reason': 'upload_below_20', 'value': 6})
        penalty_total += 6.0

    if ping > 100:
        penalties.append({'metric': 'ping', 'reason': 'ping_above_100', 'value': 14})
        penalty_total += 14.0
    elif ping > 60:
        penalties.append({'metric': 'ping', 'reason': 'ping_above_60', 'value': 7})
        penalty_total += 7.0

    score = int(max(0, min(100, round(throughput_component + upload_component + latency_component - penalty_total))))

    if score >= 85:
        label = 'Excellent'
        accent = 'mint'
    elif score >= 65:
        label = 'Good'
        accent = 'blue'
    elif score >= 45:
        label = 'Fair'
        accent = 'gold'
    else:
        label = 'Poor'
        accent = 'rose'

    return {
        'score': score,
        'label': label,
        'accent': accent,
        'components': {
            'download': round(throughput_component, 2),
            'upload': round(upload_component, 2),
            'ping': round(latency_component, 2),
            'penalty_total': round(penalty_total, 2),
        },
        'penalties': penalties,
    }


def detect_network_flags(metrics: dict[str, Any], recommendation: dict[str, Any]) -> dict[str, Any]:
    ping = _to_float(metrics.get('ping'))
    download = _to_float(metrics.get('download'))
    upload = _to_float(metrics.get('upload'))

    issue_detected = ping >= 70 or download < 30 or upload < 10
    alert_level = 'clear'
    if ping >= 100 or download < 15 or upload < 5:
        alert_level = 'critical'
    elif issue_detected:
        alert_level = 'warning'

    headline = 'Network looks stable.'
    if alert_level == 'critical':
        headline = 'Your WiFi needs attention before demanding tasks.'
    elif alert_level == 'warning':
        headline = 'A few metrics suggest your WiFi can be improved.'

    return {
        'issue_detected': issue_detected,
        'alert_level': alert_level,
        'headline': headline,
        'status': recommendation.get('status', 'unknown'),
    }


def build_metrics_payload(metrics: dict[str, Any] | None) -> dict[str, Any] | None:
    if metrics is None:
        return None

    recommendation = generate_ai_recommendation(metrics)
    health = calculate_health_score(metrics)
    flags = detect_network_flags(metrics, recommendation)
    snapshot_age_seconds = _snapshot_age_seconds(metrics)
    source = _snapshot_source(metrics, fallback='cached')

    return {
        **metrics,
        'ai_recommendation': recommendation,
        'health_score': health,
        'alerts': flags,
        'running': monitor_lock.locked(),
        'status': monitor_state['status'],
        'source': source,
        'last_error': monitor_state['last_error'],
        'snapshot_age_seconds': round(snapshot_age_seconds, 2) if snapshot_age_seconds is not None else None,
        'stale': source == 'cached',
        'last_update_timestamp': metrics.get('timestamp'),
        'last_update_epoch': metrics.get('captured_at_epoch'),
    }


def _snapshot_age_seconds(metrics: dict[str, Any] | None) -> float | None:
    if not metrics:
        return None

    timestamp = metrics.get('timestamp')
    if not timestamp:
        return None

    try:
        parsed = time.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        return max(0.0, time.time() - time.mktime(parsed))
    except (TypeError, ValueError):
        return None


def _snapshot_source(metrics: dict[str, Any] | None, fallback: str = 'cached') -> str:
    if metrics is None:
        return fallback

    if monitor_lock.locked():
        return 'in_progress_fallback'

    age_seconds = _snapshot_age_seconds(metrics)
    if age_seconds is not None and age_seconds <= CACHE_FRESH_WINDOW_SECONDS:
        return 'fresh'

    return fallback


def save_snapshot(snapshot: dict[str, Any]) -> None:
    _log_netsense(
        f"Saving fresh metrics... run_id={snapshot.get('test_run_id')} timestamp={snapshot.get('timestamp')}"
    )
    _write_json(DATA_FILE, snapshot)

    history = load_history()
    history.insert(0, snapshot)
    history = history[:MAX_HISTORY_ITEMS]
    _write_json(HISTORY_FILE, history)
    _log_netsense(f"Timestamp of last update: {snapshot.get('timestamp')}")


def _log_served_snapshot(route_name: str, metrics: dict[str, Any] | None) -> None:
    if metrics is None:
        _log_netsense(f'{route_name}: no metrics snapshot is available yet.')
        return

    age_seconds = _snapshot_age_seconds(metrics)
    source = _snapshot_source(metrics, fallback='cached')
    age_label = 'unknown' if age_seconds is None else f'{age_seconds:.2f}s'
    message = 'Serving cached data (if any)' if source != 'fresh' else 'Serving fresh data'
    _log_netsense(
        f'{route_name}: {message}. run_id={metrics.get("test_run_id")} '
        f'timestamp={metrics.get("timestamp")} age={age_label} source={source}'
    )


def build_chat_prompt(user_message: str, metrics_payload: dict[str, Any]) -> str:
    recommendation = metrics_payload.get('ai_recommendation', {})
    health = metrics_payload.get('health_score', {})
    alerts = metrics_payload.get('alerts', {})

    return (
        'You are a network assistant.\n\n'
        f'User question: {user_message.strip()}\n\n'
        'Network stats:\n'
        f"- Download: {_to_float(metrics_payload.get('download')):.2f} Mbps\n"
        f"- Upload: {_to_float(metrics_payload.get('upload')):.2f} Mbps\n"
        f"- Ping: {_to_float(metrics_payload.get('ping')):.2f} ms\n"
        f"- Health score: {health.get('score', 0)}/100 ({health.get('label', 'Unknown')})\n\n"
        'AI analysis:\n'
        f"- Status: {recommendation.get('status', 'unknown')}\n"
        f"- Suggestions: {_serialize_suggestions(recommendation.get('recommendations', []))}\n"
        f"- Alert level: {alerts.get('alert_level', 'clear')}\n\n"
        'Answer the user question clearly based on the network condition.\n'
        'Focus on whether the user can do what they asked, given the current WiFi quality.\n\n'
        'Rules:\n'
        '- Answer in maximum 4 lines\n'
        '- Be direct and helpful\n'
        '- Do not repeat all metrics unnecessarily\n'
        '- Give yes/no when applicable (like streaming, gaming)\n'
        '- Provide short explanation'
    )


def _gemini_error_message(exc: Exception) -> str:
    parts = [exc.__class__.__name__]
    message = str(exc).strip()
    if message:
        parts.append(message)

    status_code = getattr(exc, 'status_code', None)
    if status_code:
        parts.append(f'status={status_code}')

    response = getattr(exc, 'response', None)
    if response:
        parts.append(str(response))

    return ' | '.join(parts)


def _candidate_models() -> list[str]:
    primary_model = _get_setting('GEMINI_MODEL', GEMINI_DEFAULT_MODEL)
    fallback_model = _get_setting('GEMINI_FALLBACK_MODEL', GEMINI_FALLBACK_DEFAULT_MODEL)

    models = [primary_model]
    if fallback_model and fallback_model not in models:
        models.append(fallback_model)

    return models


def generate_chat_reply(user_message: str, metrics_payload: dict[str, Any]) -> str:
    if genai is None:
        raise RuntimeError("Gemini SDK is not installed. Install the 'google-genai' package first.")

    api_key = _get_setting('GEMINI_API_KEY')
    if not api_key:
        raise RuntimeError('Missing GEMINI_API_KEY in environment or backend/.env.')

    prompt = build_chat_prompt(user_message, metrics_payload)
    client = genai.Client(api_key=api_key)
    last_error = None

    for model in _candidate_models():
        for attempt in range(2):
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                reply = (getattr(response, 'text', '') or '').strip()
                if not reply:
                    raise RuntimeError(f"Gemini returned an empty response for model '{model}'.")
                return reply
            except Exception as exc:  # pragma: no cover - network/provider path
                last_error = _gemini_error_message(exc)
                retryable = '503' in last_error or 'UNAVAILABLE' in last_error.upper()
                if retryable and attempt == 0:
                    time.sleep(1.5)
                    continue
                break

    raise RuntimeError(last_error or 'Gemini request failed for all configured models.')


def run_monitor_cycle(trigger_source: str = 'scheduled') -> dict[str, Any]:
    if not monitor_lock.acquire(blocking=False):
        raise MonitorAlreadyRunning()

    _log_netsense(f'Starting speed test ({trigger_source})')
    monitor_state['status'] = 'running'
    monitor_state['last_run_started'] = time.time()
    monitor_state['last_error'] = None
    monitor_state['last_trigger'] = trigger_source
    monitor_state['last_refresh_requested_at'] = time.time()

    try:
        snapshot = run_monitor()
        save_snapshot(snapshot)
        persisted_snapshot = load_metrics()
        monitor_state['status'] = 'ready'
        monitor_state['last_completed_timestamp'] = snapshot.get('timestamp')
        monitor_state['last_completed_source'] = 'fresh'
        monitor_state['cached_available'] = True
        monitor_state['completed_runs'] += 1
        if persisted_snapshot and persisted_snapshot.get('test_run_id') == snapshot.get('test_run_id'):
            _log_netsense(
                f'data.json refresh confirmed for run_id={snapshot.get("test_run_id")} '
                f'timestamp={persisted_snapshot.get("timestamp")}'
            )
        else:
            _log_netsense('Warning: data.json verification could not confirm the latest run.')
        _log_netsense(f'Speed test completed: {snapshot}')
        return snapshot
    except Exception as exc:
        monitor_state['status'] = 'failed'
        monitor_state['last_error'] = str(exc)
        _log_netsense(f'Speed test failed: {exc}')
        raise
    finally:
        monitor_state['last_run_finished'] = time.time()
        monitor_lock.release()


def metrics_status_payload() -> dict[str, Any]:
    latest = load_metrics()
    cached_available = latest is not None
    source = _snapshot_source(latest, fallback='cached' if cached_available else 'unavailable')

    if monitor_lock.locked() or monitor_state['status'] == 'running':
        status = 'running'
    elif cached_available:
        status = 'ready'
    elif monitor_state['last_error']:
        status = 'failed'
    else:
        status = monitor_state['status']

    return {
        'status': status,
        'running': monitor_lock.locked(),
        'ready': cached_available,
        'cached_available': cached_available,
        'last_updated': latest.get('timestamp') if latest else None,
        'last_error': monitor_state['last_error'],
        'last_trigger': monitor_state['last_trigger'],
        'source': source,
        'stale': source == 'cached',
        'last_run_started': monitor_state['last_run_started'],
        'last_run_finished': monitor_state['last_run_finished'],
        'cache_fresh_window_seconds': CACHE_FRESH_WINDOW_SECONDS,
        'completed_runs': monitor_state['completed_runs'],
        'scheduler_enabled': monitor_state['scheduler_enabled'],
    }


def build_fix_plan(metrics_payload: dict[str, Any] | None) -> dict[str, Any]:
    alerts = (metrics_payload or {}).get('alerts', {})
    recommendation = (metrics_payload or {}).get('ai_recommendation', {})
    issue_detected = alerts.get('issue_detected', False)

    actions = [
        'Applied DNS optimization profile suggestion.',
        'Prepared a safe network reset checklist for the user.',
    ]

    if metrics_payload is None:
        return {
            'success': True,
            'issue_detected': False,
            'action_taken': 'Prepared startup network guidance',
            'message': 'Network optimization simulation completed successfully.',
            'improvement_message': 'A live fix plan will become more precise after the first test completes. For now, start with a router restart, reconnect WiFi, and keep one heavy download paused.',
            'next_steps': [
                'Run Test Performance once to capture your current network snapshot.',
                'Move closer to the router and avoid crowded 2.4 GHz channels if possible.',
                'Retry the fix workflow after the first test to get metric-aware guidance.',
            ],
            'actions': actions,
        }

    if issue_detected:
        message = 'Suggested a DNS refresh and router restart workflow to stabilize WiFi performance.'
    else:
        message = 'No severe issue detected, so the assistant suggested light optimization only.'

    return {
        'success': True,
        'issue_detected': issue_detected,
        'action_taken': 'Simulated network optimization guidance',
        'message': 'Network optimization simulation completed successfully.',
        'improvement_message': message,
        'next_steps': recommendation.get('recommendations', [])[:3],
        'actions': actions,
    }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/healthz')
def healthz():
    return jsonify({
        'status': 'ok',
        'service': 'netsense-ai',
    })


@app.route('/metrics', methods=['GET'])
def get_metrics():
    latest = load_metrics()
    _log_served_snapshot('/metrics', latest)
    payload = build_metrics_payload(latest)
    if payload is None:
        return no_store_json({'error': 'No data yet, please wait...'}, 404)
    return no_store_json(payload)


@app.route('/metrics/latest', methods=['GET'])
def get_latest_metrics():
    latest = load_metrics()
    _log_served_snapshot('/metrics/latest', latest)
    payload = build_metrics_payload(latest)
    if payload is None:
        return no_store_json({'error': 'No cached metrics are available yet.'}, 404)
    payload['source'] = _snapshot_source(latest, fallback='cached')
    payload['status'] = metrics_status_payload()['status']
    return no_store_json(payload)


@app.route('/metrics/status', methods=['GET'])
def get_metrics_status():
    latest = load_metrics()
    _log_served_snapshot('/metrics/status', latest)
    return no_store_json(metrics_status_payload())


@app.route('/metrics/history', methods=['GET'])
def get_metrics_history():
    history = [build_metrics_payload(item) for item in load_history()]
    return no_store_json({'items': [item for item in history if item is not None]})


@app.route('/metrics/prefetch', methods=['POST'])
def prefetch_metrics():
    status_payload = metrics_status_payload()
    status_payload['queued'] = False
    status_payload['message'] = 'Prefetch is disabled. Tests run when the user clicks Test Performance.'
    return no_store_json(status_payload, 202)


@app.route('/trigger-performance', methods=['POST'])
def trigger_performance():
    monitor_state['last_manual_request_at'] = time.time()
    monitor_state['last_refresh_requested_at'] = time.time()
    monitor_state['last_trigger'] = 'manual_button'

    if monitor_lock.locked():
        return no_store_json({
            'status': 'running',
            'queued': False,
            'running': True,
            'cached_available': load_metrics() is not None,
            'source': 'in_progress_fallback',
            'message': 'A speed test is already running. Please wait for it to finish.',
        }), 409

    try:
        snapshot = run_monitor_cycle(trigger_source='manual_button')
        payload = build_metrics_payload(snapshot)
        payload['source'] = 'fresh'
        payload['status'] = 'ready'
    except Exception as exc:
        return no_store_json({
            'status': 'failed',
            'running': False,
            'cached_available': load_metrics() is not None,
            'source': 'manual_test_failed',
            'error': str(exc),
            'message': 'Manual speed test failed. Please try again.',
        }, 500)

    return no_store_json({
        'status': 'ready',
        'queued': False,
        'running': False,
        'cached_available': True,
        'source': 'fresh',
        'message': 'Fresh speed test completed.',
        'data': payload,
    })


@app.route('/fix-network', methods=['POST'])
def fix_network():
    try:
        print('[NetSense] POST /fix-network received')
        payload = build_metrics_payload(load_metrics())
        response = build_fix_plan(payload)
        print('[NetSense] /fix-network response:', response)
        return jsonify(response)
    except Exception as exc:
        print('[NetSense] /fix-network error:', exc)
        return jsonify({
            'success': False,
            'message': 'Network optimization simulation failed.',
            'error': str(exc),
        }), 500


@app.route('/chat', methods=['POST'])
def chat():
    payload = request.get_json(silent=True) or {}
    message = (payload.get('message') or '').strip()

    if not message:
        return jsonify({'error': 'Message is required.'}), 400

    metrics_payload = build_metrics_payload(load_metrics())
    if metrics_payload is None:
        return jsonify({'error': 'No saved network snapshot is available yet.'}), 404

    try:
        reply = generate_chat_reply(message, metrics_payload)
    except RuntimeError as exc:
        return jsonify({
            'error': 'Gemini AI request failed.',
            'details': str(exc),
        }), 502

    return jsonify({
        'message': message,
        'reply': reply,
        'metrics_timestamp': metrics_payload.get('timestamp', 'the latest saved snapshot'),
        'recommendation': metrics_payload.get('ai_recommendation'),
        'health_score': metrics_payload.get('health_score'),
        'alerts': metrics_payload.get('alerts'),
    })


if __name__ == '__main__':
    print('NetSense AI backend running...')
    app.run(debug=True, port=5000)
