import os
from dotenv import load_dotenv
from langchain_pipeline import run_recipe_pipeline

load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY")

print("API Key loaded:", bool(api_key))

try:
    print("Starting pipeline...")
    result = run_recipe_pipeline(
        media_id="3758015590456423498_73088208474",
        video_url="",  # Should resolve from backup
        gemini_api_key=api_key,
        target_servings=0,
        save_to_db=False,
        caption="test caption"
    )
    print("Pipeline finished!")
    print(result.get("final_recipe", {}).get("nombre"))
except Exception as e:
    print(f"Exception: {e}")
