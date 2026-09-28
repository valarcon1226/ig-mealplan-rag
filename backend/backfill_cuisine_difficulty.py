"""
backfill_cuisine_difficulty.py
===============================
Las recetas ya procesadas antes de hoy no tienen cuisine_type/dificultad
(esos campos no existian). En vez de gastar una llamada a Gemini por cada
una de las 244+ recetas, se infieren con reglas simples por palabras clave
en ingredientes/tags/nombre (mismo estilo que infer_dietary_restrictions en
vector_db.py). Es barato, determinista y re-corrible sin duplicar trabajo
(solo toca recetas con el campo en null).
"""
import json

from database import SessionLocal
from models import Recipe

CUISINE_KEYWORDS = {
    "italiana": ["pasta", "parmesano", "mozzarella", "albahaca", "pesto", "risotto",
                 "prosciutto", "burrata", "spaghetti", "penne", "lasagna", "parmigiano"],
    "mexicana": ["tortilla", "taco", "elote", "chile", "cilantro", "frijoles",
                 "guacamole", "jalapeño", "salsa verde", "tomatillo", "chipotle", "pico de gallo"],
    "asiatica": ["soya", "jengibre", "sriracha", "wok", "sesamo", "sésamo", "kimchi",
                 "teriyaki", "miso", "wasabi", "shiitake", "salsa de soja", "ajonjoli"],
    "mediterranea": ["aceite de oliva", "feta", "aceitunas", "hummus", "pepino",
                      "yogur griego", "tahini", "pita", "tzatziki"],
    "americana": ["hamburguesa", "bacon", "bbq", "cheddar", "pretzel", "burger", "buffalo"],
    "india": ["curry", "garam masala", "curcuma", "cúrcuma", "comino", "cardamomo", "naan"],
}

DIFFICULTY_KEYWORDS_HARD = ["estofad", "fermentad", "marinar", "reposar toda la noche", "sous vide", "flambear"]


def infer_cuisine(recipe: Recipe) -> str:
    text_parts = [recipe.nombre or "", recipe.tags or ""]
    try:
        ingredientes = json.loads(recipe.ingredients_raw) if recipe.ingredients_raw else []
        for ing in ingredientes:
            if isinstance(ing, dict):
                text_parts.append(str(ing.get("nombre", "")))
            else:
                text_parts.append(str(ing))
    except Exception:
        pass

    text = " ".join(text_parts).lower()

    scores = {cuisine: sum(1 for kw in kws if kw in text) for cuisine, kws in CUISINE_KEYWORDS.items()}
    best_cuisine = max(scores, key=scores.get)
    return best_cuisine if scores[best_cuisine] > 0 else "internacional"


def infer_dificultad(recipe: Recipe) -> str:
    try:
        instrucciones = json.loads(recipe.instructions) if recipe.instructions else []
    except Exception:
        instrucciones = []
    num_pasos = len(instrucciones) if isinstance(instrucciones, list) else 0
    tiempo = recipe.tiempo_preparacion_min or 0
    text = " ".join(str(i) for i in instrucciones).lower() if isinstance(instrucciones, list) else ""

    if any(kw in text for kw in DIFFICULTY_KEYWORDS_HARD) or num_pasos >= 8 or tiempo >= 60:
        return "dificil"
    if num_pasos <= 4 and (tiempo == 0 or tiempo <= 20):
        return "facil"
    return "media"


def main():
    db = SessionLocal()
    try:
        pending = db.query(Recipe).filter(
            (Recipe.cuisine_type.is_(None)) | (Recipe.dificultad.is_(None))
        ).all()
        print(f"Recetas a completar: {len(pending)}")

        for recipe in pending:
            if not recipe.cuisine_type:
                recipe.cuisine_type = infer_cuisine(recipe)
            if not recipe.dificultad:
                recipe.dificultad = infer_dificultad(recipe)

        db.commit()
        print(f"Listo. {len(pending)} recetas actualizadas.")

        # Resumen rapido
        from collections import Counter
        all_recipes = db.query(Recipe).all()
        print("Distribucion cuisine_type:", Counter(r.cuisine_type for r in all_recipes))
        print("Distribucion dificultad:", Counter(r.dificultad for r in all_recipes))
    finally:
        db.close()


if __name__ == "__main__":
    main()
