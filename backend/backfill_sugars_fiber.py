"""
backfill_sugars_fiber.py
=========================
Completa sugars/fiber en NutritionInformation para las recetas ya existentes.

Paso 1 (gratis, sin LLM): la mayoria de las recetas YA tienen azucares_g/fibra_g
calculados dentro de recetas_db.json (el pipeline ya los calcula desde hace
tiempo - el prompt de nutricion pide explicitamente calcularlos a partir de
los ingredientes). Ese dato nunca se copiaba a SQL. Se migra directo, sin
gastar ni un solo llamado a Gemini.

Paso 2 (solo para lo que quede sin dato): un llamado de texto a Gemini
ANCLADO en los ingredientes y macros YA guardados de esa receta especifica
(no vuelve a mirar el video, no inventa - si no puede calcularlo a partir de
lo que tiene, lo deja en null en vez de adivinar).
"""
import os
import json

from database import SessionLocal
from models import Recipe

RECETAS_DB_FILE = "recetas_db.json"


def load_recetas_db() -> dict:
    if not os.path.exists(RECETAS_DB_FILE):
        return {}
    with open(RECETAS_DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("No se encontro GEMINI_API_KEY")


def compute_from_ingredients(recipe: Recipe, gemini_api_key: str):
    """Calcula azucares_g/fibra_g anclado SOLO en los ingredientes y macros ya guardados de esta receta."""
    import google.generativeai as genai

    try:
        ingredientes = json.loads(recipe.ingredients_raw) if recipe.ingredients_raw else []
    except Exception:
        ingredientes = []

    if not ingredientes:
        return None, None  # sin ingredientes no hay de donde calcular - mejor null que inventar

    ing_text = "\n".join(
        f"- {ing.get('cantidad', '')} {ing.get('unidad', '')} de {ing.get('nombre', '')}"
        for ing in ingredientes if isinstance(ing, dict)
    )

    prompt = f"""Eres un nutricionista. Tenes esta receta con sus ingredientes y sus macros YA CALCULADOS por porción:

Receta: {recipe.nombre}
Porciones: {recipe.servings}
Ingredientes (cantidades YA ajustadas a la porción):
{ing_text}

Macros ya conocidos por porción: {recipe.nutrition.calories} kcal, {recipe.nutrition.proteins}g proteína, {recipe.nutrition.carbohydrates}g carbohidratos, {recipe.nutrition.fats}g grasa.

Calculá cuántos gramos de AZÚCARES (subcategoría de los carbohidratos ya dados) y de FIBRA hay por porción, basándote ÚNICAMENTE en los ingredientes listados arriba. Los azúcares no pueden superar los carbohidratos totales.

Si con estos ingredientes genuinamente no podés estimarlo (ej. faltan cantidades), respondé null en ese campo en vez de inventar un número.

Respondé SOLO con este JSON, sin markdown: {{"azucares_g": 0.0, "fibra_g": 0.0}}"""

    model = genai.GenerativeModel("gemini-2.5-flash")
    resp = model.generate_content(prompt)
    raw = resp.text.replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    return data.get("azucares_g"), data.get("fibra_g")


def main():
    recetas_db = load_recetas_db()
    db = SessionLocal()
    try:
        recipes = db.query(Recipe).filter(Recipe.nutrition_id.isnot(None)).all()
        print(f"Total recetas con nutricion: {len(recipes)}")

        filled_from_json = 0
        needs_llm = []

        for r in recipes:
            if r.nutrition.sugars is not None and r.nutrition.fiber is not None:
                continue

            db_entry = recetas_db.get(r.media_id, {})
            nut = db_entry.get("nutricion_por_porcion", {})
            azucar = nut.get("azucares_g")
            fibra = nut.get("fibra_g")

            if azucar is not None and fibra is not None:
                r.nutrition.sugars = float(azucar)
                r.nutrition.fiber = float(fibra)
                filled_from_json += 1
            else:
                needs_llm.append(r)

        db.commit()
        print(f"Completadas desde recetas_db.json (sin gastar Gemini): {filled_from_json}")
        print(f"Necesitan calculo anclado en ingredientes: {len(needs_llm)}")

        if needs_llm:
            gemini_key = get_gemini_key()
            llm_filled, llm_skipped = 0, 0
            for i, r in enumerate(needs_llm, 1):
                try:
                    azucar, fibra = compute_from_ingredients(r, gemini_key)
                    if azucar is not None and fibra is not None:
                        r.nutrition.sugars = float(azucar)
                        r.nutrition.fiber = float(fibra)
                        llm_filled += 1
                        db.commit()
                        print(f"  [{i}/{len(needs_llm)}] {r.nombre}: azucar={azucar}g fibra={fibra}g")
                    else:
                        llm_skipped += 1
                        print(f"  [{i}/{len(needs_llm)}] {r.nombre}: no se pudo calcular (sin datos suficientes)")
                except Exception as e:
                    llm_skipped += 1
                    print(f"  [{i}/{len(needs_llm)}] {r.nombre}: ERROR {e}")

            print(f"\nCalculadas via LLM anclado: {llm_filled} | Sin poder calcular: {llm_skipped}")

        print("\nListo.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
