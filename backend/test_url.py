import json
import requests

try:
    with open("recetas_saludables_backup.json", "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    
    url = None
    if isinstance(data, list):
        posts = data
    else:
        posts = data.get("posts", [])

    print(f"Loaded {len(posts)} posts")

    for item in posts:
        if item.get("video_url"):
            url = item["video_url"]
            print(f"Testing URL: {url[:80]}...")
            break
            
    if url:
        headers = {
            "User-Agent": "Instagram 219.0.0.12.117 Android",
            "Accept": "*/*"
        }
        resp = requests.get(url, stream=True, headers=headers)
        print(f"Status (Android): {resp.status_code}")
        
except Exception as e:
    print(e)
