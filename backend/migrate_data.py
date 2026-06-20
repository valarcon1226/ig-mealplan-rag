import json
from database import SessionLocal
from models import Recipe, Ingredient, Food, Unit, NutritionInformation

def get_or_create_food(db, name):
    food = db.query(Food).filter(Food.name == name).first()
    if not food:
        food = Food(name=name)
        db.add(food)
        db.commit()
        db.refresh(food)
    return food

def get_or_create_unit(db, name):
    if not name:
        name = "unidad"
    unit = db.query(Unit).filter(Unit.name == name).first()
    if not unit:
        unit = Unit(name=name)
        db.add(unit)
        db.commit()
        db.refresh(unit)
    return unit

def migrate():
    db = SessionLocal()
    with open("recetas_db.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    print(f"Migrando {len(data)} recetas a la BD relacional...")

    for media_id, item in data.items():
        if not item.get("is_recipe"):
            continue
            
        existing_recipe = db.query(Recipe).filter(Recipe.media_id == media_id).first()
        if existing_recipe:
            continue
            
        nutrition = None
        info_nutricional = item.get("nutricion_por_porcion", {})
        if info_nutricional:
            nutrition = NutritionInformation(
                calories=info_nutricional.get("calorias", 0.0),
                proteins=info_nutricional.get("proteina_g", 0.0),
                carbohydrates=info_nutricional.get("carbohidratos_g", 0.0),
                fats=info_nutricional.get("grasa_g", 0.0)
            )
            db.add(nutrition)
            db.flush()

        recipe = Recipe(
            media_id=media_id,
            nombre=item.get("nombre", "Sin Nombre"),
            video_url=item.get("video_url"),
            thumbnail_url=item.get("thumbnail_url"),
            tiempo_preparacion_min=item.get("tiempo_preparacion_min"),
            servings=item.get("porciones_originales", 1),
            tags=",".join([str(t).lower().strip() for t in item.get("tags", [])]) if item.get("tags") else None,
            nutrition_id=nutrition.id if nutrition else None
        )
        db.add(recipe)
        db.flush() # Para tener recipe.id

        ingredientes = item.get("ingredientes", [])
        for ing_data in ingredientes:
            nombre = ing_data.get("nombre")
            if not nombre:
                continue
                
            food = get_or_create_food(db, nombre.lower().strip())
            unit = get_or_create_unit(db, str(ing_data.get("unidad", "unidad")).lower().strip())
            
            # Limpiar cantidad
            cantidad_val = ing_data.get("cantidad")
            try:
                cantidad = float(cantidad_val) if cantidad_val is not None else 0.0
            except ValueError:
                cantidad = 0.0
                
            ing = Ingredient(
                recipe_id=recipe.id,
                food_id=food.id,
                unit_id=unit.id,
                amount=cantidad,
                note=None
            )
            db.add(ing)
            
    db.commit()
    print("Migración completa.")

if __name__ == "__main__":
    migrate()
