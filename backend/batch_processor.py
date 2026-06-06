import json
import time
import os
from langchain_pipeline import analyze_recipe_with_langchain, load_recipes_db, save_recipes_db
from dotenv import load_dotenv

load_dotenv()

def main():
    try:
        with open("recetas_saludables_backup.json", "r", encoding="utf-8-sig") as f:
            backup = json.load(f)
    except Exception as e:
        print("Error loading backup:", e)
        return

    posts = backup.get("posts", [])
    print(f"Total posts in backup: {len(posts)}")

    db = load_recipes_db()
    unanalyzed = [p for p in posts if p.get("media_id", p.get("id")) not in db]
    print(f"Remaining to analyze: {len(unanalyzed)}")

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("Error: GEMINI_API_KEY no encontrada en el .env")
        return

    for i, post in enumerate(unanalyzed):
        media_id = post.get("media_id", post.get("id"))
        if not media_id:
            continue

        print(f"[{i+1}/{len(unanalyzed)}] Analyzing {media_id}...")
        
        inputs = {
            "media_id": media_id,
            "caption": post.get("caption", ""),
            "video_url": post.get("video_url") or post.get("url", ""),
            "thumbnail_url": post.get("thumbnail_url", ""),
            "target_servings": 0
        }

        success = False
        retries = 0
        while not success and retries < 5:
            try:
                recipe = analyze_recipe_with_langchain(inputs, gemini_key)
                
                # Recargar BD para no pisar si el usuario está usando la app
                db = load_recipes_db() 
                db[media_id] = recipe
                save_recipes_db(db)
                
                print(f"✅ Success! {recipe.get('title')}")
                success = True
                
                # Pausa para evitar Rate Limits (10 Requests Per Minute = 1 cada 6 segs)
                time.sleep(6.5) 
                
            except Exception as e:
                err_msg = str(e)
                print(f"⚠️ Error ({retries+1}/5): {err_msg}")
                if "429" in err_msg or "quota" in err_msg.lower() or "rate" in err_msg.lower():
                    print("Hit Rate Limit. Sleeping for 60 seconds...")
                    time.sleep(60)
                    retries += 1
                else:
                    # Si es otro error (ej. el post no es de comida), saltar al siguiente
                    break

if __name__ == "__main__":
    main()
