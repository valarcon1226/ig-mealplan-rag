from sqlalchemy.orm import Session
from models import MealPlan, Recipe, NutritionInformation
from datetime import date
from typing import List

def add_to_meal_plan(db: Session, recipe_id: int, target_date: date, meal_type: str, servings: float) -> MealPlan:
    """
    Añade una receta al plan de comidas para una fecha específica.
    """
    # Verificar que la receta exista
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise ValueError(f"La receta con id {recipe_id} no existe.")

    new_meal = MealPlan(
        recipe_id=recipe_id,
        target_date=target_date,
        meal_type=meal_type,
        servings=servings
    )
    db.add(new_meal)
    db.commit()
    db.refresh(new_meal)
    return new_meal

def get_meal_plan_by_date(db: Session, target_date: date) -> List[MealPlan]:
    """
    Recupera todas las comidas planeadas para un día en específico.
    """
    return db.query(MealPlan).filter(MealPlan.target_date == target_date).order_by(MealPlan.meal_type).all()

def get_daily_macros(db: Session, target_date: date) -> dict:
    """
    Calcula los macros totales de un día ajustando las porciones planeadas.
    """
    meals = get_meal_plan_by_date(db, target_date)
    
    total_calories = 0.0
    total_proteins = 0.0
    total_carbs = 0.0
    total_fats = 0.0

    for meal in meals:
        recipe = meal.recipe
        nutrition = recipe.nutrition
        
        if nutrition:
            # Factor de ajuste: si la receta rinde 2 porciones y me comeré 1, el factor es 0.5
            original_servings = recipe.servings if recipe.servings and recipe.servings > 0 else 1.0
            adjustment_factor = meal.servings / original_servings

            total_calories += nutrition.calories * adjustment_factor
            total_proteins += nutrition.proteins * adjustment_factor
            total_carbs += nutrition.carbohydrates * adjustment_factor
            total_fats += nutrition.fats * adjustment_factor

    return {
        "date": target_date.isoformat(),
        "total_calories": round(total_calories, 2),
        "total_proteins": round(total_proteins, 2),
        "total_carbohydrates": round(total_carbs, 2),
        "total_fats": round(total_fats, 2),
        "meal_count": len(meals)
    }
