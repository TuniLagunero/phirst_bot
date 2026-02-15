import requests
from decouple import config

# LOAD YOUR CREDENTIALS
PAGE_ACCESS_TOKEN = config('FB_PAGE_ACCESS_TOKEN')
PAGE_ID = "104329078028312"  # I got this from your screenshot (Tales ss)

def check_feed():
    print(f"🔍 Checking Feed for Page ID: {PAGE_ID}...")
    
    # 1. Fetch the latest posts
    url = f"https://graph.facebook.com/v21.0/{PAGE_ID}/feed"
    params = {
        'access_token': PAGE_ACCESS_TOKEN,
        'fields': 'message,created_time,id,comments.limit(5){message,from}'
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    if 'error' in data:
        print("\n❌ API ERROR: Your Token is BROKEN.")
        print(f"Error Details: {data['error']['message']}")
        return

    print("\n✅ API SUCCESS: Your Token works!")
    print(f"Found {len(data.get('data', []))} posts.\n")
    
    for post in data.get('data', []):
        print(f"📝 Post: {post.get('message', 'No Caption')}")
        print(f"   ID: {post.get('id')}")
        
        comments = post.get('comments', {}).get('data', [])
        if comments:
            print(f"   💬 Found {len(comments)} comments:")
            for comment in comments:
                print(f"      - [{comment.get('from', {}).get('name')}]: {comment.get('message')}")
        else:
            print("   Running... No comments found yet.")
        print("-" * 30)

if __name__ == "__main__":
    check_feed()