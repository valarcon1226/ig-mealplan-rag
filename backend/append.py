with open('ig_recetas.py', 'a', encoding='utf-8') as f:
    f.write('''

class MealPlanRequest(BaseModel):
    dailyGoals: dict
    meals: list

@app.get("/api/recipes")
def get_all_recipes():
    from database import SessionLocal
    from models import Recipe
    db = SessionLocal()
    recipes = db.query(Recipe).all()
    result = []
    for r in recipes:
        result.append({
            "id": r.id,
            "title": r.nombre,
            "video_url": r.video_url,
            "thumbnail_url": r.thumbnail_url,
            "servings": r.servings,
            "tags": r.tags.split(",") if r.tags else [],
            "macros": {
                "calories": r.nutrition.calories if r.nutrition else 0,
                "protein": r.nutrition.proteins if r.nutrition else 0,
                "carbs": r.nutrition.carbohydrates if r.nutrition else 0,
                "fat": r.nutrition.fats if r.nutrition else 0
            }
        })
    db.close()
    return result

@app.post("/api/mealplan/generate")
def generate_mealplan(request: MealPlanRequest):
    from database import SessionLocal
    from smart_generator import MealPlanGenerator
    db = SessionLocal()
    generator = MealPlanGenerator(db)
    
    targets = {
        "calorias": request.dailyGoals.get("calories", 2000),
        "proteinas": request.dailyGoals.get("protein", 150),
        "carbohidratos": request.dailyGoals.get("carbs", 200),
        "grasas": request.dailyGoals.get("fat", 60)
    }
    
    structure = [m.lower() for m in request.meals]
    
    try:
        result = generator.generate(structure, targets, iterations=10000)
    except Exception as e:
        db.close()
        raise HTTPException(status_code=400, detail=str(e))
        
    db.close()
    return result
''')
