from database import SessionLocal
from models import Recipe

db = SessionLocal()
recipes = db.query(Recipe).all()
print(f"Total recipes: {len(recipes)}")
print(f"Recipes with nutrition: {len([r for r in recipes if r.nutrition])}")

tags = [r.tags for r in recipes if r.tags]
print(f"Sample tags: {tags[:5]}")
