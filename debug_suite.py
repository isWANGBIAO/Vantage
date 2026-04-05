import os
import subprocess
import sys
import time

import psutil
import requests


SERVER_PORT = 8000
BASE_URL = f"http://localhost:{SERVER_PORT}"
SERVER_SCRIPT = "src/server.py"
LOG_FILE = "logs/debug_server.log"
WAIT_FOR_SERVER_TIMEOUT_SECONDS = 60


def console_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_args = [
            str(arg).encode(encoding, errors="replace").decode(encoding)
            for arg in args
        ]
        print(*safe_args, **kwargs)


def is_port_in_use(port):
    for conn in psutil.net_connections():
        if conn.laddr.port == port:
            return True
    return False


def start_server():
    console_print("Starting dashboard backend for debugging...")
    if not os.path.exists("logs"):
        os.makedirs("logs")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    process = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        stdout=open(LOG_FILE, "w"),
        stderr=subprocess.STDOUT,
        env=env,
        cwd=os.getcwd(),
    )
    return process


def wait_for_server(timeout=WAIT_FOR_SERVER_TIMEOUT_SECONDS):
    start = time.time()
    while time.time() - start < timeout:
        try:
            requests.get(f"{BASE_URL}/api/status", timeout=1)
            console_print("Backend is READY.")
            return True
        except requests.exceptions.ConnectionError:
            time.sleep(1)
            console_print(".", end="", flush=True)
    console_print("\nBackend failed to start within timeout.")
    return False


def test_api(name, path, method="GET", expected_code=200):
    console_print(f"\nTesting {name} [{path}]...")
    try:
        url = f"{BASE_URL}{path}"
        if method == "GET":
            res = requests.get(url)
        else:
            res = requests.post(url)

        if res.status_code == expected_code:
            console_print(f"   OK ({res.status_code})")
            if "json" in res.headers.get("Content-Type", ""):
                data = res.json()
                if isinstance(data, dict):
                    keys = list(data.keys())
                    console_print(f"   Response Keys: {keys}")
                    if "content" in data:
                        console_print(
                            f"   Content Preview: {data['content'][:50]}..."
                            if data["content"]
                            else "   Content: (Empty)"
                        )
                    if "logs" in data:
                        console_print(f"   Logs Count: {len(data['logs'])}")
                        if data["logs"]:
                            console_print(f"   Last Log: {data['logs'][-1].strip()}")
                elif isinstance(data, list):
                    console_print(f"   List Length: {len(data)}")
            return True

        console_print(f"   Failed: Status {res.status_code}")
        return False
    except Exception as e:
        console_print(f"   Error: {e}")
        return False


def main():
    server_process = None
    existing_server = False

    if is_port_in_use(SERVER_PORT):
        console_print("Port 8000 is already in use. Assuming user's server is running.")
        existing_server = True
        if not wait_for_server(timeout=WAIT_FOR_SERVER_TIMEOUT_SECONDS):
            console_print("Port is used but /api/status is not responding. Aborting.")
            return
    else:
        server_process = start_server()
        if not wait_for_server(timeout=WAIT_FOR_SERVER_TIMEOUT_SECONDS):
            server_process.terminate()
            return

    try:
        results = []
        results.append(test_api("System Status", "/api/status"))
        results.append(test_api("System Stats (CPU/Mem)", "/api/sys_stats"))
        results.append(test_api("Action Plan History", "/api/action_plan_content"))
        results.append(test_api("System Logs", "/api/system_logs"))

        console_print("\n" + "=" * 40)
        console_print(f"Debug Summary: {sum(results)}/{len(results)} Passed")
        console_print("=" * 40)
    finally:
        if server_process and not existing_server:
            console_print("Stopping debug server...")
            server_process.terminate()
            server_process.wait()


if __name__ == "__main__":
    main()
