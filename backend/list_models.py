import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("No API key found")
    exit(1)

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
try:
    resp = requests.get(url)
    resp.raise_for_status()
    models = resp.json().get("models", [])
    
    print("Available models supporting generateContent:")
    for m in models:
        if "generateContent" in m.get("supportedGenerationMethods", []):
            print(f" - {m['name']} (version: {m.get('version', 'N/A')})")
except Exception as e:
    print("Error:", e)
