import json
import chromadb
from sentence_transformers import SentenceTransformer
import warnings
warnings.filterwarnings("ignore")

from database import SessionLocal
from models import Recipe
import sqlite3

db = SessionLocal()
all_recipes = db.query(Recipe).all()

desayunos = []
for r in all_recipes:
    tags = [t.strip().lower() for t in (r.tags.split(',') if r.tags else [])]
    if "desayuno" in tags:
        desayunos.append(r.nombre)

print(f"Total recetas en SQLite con tag desayuno: {len(desayunos)}")
print(desayunos[:5])
