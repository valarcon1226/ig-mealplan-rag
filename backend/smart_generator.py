import random
from typing import List, Dict
from sqlalchemy.orm import Session
from models import Recipe, NutritionInformation

class MealPlanGenerator:
    def __init__(self, db: Session):
        self.db = db
        # Cache de recetas por tag para no consultar a BD miles de veces
        self.recipes_by_tag = {}

    def _get_candidates_for_tag(self, tag: str) -> List[Recipe]:
        """Busca recetas que contengan el tag (case-insensitive)"""
        if tag in self.recipes_by_tag:
            return self.recipes_by_tag[tag]

        # SQLite LIKE es case-insensitive
        candidates = self.db.query(Recipe).filter(Recipe.tags.like(f"%{tag.lower()}%")).all()
        
        # Fallback: Si no hay recetas con el tag, tomar cualquiera que tenga nutrición
        if not candidates:
            print(f"Advertencia: No se encontraron recetas con el tag '{tag}'. Usando fallback genérico.")
            candidates = self.db.query(Recipe).filter(Recipe.nutrition_id != None).all()
            
        # Filtrar solo recetas que tengan info nutricional
        valid_candidates = []
        forbidden_words = ["polvo", "magnesio", "bebida", "electrolyte", "drink", "suplemento", "creatina", "queso cottage casero", "labneh"]
        for r in candidates:
            if not r.nutrition:
                continue
            
            # Exclusion rules for snacks/drinks 
            name_lower = r.nombre.lower() if r.nombre else ""
            if any(fw in name_lower for fw in forbidden_words):
                continue
                
            valid_candidates.append(r)
            
        self.recipes_by_tag[tag] = valid_candidates
        return valid_candidates

    def _evaluate_fitness(self, combination: List[Recipe], target_macros: Dict[str, float]) -> float:
        """
        Calcula qué tan lejos está la combinación de la meta.
        Un puntaje de 0 es un match perfecto. Valores más altos son peores.
        """
        total_cals = sum(r.nutrition.calories for r in combination if r.nutrition)
        total_prot = sum(r.nutrition.proteins for r in combination if r.nutrition)
        total_carbs = sum(r.nutrition.carbohydrates for r in combination if r.nutrition)
        total_fats = sum(r.nutrition.fats for r in combination if r.nutrition)

        target_cals = target_macros.get("calorias", 0)
        target_prot = target_macros.get("proteinas", 0)
        target_carbs = target_macros.get("carbohidratos", 0)
        target_fats = target_macros.get("grasas", 0)

        # Usamos diferencias absolutas. 
        # Multiplicamos la proteína por 10 para darle mucha prioridad a cumplir la meta de proteína.
        diff_cals = abs(total_cals - target_cals)
        diff_prot = abs(total_prot - target_prot) * 10 
        
        score = diff_cals + diff_prot

        if target_carbs > 0:
            score += abs(total_carbs - target_carbs) * 2
        if target_fats > 0:
            score += abs(total_fats - target_fats) * 2

        return score

    def generate(self, meal_structure: List[str], target_macros: Dict[str, float], iterations=10000) -> dict:
        """
        Genera el mejor plan de comidas iterando aleatoriamente.
        """
        # 1. Obtener pools de candidatos
        pools = []
        for tag in meal_structure:
            candidates = self._get_candidates_for_tag(tag)
            if not candidates:
                raise ValueError(f"No hay recetas válidas para cubrir el hueco de: {tag}")
            pools.append(candidates)

        best_combination = None
        best_score = float('inf')

        # 2. Fuerza bruta aleatoria optimizada
        for _ in range(iterations):
            # Escoger una receta al azar para cada hueco
            current_combination = [random.choice(pool) for pool in pools]
            
            # Evaluar
            score = self._evaluate_fitness(current_combination, target_macros)
            
            if score < best_score:
                best_score = score
                best_combination = current_combination
                
                # Si llegamos a un margen aceptable (ej. < 50 puntos de penalidad), podemos salir temprano
                if best_score < 30:
                    break

        # 3. Retornar el resultado
        total_cals = sum(r.nutrition.calories for r in best_combination)
        total_prot = sum(r.nutrition.proteins for r in best_combination)
        total_carbs = sum(r.nutrition.carbohydrates for r in best_combination)
        total_fats = sum(r.nutrition.fats for r in best_combination)

        # Preparar respuesta
        meals_result = []
        for i, recipe in enumerate(best_combination):
            ing_raw = []
            if recipe.ingredients_raw:
                try:
                    import json
                    ing_raw = json.loads(recipe.ingredients_raw)
                except:
                    pass
                    
            ing_mapped = []
            for ing in ing_raw:
                if isinstance(ing, dict):
                    name = ing.get("nombre") or ing.get("ingrediente") or ing.get("item") or "Ingrediente"
                    cantidad = str(ing.get("cantidad", "")) if ing.get("cantidad") is not None else ""
                    unidad = str(ing.get("unidad", "")) if ing.get("unidad") is not None else ""
                    ing_mapped.append({"name": name, "amount": f"{cantidad} {unidad}".strip()})
                else:
                    ing_mapped.append({"name": str(ing), "amount": ""})
                    
            instructions = []
            if recipe.instructions:
                try:
                    import json
                    instructions = json.loads(recipe.instructions)
                except:
                    pass

            meals_result.append({
                "meal_type": meal_structure[i],
                "recipe_id": recipe.id,
                "nombre": recipe.nombre,
                "calorias": recipe.nutrition.calories,
                "proteinas": recipe.nutrition.proteins,
                "ingredients": ing_mapped,
                "instructions": instructions
            })

        return {
            "score": best_score,
            "totals": {
                "calorias": total_cals,
                "proteinas": total_prot,
                "carbohidratos": total_carbs,
                "grasas": total_fats
            },
            "targets": target_macros,
            "meals": meals_result
        }
