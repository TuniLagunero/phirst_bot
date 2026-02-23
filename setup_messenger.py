import requests
from decouple import config

print("⏳ Starting Messenger Setup...")

# Fetch the token from your .env
PAGE_ACCESS_TOKEN = config('FB_PAGE_ACCESS_TOKEN')

if not PAGE_ACCESS_TOKEN:
    print("❌ ERROR: FB_PAGE_ACCESS_TOKEN is missing from your .env file!")
    exit()

URL = f"https://graph.facebook.com/v18.0/me/messenger_profile?access_token={PAGE_ACCESS_TOKEN}"

payload = {
    "get_started": {
        "payload": "GET_STARTED"
    },
    "persistent_menu": [
        {
            "locale": "default",
            "composer_input_disabled": False,
            "call_to_actions": [
                {"type": "postback", "title": "View House Models 🏠", "payload": "VIEW_MODELS"},
                {"type": "postback", "title": "Talk to Agent 📞", "payload": "TALK_TO_AGENT"}
            ]
        }
    ]
}

print("📡 Sending request to Meta Graph API...")

try:
    response = requests.post(URL, json=payload)
    print(f"➡️ Status Code: {response.status_code}")
    print(f"➡️ Response: {response.json()}")
    
    if response.status_code == 200:
        print("✅ SUCCESS! Your persistent menu and Get Started button are live.")
    else:
        print("❌ FAILED. Look at the JSON response above to see why Meta rejected it.")
        
except Exception as e:
    print(f"🔥 CRITICAL SCRIPT ERROR: {e}")