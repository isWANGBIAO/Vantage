import requests
import sys

BASE_URL = "http://localhost:8000"

def test_endpoint(name, url):
    print(f"Testing {name} ({url})...")
    try:
        response = requests.get(f"{BASE_URL}{url}")
        if response.status_code == 200:
            print(f"✅ {name}: Success")
            try:
                data = response.json()
                print(f"   Data keys: {list(data.keys())}")
                if "content" in data:
                    print(f"   Content length: {len(data['content'])}")
                if "logs" in data:
                    print(f"   Logs count: {len(data['logs'])}")
            except:
                print("   Response is not JSON")
        else:
            print(f"❌ {name}: Failed ({response.status_code})")
    except Exception as e:
        print(f"❌ {name}: Connection Failed ({e})")

print("=== Verifying Backend API ===")
test_endpoint("Action Plan Content", "/api/action_plan_content")
test_endpoint("System Logs", "/api/system_logs")
test_endpoint("Status", "/api/status")
