import json
import time
import urllib.error

import speedtest


def _log_monitor(message):
    print(f"[NetSense][monitor] {message}", flush=True)


def _utc_timestamp(epoch_seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_seconds))


def _persist_snapshot(output_file, payload):
    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def run_monitor(output_file=None):
    """Run a real network speed test and optionally persist the latest snapshot."""
    started_at = time.time()
    run_id = str(time.time_ns())
    _log_monitor(f"Running new speed test... run_id={run_id}")

    st = None
    selected_server = None

    for secure_mode in (False, True):
        try:
            st = speedtest.Speedtest(secure=secure_mode)
            selected_server = st.get_best_server()
            if secure_mode:
                _log_monitor("Using secure HTTPS mode for speedtest")
            break
        except urllib.error.HTTPError as err:
            if err.code == 403 and not secure_mode:
                _log_monitor("403 Forbidden detected, retrying with secure=True")
                continue
            raise
        except Exception as err:
            if secure_mode:
                raise
            _log_monitor(f"Initial speedtest attempt failed: {err}. Retrying with secure=True")
            continue

    if st is None:
        raise RuntimeError("Unable to initialize Speedtest client")

    download = st.download() / 1_000_000
    upload = st.upload() / 1_000_000
    ping = st.results.ping
    finished_at = time.time()

    data = {
        "test_run_id": run_id,
        "ping": round(ping, 2),
        "download": round(download, 2),
        "upload": round(upload, 2),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(finished_at)),
        "captured_at_epoch": round(finished_at, 3),
        "captured_at_utc": _utc_timestamp(finished_at),
        "test_started_at_epoch": round(started_at, 3),
        "test_finished_at_epoch": round(finished_at, 3),
        "test_duration_seconds": round(finished_at - started_at, 2),
        "server_name": (selected_server or {}).get("name"),
        "server_country": (selected_server or {}).get("country"),
        "server_sponsor": (selected_server or {}).get("sponsor"),
    }

    _log_monitor(
        "Real metrics collected "
        f"run_id={run_id} down={data['download']}Mbps up={data['upload']}Mbps "
        f"ping={data['ping']}ms duration={data['test_duration_seconds']}s"
    )

    if output_file:
        _log_monitor(f"Saving fresh metrics to {output_file}")
        _persist_snapshot(output_file, data)

    _log_monitor(f"Timestamp of last update: {data['timestamp']}")
    return data
