import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY")

try:
    print("Uploading to Gemini...")
    upload_url = (
        f"https://generativelanguage.googleapis.com/upload/v1beta/files"
        f"?uploadType=multipart&key={api_key}"
    )
    
    # Create a dummy video file of 1MB
    dummy_bytes = b"0" * 1024 * 1024
    
    boundary = "bound_recipe_pipeline"
    metadata = json.dumps({"file": {"display_name": "test_video"}}).encode()
    body = (
        f"--{boundary}\r\nContent-Type: application/json\r\n\r\n"
    ).encode() + metadata + (
        f"\r\n--{boundary}\r\nContent-Type: video/mp4\r\n\r\n"
    ).encode() + dummy_bytes + f"\r\n--{boundary}--\r\n".encode()

    upload_resp = requests.post(
        upload_url,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        data=body,
        timeout=30
    )
    upload_resp.raise_for_status()
    print("Upload Response:", upload_resp.json())
except Exception as e:
    print("Error:", e)
