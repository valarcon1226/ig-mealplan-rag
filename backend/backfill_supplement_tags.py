"""
backfill_supplement_tags.py
===========================
Suplementos caseros (magnesio en polvo, proteína en polvo) venían con tags de
tipo de comida ("snack, desayuno"), así que el reajuste de macros del planner
los elegía como snack por tener 0 azúcar y pocas calorías. Mismo arreglo que
backfill_drink_tags.py: se les quitan los tags de comida y quedan como
"suplemento, otros". Siguen en el Cookbook, solo dejan de entrar al planner.

Detecta por tag "suplemento" o por nombre (magnesio / proteína en polvo); no
usa "polvo" solo porque hay recetas reales como "Pavé de leche en polvo".

Después de correrlo, re-indexar la base vectorial con populate_db.py (el
planner lee los tags de ahí, no de SQL).
"""
import re

from backfill_condiment_tags import MEAL_TYPE_TAGS
from database import SessionLocal
from models import Recipe

SUPPLEMENT_NAME = re.compile(r"magnesio|prote[ií]na en polvo", re.I)


def main():
    db = SessionLocal()
    try:
        changed = []
        for recipe in db.query(Recipe).filter(Recipe.nombre.isnot(None)).all():
            tags = [t.strip() for t in (recipe.tags or "").split(",") if t.strip()]
            lower = [t.lower() for t in tags]
            if "suplemento" not in lower and not SUPPLEMENT_NAME.search(recipe.nombre):
                continue
            kept = [t for t in tags if t.lower() not in MEAL_TYPE_TAGS]
            for tag in ("suplemento", "otros"):
                if tag not in [t.lower() for t in kept]:
                    kept.append(tag)
            new_tags = ", ".join(kept)
            if new_tags != recipe.tags:
                changed.append((recipe.id, recipe.nombre, recipe.tags, new_tags))
                recipe.tags = new_tags
        db.commit()

        print(f"Recetas actualizadas: {len(changed)}")
        for rid, nombre, old_tags, new_tags in changed:
            print(f"  [{rid}] {nombre}: {old_tags}  ->  {new_tags}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
