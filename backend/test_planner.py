import json
import requests

payload = {
    "dailyGoals": {"calories": 1600, "protein": 120, "carbs": 150, "fat": 50},
    "meals": ["desayuno", "almuerzo", "cena"],
    "restrictions": [],
    "plan_type": "daily"
}

resp = requests.post("http://localhost:8011/api/mealplan/generate", json=payload)
print(resp.status_code)
print(json.dumps(resp.json(), indent=2))
