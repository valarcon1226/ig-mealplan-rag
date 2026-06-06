import json
import uuid
import random
import time

def populate_db():
    print("Leyendo backup...")
    with open("recetas_saludables_backup.json", "r", encoding="utf-8-sig") as f:
        backup = json.load(f)
    posts = backup.get("posts", [])
    
    try:
        with open("recetas_db.json", "r", encoding="utf-8-sig") as f:
            db = json.load(f)
    except Exception:
        db = {}
        
    added = 0
    start_time = int(time.time() * 1000)
    
    for p in posts:
        media_id = p.get("media_id", p.get("id"))
        if not media_id:
            continue
            
        if media_id not in db:
            # Creamos un mock rápido para probar frontend
            db[media_id] = {
                "id": str(uuid.uuid4()),
                "media_id": media_id,
                "title": f"Test Recipe {media_id[-4:]}",
                "video_url": p.get("video_url") or p.get("url", ""),
                "thumbnail_url": p.get("thumbnail_url", ""),
                "imageUrl": p.get("thumbnail_url") or p.get("url", ""),
                "prepTime": "15 mins",
                "servings": random.randint(1, 4),
                "categories": random.sample(["desayuno", "almuerzo", "cena", "snack", "postre", "alto en proteinas", "vegano"], 2),
                "macros": {
                    "calories": random.randint(150, 800),
                    "protein": random.randint(5, 60),
                    "carbs": random.randint(10, 100),
                    "fat": random.randint(5, 45)
                },
                "ingredients": [
                    {"name": "Ingrediente de prueba A", "amount": "100g"},
                    {"name": "Ingrediente de prueba B", "amount": "2 tazas"}
                ],
                "instructions": [
                    "Paso de prueba 1: Mezclar todo.",
                    "Paso de prueba 2: Disfrutar."
                ],
                "createdAt": start_time + added
            }
            added += 1
            
    with open("recetas_db.json", "w", encoding="utf-8-sig") as f:
        json.dump(db, f, indent=2)
        
    print(f"¡Agregadas {added} recetas falsas a la base de datos para pruebas de carga!")

if __name__ == "__main__":
    populate_db()
