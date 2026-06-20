import json
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import Recipe, NutritionInformation

def sync_db():
    print("Sincronizando recetas del backup a SQLite...")
    
    with open("recetas_saludables_backup.json", "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    
    posts = data.get("posts", [])
    
    db = SessionLocal()
    added_count = 0
    
    for post in posts:
        analysis = post.get("ai_analysis", {})
        if not analysis.get("is_recipe"):
            continue
            
        media_id = post.get("media_id")
        if not media_id:
            continue
            
        # Check if exists
        existing = db.query(Recipe).filter(Recipe.media_id == media_id).first()
        if existing:
            continue
            
        # Extract nutrition
        nut_data = analysis.get("nutricion_por_porcion", {})
        
        nutrition = NutritionInformation(
            calories=float(nut_data.get("calorias", nut_data.get("kcal", 0))),
            proteins=float(nut_data.get("proteina_g", 0)),
            carbohydrates=float(nut_data.get("carbohidratos_g", 0)),
            fats=float(nut_data.get("grasa_g", nut_data.get("grasas_g", 0)))
        )
        
        # Tags string
        tags = []
        tags.extend(analysis.get("tags", []))
        tags_str = ", ".join(tags)
        
        # Parse time
        time_prep = analysis.get("tiempo_preparacion_min")
        if time_prep is None or str(time_prep).lower() == "null":
            time_prep = 0
        else:
            try:
                time_prep = int(float(time_prep))
            except:
                time_prep = 0
                
        recipe = Recipe(
            media_id=media_id,
            nombre=analysis.get("nombre", "Sin nombre"),
            video_url=post.get("url"),
            thumbnail_url=post.get("url"),
            tiempo_preparacion_min=time_prep,
            tags=tags_str,
            instructions=json.dumps(analysis.get("instrucciones", []), ensure_ascii=False),
            ingredients_raw=json.dumps(analysis.get("ingredientes", []), ensure_ascii=False),
            nutrition=nutrition
        )
        
        db.add(nutrition)
        db.add(recipe)
        added_count += 1
        
    db.commit()
    db.close()
    
    print(f"Sincronizacion completada. {added_count} recetas agregadas a SQLite.")

if __name__ == "__main__":
    sync_db()
