"""
backfill_condiment_tags.py
===========================
El prompt de clasificacion (langchain_pipeline.py) generaba tags de tipo de
comida (desayuno/almuerzo/cena/snack/postre) para salsas, dips, aderezos y
mermeladas, aunque no sean una comida completa por si solas (ej. "Comeback
Sauce" quedo taggeada "salsa, aderezo, snack"). Eso hacia que el RAG planner
las devolviera como desayuno/snack por tener pocas calorias.

El prompt ya se corrigio para las importaciones nuevas. Este script re-tagea
las recetas ya existentes: a cualquier receta que ya tenga un tag de
condimento (salsa/aderezo/dip/etc.) o cuyo nombre lo delate, le quita los
tags de tipo de comida y le deja "condimento". Deterministico, sin costo de
API, re-corrible sin duplicar trabajo (solo toca recetas que de verdad
matchean).
"""
from database import SessionLocal
from models import Recipe

CONDIMENT_TAG_KEYWORDS = {
    "salsa", "aderezo", "dip", "condimento", "dressing",
    "mermelada", "jam", "tapenade", "vinagreta", "chutney",
}

CONDIMENT_NAME_KEYWORDS = [
    "dip", "salsa", "aderezo", "mermelada", "dressing",
    "tapenade", "vinagreta", "chutney",
]

MEAL_TYPE_TAGS = {"desayuno", "almuerzo", "cena", "snack", "postre", "brunch", "merienda"}


def is_condiment(recipe: Recipe) -> bool:
    tags = [t.strip().lower() for t in (recipe.tags or "").split(",") if t.strip()]
    if any(t in CONDIMENT_TAG_KEYWORDS for t in tags):
        return True

    # Coincidencia por nombre: solo cuenta si la palabra clave no viene
    # precedida de "con " / "y " (eso indica que el plato SOLO INCLUYE la
    # salsa/aderezo como componente, ej. "Ensalada ... con aderezo picante"
    # o "Pollo ... y salsa de yogur" -- esos son platos completos, no la
    # salsa en si).
    name = (recipe.nombre or "").lower()
    for kw in CONDIMENT_NAME_KEYWORDS:
        idx = name.find(kw)
        if idx == -1:
            continue
        preceding = name[:idx]
        if preceding.endswith("con ") or preceding.endswith("y "):
            continue
        return True
    return False


def strip_meal_tags(recipe: Recipe) -> str:
    tags = [t.strip() for t in (recipe.tags or "").split(",") if t.strip()]
    kept = [t for t in tags if t.lower() not in MEAL_TYPE_TAGS]
    if "condimento" not in [t.lower() for t in kept]:
        kept.append("condimento")
    return ", ".join(kept)


def main():
    db = SessionLocal()
    try:
        recipes = db.query(Recipe).filter(Recipe.tags.isnot(None)).all()
        changed = []

        for recipe in recipes:
            if not is_condiment(recipe):
                continue
            old_tags = recipe.tags
            new_tags = strip_meal_tags(recipe)
            if new_tags != old_tags:
                changed.append((recipe.id, recipe.nombre, old_tags, new_tags))
                recipe.tags = new_tags

        db.commit()

        print(f"Recetas actualizadas: {len(changed)}")
        for rid, nombre, old_tags, new_tags in changed:
            print(f"  [{rid}] {nombre}")
            print(f"      antes: {old_tags}")
            print(f"      ahora: {new_tags}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
