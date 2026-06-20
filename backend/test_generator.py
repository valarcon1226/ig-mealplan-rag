from database import SessionLocal
from smart_generator import MealPlanGenerator
import json

def test_generation():
    db = SessionLocal()
    generator = MealPlanGenerator(db)

    # El usuario define su estructura de comida
    meal_structure = ["desayuno", "almuerzo", "cena"]
    
    # El usuario define sus metas diarias
    # Por ejemplo, una meta de 1800 calorías y 130g de proteína.
    target_macros = {
        "calorias": 1800.0,
        "proteinas": 130.0,
        "carbohidratos": 150.0,
        "grasas": 60.0
    }

    print("Generando plan inteligente...")
    print(f"Meta: {target_macros}")
    print(f"Estructura: {meal_structure}")
    print("-" * 50)

    try:
        result = generator.generate(meal_structure, target_macros, iterations=20000)
        
        print(f"\n¡Plan Generado! (Score de Fitness: {result['score']})")
        print("\nTotales Logrados:")
        print(json.dumps(result["totals"], indent=2, ensure_ascii=False))
        
        print("\nComidas Asignadas:")
        for meal in result["meals"]:
            print(f"[{meal['meal_type'].upper()}] - {meal['nombre']} (Cal: {meal['calorias']}, Prot: {meal['proteinas']}g)")
            
    except Exception as e:
        print(f"Error generando el plan: {e}")

if __name__ == "__main__":
    test_generation()
