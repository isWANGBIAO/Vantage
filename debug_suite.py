import subprocess
import requests
import time
import sys
import os
import signal
import psutil

SERVER_PORT = 8000
BASE_URL = f"http://localhost:{SERVER_PORT}"
SERVER_SCRIPT = "src/server.py"
LOG_FILE = "logs/debug_server.log"

def is_port_in_use(port):
    for conn in psutil.net_connections():
        if conn.laddr.port == port:
            return True
    return False

def start_server():
    print(f"🚀 Starting Dashboard Backend for debugging...")
    if not os.path.exists("logs"):
        os.makedirs("logs")
        
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    # Start server process
    process = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        stdout=open(LOG_FILE, "w"),
        stderr=subprocess.STDOUT,
        env=env,
        cwd=os.getcwd()
    )
    return process

def wait_for_server(timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            requests.get(f"{BASE_URL}/api/status", timeout=1)
            print("✅ Backend is READY.")
            return True
        except requests.exceptions.ConnectionError:
            time.sleep(1)
            print(".", end="", flush=True)
    print("\n❌ Backend failed to start within timeout.")
    return False

def test_api(name, path, method="GET", expected_code=200):
    print(f"\n🔍 Testing {name} [{path}]...")
    try:
        url = f"{BASE_URL}{path}"
        if method == "GET":
            res = requests.get(url)
        else:
            res = requests.post(url)
            
        if res.status_code == expected_code:
            print(f"   ✅ OK ({res.status_code})")
            if "json" in res.headers.get("Content-Type", ""):
                data = res.json()
                # Print summary of data
                if isinstance(data, dict):
                    keys = list(data.keys())
                    print(f"   📦 Response Keys: {keys}")
                    if "content" in data:
                        print(f"   📄 Content Preview: {data['content'][:50]}..." if data['content'] else "   📄 Content: (Empty)")
                    if "logs" in data:
                        print(f"   📝 Logs Count: {len(data['logs'])}")
                        if data['logs']:
                            print(f"   📝 Last Log: {data['logs'][-1].strip()}")
                elif isinstance(data, list):
                     print(f"   📦 List Length: {len(data)}")
            return True
        else:
            print(f"   ❌ Failed: Status {res.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def main():
    server_process = None
    existing_server = False
    
    # 1. Check if server is already running
    if is_port_in_use(SERVER_PORT):
        print("⚠️ Port 8000 is already in use. Assuming User's server is running.")
        existing_server = True
        if not wait_for_server(timeout=5):
            print("❌ Port is used but /api/status not responding. Aborting.")
            return
    else:
        # 2. Start our own server
        server_process = start_server()
        if not wait_for_server():
            server_process.terminate()
            return

    try:
        # 3. Run Tests
        results = []
        results.append(test_api("System Status", "/api/status"))
        results.append(test_api("System Stats (CPU/Mem)", "/api/sys_stats"))
        results.append(test_api("Action Plan History", "/api/action_plan_content"))
        results.append(test_api("System Logs", "/api/system_logs"))
        
        # 4. Summary
        print("\n" + "="*40)
        print(f"🏁 Debug Summary: {sum(results)}/{len(results)} Passed")
        print("="*40)
        
    finally:
        # 5. Cleanup
        if server_process and not existing_server:
            print("🛑 Stopping debug server...")
            server_process.terminate()
            server_process.wait()

if __name__ == "__main__":
    main()
