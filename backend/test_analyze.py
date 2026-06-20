import requests
url = "http://127.0.0.1:8001/analyze-langchain-by-id"
payload = {"media_id": "3812997248033407230_2326491155"}
r = requests.post(url, json=payload)
print(r.status_code, r.text)
