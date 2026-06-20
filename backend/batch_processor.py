import json
import time
import os
import sys
from langchain_pipeline import run_recipe_pipeline, load_recipes_db, save_recipes_db
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

    # Limitar a la mitad para no gastar todos los tokens
    if len(unanalyzed) > 0:
        limit = len(unanalyzed) // 2
        # Si de casualidad solo queda 1, procesamos ese 1 en lugar de 0
        limit = max(limit, 1)
        unanalyzed = unanalyzed[:limit]
        print(f"Limiting this run to process: {len(unanalyzed)} recipes")

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("Error: GEMINI_API_KEY no encontrada en el .env")
        return

    try:
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
                    recipe = run_recipe_pipeline(
                        media_id=media_id,
                        video_url=inputs["video_url"],
                        gemini_api_key=gemini_key,
                        target_servings=0,
                        save_to_db=False,
                        caption=inputs["caption"]
                    )
                    
                    # Recargar BD para no pisar si el usuario está usando la app
                    db = load_recipes_db() 
                    db[media_id] = recipe
                    save_recipes_db(db)
                    
                    print(f"✅ Success! {recipe.get('nombre')}")
                    success = True
                    
                    # Pausa para evitar Rate Limits (10 Requests Per Minute)
                    time.sleep(10) 
                    
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

    except KeyboardInterrupt:
        print("\nProceso interrumpido por el usuario.")

if __name__ == "__main__":
    main()
