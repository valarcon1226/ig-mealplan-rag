"""
backfill_cuisine_normalize.py
=============================
El pipeline guardaba tipo_cocina tal cual lo escribía el LLM ("asiática",
"fusión", "colombiana"...) y el buscador/Cookbook comparan contra "asiatica"
exacto, así que la cocina asiática casi nunca aparecía. Deja cada receta con
una de recipe_search.CUISINES (canon_cuisine). Las "fusión" que antes eran
asiáticas se corrigen a mano abajo; el resto de fusión pasa a internacional.

Después de correrlo, re-indexar la base vectorial con populate_db.py (el
filtro de cocina del buscador lee la metadata de Chroma, no SQL).
"""
from database import SessionLocal
from diet import fold
from models import Recipe
from recipe_search import canon_cuisine

# Recetas "fusión" revisadas a mano: id -> cocina que más pesa.
FUSION_OVERRIDES = {52: "asiatica", 138: "asiatica", 168: "asiatica", 172: "asiatica", 164: "americana"}


def main():
    db = SessionLocal()
    try:
        changed = []
        for recipe in db.query(Recipe).filter(Recipe.cuisine_type.isnot(None)).all():
            new = canon_cuisine(recipe.cuisine_type)
            if fold(recipe.cuisine_type) == "fusion" and recipe.id in FUSION_OVERRIDES:
                new = FUSION_OVERRIDES[recipe.id]
            if new != recipe.cuisine_type:
                changed.append((recipe.id, recipe.nombre, recipe.cuisine_type, new))
                recipe.cuisine_type = new
        db.commit()

        print(f"Recetas actualizadas: {len(changed)}")
        for rid, nombre, old, new in changed:
            print(f"  [{rid}] {nombre}: {old}  ->  {new}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
