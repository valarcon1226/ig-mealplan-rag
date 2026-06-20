import sys
import os
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from rag_planner import RAGMealPlanner
import json

def test():
    print("Iniciando test de RAG Planner...")
    db = SessionLocal()
    planner = RAGMealPlanner(db)
    
    targets = {
        "calorias": 1600,
        "proteinas": 110,
        "carbohidratos": 150,
        "grasas": 50
    }
    
    meals = ["desayuno", "almuerzo"]
    restrictions = ["Vegetariano"]
    cycle = "fase lútea"
    
    try:
        res = planner.generate(meals, targets, restrictions, cycle)
        print("Test Exitoso:")
        print(json.dumps(res, indent=2))
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    test()
