import json
import re
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from models import Recipe
from vector_db import get_chroma_client, get_or_create_collection, perform_filtered_search
from rag_chatbot import get_llm
from langchain_core.messages import SystemMessage, HumanMessage

class RAGMealPlanner:
    def __init__(self, db: Session):
        self.db = db
        self.chroma_client = get_chroma_client()
        self.collection = get_or_create_collection(self.chroma_client)
        self.llm = get_llm()

    def generate(self, meal_structure: List[str], target_macros: Dict[str, float], restrictions: List[str], cycle_phase: str, plan_type: str = "daily") -> Any:
        is_weekly = (plan_type == "weekly")
        n_results = 30 if is_weekly else 15
        
        candidates_by_meal = {}
        all_candidates_context = ""
        
        # 1. Recuperar candidatos
        for meal_type in meal_structure:
            # Traer más resultados iniciales para tener margen de filtrado estricto
            results = perform_filtered_search(
                self.collection,
                query=f"recetas de {meal_type}",
                n_results=100
            )
            
            valid_results = []
            for res in results:
                tags = [t.strip().lower() for t in res.get("tags", "").split(",")]
                
                # Filtrar estrictamente por tipo de comida
                if meal_type.lower() not in tags:
                    continue
                    
                # Filtrar estrictamente por restricciones (ej. vegetariano)
                if restrictions:
                    fails_restriction = False
                    for rest in restrictions:
                        if rest.lower() not in tags:
                            fails_restriction = True
                            break
                    if fails_restriction:
                        continue
                
                valid_results.append(res)
                if len(valid_results) >= n_results:
                    break
            
            # Si somos muy estrictos y no hay, relajamos un poco solo para no romper
            if not valid_results:
                valid_results = results[:10]
                
            candidates_by_meal[meal_type] = valid_results
            
            all_candidates_context += f"\n--- Candidatos para {meal_type.upper()} ---\n"
            for r in valid_results:
                all_candidates_context += (
                    f"ID: {r.get('id', 'UNKNOWN')} | Nombre: {r['nombre']} | "
                    f"Calorias: {r.get('calorias', 0)} | Prot: {r.get('proteina', 0)}g | "
                    f"Tags: {r.get('tags', '')}\n"
                )

        # 2. Prompt Dinámico
        keys_example = ",\n        ".join([f'"{m}": "ID_DEL_CANDIDATO"' for m in meal_structure])
        
        if is_weekly:
            goal_text = f"Armar un plan SEMANAL (7 días) que incluya exactamente estas comidas CADA DÍA: {', '.join(meal_structure)}."
            json_format = f"""{{
  "days": [
    {{
      "day": 1,
      {keys_example}
    }}
    // ... repite la estructura para el day 2, 3, 4, 5, 6 y 7
  ]
}}"""
            instructions_text = f"DEBES generar exactamente 7 días. Para CADA DÍA, DEBES rellenar TODAS las llaves obligatorias ({', '.join(meal_structure)}). Intenta no repetir recetas seguidas."
        else:
            goal_text = f"Armar un plan de UN DÍA que incluya exactamente estas comidas: {', '.join(meal_structure)}."
            json_format = f"""{{
  "days": [
    {{
      "day": 1,
      {keys_example}
    }}
  ]
}}"""
            instructions_text = f"DEBES rellenar TODAS las llaves obligatorias ({', '.join(meal_structure)}). No dejes ninguna vacía."

        prompt = f"""Eres un Nutricionista y Planeador de Dietas experto.
Objetivo: {goal_text}

Metas Diarias:
- Calorías Totales: ~{target_macros.get('calorias', 2000)} kcal
- Proteínas: ~{target_macros.get('proteinas', 150)} g
- Carbohidratos: ~{target_macros.get('carbohidratos', 200)} g
- Grasas: ~{target_macros.get('grasas', 60)} g

Perfil del Usuario:
- Fase del ciclo menstrual / Estado: {cycle_phase if cycle_phase else 'No especificada'}
- Restricciones Alimentarias: {', '.join(restrictions) if restrictions else 'Ninguna'}

Instrucciones:
Revisa los siguientes candidatos y cumple tu objetivo.
{instructions_text}
Asegúrate de que la suma de macros DIARIA se acerque a las metas.

Reglas Estrictas de Selección:
- REGLA ABSOLUTA: Tienes que devolver EXACTAMENTE 1 receta para CADA UNO de los tipos de comida solicitados. Es PREFERIBLE pasarse o quedarse corto en los macros antes que omitir una comida. NO omitas ninguna comida bajo ninguna circunstancia.
- Prohibido seleccionar recetas que sean claramente dips, quesos, aderezos, condimentos o snacks muy ligeros para comidas principales (Desayuno, Almuerzo, Cena). Estas solo deben ir como Snack o Postre.
- Cada comida debe ser lógica y apropiada para su horario (ej. un desayuno debe ser un plato fuerte de desayuno, no un queso crema).

Devuelve tu selección como un objeto JSON estricto con este formato:
{json_format}
NO agregues nada de texto antes ni después del JSON. Sólo devuelve el JSON.

CANDIDATOS DISPONIBLES:
{all_candidates_context}
"""
        messages = [
            SystemMessage(content="Eres una API de planeamiento nutricional. Responde solo con JSON válido."),
            HumanMessage(content=prompt)
        ]
        
        response = self.llm.invoke(messages)
        text_resp = response.content
        
        if isinstance(text_resp, list):
            text_resp = text_resp[0].get("text", "") if isinstance(text_resp[0], dict) else str(text_resp[0])
        elif not isinstance(text_resp, str):
            text_resp = str(text_resp)
            
        match = re.search(r'\{[\s\S]*\}', text_resp)
        if not match:
            raise ValueError(f"No se pudo parsear el plan de Gemini. Respuesta raw: {text_resp}")
            
        plan_json = json.loads(match.group(0))
        days = plan_json.get("days", [])
        
        # 4. Traducir y armar resultado
        result_days = []
        for day_obj in days:
            meals_result = []
            total_cals = 0
            total_prot = 0
            total_carbs = 0
            total_fats = 0
            
            for m_type in meal_structure:
                media_id = day_obj.get(m_type)
                if not media_id:
                    continue
                
                recipe = self.db.query(Recipe).filter(Recipe.media_id == media_id).first()
                if not recipe:
                    continue
                    
                meals_result.append({
                    "meal_type": m_type,
                    "recipe_id": recipe.id,
                    "nombre": recipe.nombre,
                    "calorias": recipe.nutrition.calories if recipe.nutrition else 0,
                    "proteinas": recipe.nutrition.proteins if recipe.nutrition else 0
                })
                
                if recipe.nutrition:
                    total_cals += recipe.nutrition.calories
                    total_prot += recipe.nutrition.proteins
                    total_carbs += recipe.nutrition.carbohydrates
                    total_fats += recipe.nutrition.fats
                    
            diff_cals = abs(total_cals - target_macros.get("calorias", 0))
            diff_prot = abs(total_prot - target_macros.get("proteinas", 0)) * 10
            score = diff_cals + diff_prot

            result_days.append({
                "day": day_obj.get("day", 1),
                "score": score,
                "totals": {
                    "calorias": total_cals,
                    "proteinas": total_prot,
                    "carbohidratos": total_carbs,
                    "grasas": total_fats
                },
                "targets": target_macros,
                "meals": meals_result
            })
            
        if is_weekly:
            return result_days
        else:
            return result_days[0] if len(result_days) > 0 else {}
