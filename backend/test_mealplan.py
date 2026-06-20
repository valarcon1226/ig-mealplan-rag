from database import SessionLocal
from models import Recipe
from mealplan_service import add_to_meal_plan, get_daily_macros, get_meal_plan_by_date
import datetime

def run_tests():
    db = SessionLocal()
    
    # Obtener un par de recetas de la BD
    recipes = db.query(Recipe).limit(2).all()
    if len(recipes) < 2:
        print("No hay suficientes recetas para probar.")
        return

    recipe_1 = recipes[0]
    recipe_2 = recipes[1]
    
    test_date = datetime.date(2026, 6, 8)
    
    # Limpiar plan viejo para evitar duplicados en pruebas seguidas
    old_plans = get_meal_plan_by_date(db, test_date)
    for p in old_plans:
        db.delete(p)
    db.commit()

    print(f"Añadiendo '{recipe_1.nombre}' como Desayuno (Rinde {recipe_1.servings} porciones, comeré 1 porción)")
    add_to_meal_plan(db, recipe_id=recipe_1.id, target_date=test_date, meal_type="Desayuno", servings=1.0)
    
    print(f"Añadiendo '{recipe_2.nombre}' como Almuerzo (Rinde {recipe_2.servings} porciones, comeré 2 porciones)")
    add_to_meal_plan(db, recipe_id=recipe_2.id, target_date=test_date, meal_type="Almuerzo", servings=2.0)
    
    # Obtener el plan programado
    plan = get_meal_plan_by_date(db, test_date)
    print("\n--- Plan del Día ---")
    for meal in plan:
        print(f"[{meal.meal_type}] {meal.recipe.nombre} - Porciones a comer: {meal.servings}")

    # Obtener macros
    macros = get_daily_macros(db, test_date)
    print("\n--- Macros Calculados ---")
    print(macros)

if __name__ == "__main__":
    run_tests()
