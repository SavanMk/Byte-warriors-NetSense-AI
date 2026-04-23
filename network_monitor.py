import json
import time
import urllib.error

import speedtest


def run_monitor(output_file=None):
    """Run a real network speed test and optionally persist the latest snapshot."""
    print('Running real speed test...')
    st = None

    for secure_mode in (False, True):
        try:
            st = speedtest.Speedtest(secure=secure_mode)
            st.get_best_server()
            if secure_mode:
                print('Using secure HTTPS mode for speedtest')
            break
        except urllib.error.HTTPError as err:
            if err.code == 403 and not secure_mode:
                print('403 Forbidden detected, retrying with secure=True')
                continue
            raise
        except Exception as err:
            if secure_mode:
                raise
            print(f'Initial speedtest attempt failed: {err}. Retrying with secure=True')
            continue

    if st is None:
        raise RuntimeError('Unable to initialize Speedtest client')

    download = st.download() / 1_000_000
    upload = st.upload() / 1_000_000
    ping = st.results.ping

    data = {
        'ping': round(ping, 2),
        'download': round(download, 2),
        'upload': round(upload, 2),
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
    }

    if output_file:
        with open(output_file, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2)

    print('Real metrics collected')
    return data
