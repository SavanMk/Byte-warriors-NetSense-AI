import subprocess
import platform
import speedtest

def run_ping(host="8.8.8.8"):
    """
    Runs a basic ping test to a reliable public DNS server (Google).
    Adjusts the ping command based on the operating system.
    """
    print(f"[*] Pinging {host}...")
    
    # Windows uses '-n' for packet count, Linux/Mac uses '-c'
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    command = ['ping', param, '4', host]

    try:
        # Run the command and capture the output
        output = subprocess.check_output(command, universal_newlines=True)
        print("--- Ping Results ---\n", output.strip())
        return True
    except subprocess.CalledProcessError as e:
        print("[-] Ping failed:\n", e.output)
        return False

def run_speed_test():
    """
    Runs a download and upload speed test using speedtest-cli.
    """
    print("[*] Finding best server and running speed test... (This may take a minute)")
    try:
        st = speedtest.Speedtest()
        st.get_best_server()

        # Speeds are returned in bits per second, convert to Megabits per second (Mbps)
        download_speed = st.download() / 1_000_000 
        upload_speed = st.upload() / 1_000_000 
        ping_latency = st.results.ping

        print("--- Speed Test Results ---")
        print(f"Download: {download_speed:.2f} Mbps")
        print(f"Upload:   {upload_speed:.2f} Mbps")
        print(f"Latency:  {ping_latency} ms")
        return True
    except Exception as e:
        print(f"[-] Speed test failed: {e}")
        return False

if __name__ == "__main__":
    print("="*40)
    print(" NetSense AI: Network Monitor Started")
    print("="*40)
    
    # Run independent tests
    run_ping()
    print("\n" + "-"*40 + "\n")
    run_speed_test()
    
    print("\n========================================")
    print(" Monitoring Complete")
    print("========================================")