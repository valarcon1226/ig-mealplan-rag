"""
backfill_drink_tags.py
======================
Las bebidas (chocolate caliente, tes, electrolitos, mocktails...) venian con
tags de tipo de comida ("bebida, snack, postre"), asi que el RAG planner las
metia como snack y el mealprep terminaba "cocinandolas" con dias de
anticipacion. Mismo arreglo que backfill_condiment_tags.py: a toda receta con
tag "bebida" se le quitan los tags de comida y se le deja "otros". Siguen en el
Cookbook, solo dejan de entrar al planner.

Despues de correrlo, re-indexar la base vectorial con populate_db.py (el
planner lee los tags de ahi, no de SQL).
"""
from backfill_condiment_tags import MEAL_TYPE_TAGS
from database import SessionLocal
from models import Recipe


def main():
    db = SessionLocal()
    try:
        changed = []
        for recipe in db.query(Recipe).filter(Recipe.tags.isnot(None)).all():
            tags = [t.strip() for t in recipe.tags.split(",") if t.strip()]
            if "bebida" not in [t.lower() for t in tags]:
                continue
            kept = [t for t in tags if t.lower() not in MEAL_TYPE_TAGS]
            if "otros" not in [t.lower() for t in kept]:
                kept.append("otros")
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
