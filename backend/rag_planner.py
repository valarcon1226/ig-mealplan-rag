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

    def generate(self, meal_structure: List[str], target_macros: Dict[str, float], restrictions: List[str], cycle_phase: str, num_days: int = 1) -> Any:
        is_multi_day = num_days > 1
        n_results = 3
        
        all_candidates_context = ""

        total_target_cals = target_macros.get("calorias", 2000)

        # meal_structure puede traer el mismo tipo repetido (ej. dos snacks),
        # y el string del tipo ("snack") no alcanza como llave unica para el
        # dict de porcentajes ni para las llaves del JSON que arma el LLM --
        # sin esto, la segunda ocurrencia pisaba a la primera y se perdia una
        # de las dos comidas. Se genera una llave unica por slot.
        MEAL_TYPE_WEIGHTS = {
            "desayuno": 25,
            "almuerzo": 30,
            "comida": 30,
            "cena": 25,
            "snack": 10,
            "postre": 10,
        }
        DEFAULT_WEIGHT = 10

        slots = []  # [(slot_key, meal_type), ...]
        occurrences: Dict[str, int] = {}
        for m in meal_structure:
            occurrences[m] = occurrences.get(m, 0) + 1
            n = occurrences[m]
            slot_key = m if n == 1 else f"{m}_{n}"
            slots.append((slot_key, m))

        weights = {slot_key: MEAL_TYPE_WEIGHTS.get(m.lower(), DEFAULT_WEIGHT) for slot_key, m in slots}
        total_weight = sum(weights.values()) or 1
        percentages = {slot_key: w / total_weight for slot_key, w in weights.items()}

        # 1. Recuperar candidatos
        for slot_key, meal_type in slots:
            meal_cals = total_target_cals * percentages[slot_key]
            min_cals = meal_cals * 0.70
            max_cals = meal_cals * 1.30
            
            # Pedimos muchos resultados filtrando por calorias
            results = perform_filtered_search(
                self.collection,
                query=f"recetas de {meal_type}",
                min_calories=min_cals,
                max_calories=max_cals,
                n_results=100
            )
            
            # Filtrar estrictamente por tag y restricciones en python
            valid_results = []
            for res in results:
                tags = [t.strip().lower() for t in res.get("tags", "").split(",")]
                if meal_type.lower() not in tags:
                    continue
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
            
            # Si somos muy estrictos y no hay, relajamos calorias
            if not valid_results:
                results = perform_filtered_search(
                    self.collection,
                    query=f"recetas de {meal_type}",
                    n_results=100
                )
                for res in results:
                    tags = [t.strip().lower() for t in res.get("tags", "").split(",")]
                    if meal_type.lower() not in tags:
                        continue
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
                
            # Si a pesar de relajar calorias sigue sin haber por las restricciones, usamos los mas relevantes sin restriccion estricta
            if not valid_results:
                valid_results = results[:n_results]
                
            all_candidates_context += f"\n--- Candidatos para {slot_key.upper()} (tipo: {meal_type}, Objetivo: ~{int(meal_cals)} kcal) ---\n"
            for r in valid_results:
                all_candidates_context += (
                    f"ID: {r.get('id', 'UNKNOWN')} | Nombre: {r['nombre']} | "
                    f"Calorias: {r.get('calorias', 0)} | Prot: {r.get('proteina', 0)}g | "
                    f"Tags: {r.get('tags', '')}\n"
                )

        # 2. Prompt Dinámico
        slot_keys = [slot_key for slot_key, _ in slots]
        keys_example = ",\n        ".join([f'"{k}": "ID_DEL_CANDIDATO"' for k in slot_keys])
        
        if is_multi_day:
            remaining_days = ", ".join(str(d) for d in range(2, num_days + 1))
            goal_text = f"Armar un plan de {num_days} DÍAS que incluya exactamente estas comidas CADA DÍA: {', '.join(meal_structure)}."
            json_format = f"""{{
  "days": [
    {{
      "day": 1,
      {keys_example}
    }}
    // ... repite la estructura para el day {remaining_days}
  ]
}}"""
            instructions_text = f"DEBES generar exactamente {num_days} días. Para CADA DÍA, DEBES rellenar TODAS las llaves obligatorias ({', '.join(slot_keys)}). Cada llave es una comida distinta aunque el nombre se repita (ej. hay dos snacks). Intenta no repetir recetas seguidas."
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
            instructions_text = f"DEBES rellenar TODAS las llaves obligatorias ({', '.join(slot_keys)}). Cada llave es una comida distinta aunque el nombre se repita (ej. hay dos snacks). No dejes ninguna vacía."

        prompt = f"""Eres un Nutricionista y Planeador de Dietas experto.
Objetivo: {goal_text}

Metas Diarias:
- Calorías Totales: ~{target_macros.get('calorias', 2000)} kcal
- Proteínas: ~{target_macros.get('proteinas', 150)} g
- Carbohidratos: ~{target_macros.get('carbohidratos', 200)} g
- Grasas: ~{target_macros.get('grasas', 60)} g{f"{chr(10)}- Azúcares: máximo ~{target_macros.get('azucares')} g" if target_macros.get('azucares') else ""}{f"{chr(10)}- Fibra: mínimo ~{target_macros.get('fibra')} g" if target_macros.get('fibra') else ""}

Perfil del Usuario:
- Fase del ciclo menstrual / Estado: {cycle_phase if cycle_phase else 'No especificada'}
- Restricciones Alimentarias: {', '.join(restrictions) if restrictions else 'Ninguna'}

Instrucciones:
Revisa los siguientes candidatos y cumple tu objetivo.
{instructions_text}
Asegúrate de que la suma de macros DIARIA se acerque a las metas.

Reglas Estrictas de Selección:
- REGLA ABSOLUTA: Tienes que devolver EXACTAMENTE 1 receta para CADA UNO de los tipos de comida solicitados. Es PREFERIBLE pasarse o quedarse corto en los macros antes que omitir una comida. NO omitas ninguna comida bajo ninguna circunstancia.
- Prohibido seleccionar recetas que sean claramente dips, quesos, aderezos, condimentos, POLVOS o SUPLEMENTOS (como "magnesio en polvo") para snacks o comidas principales. Los snacks deben ser comidas o alimentos reales (ej. galletas, fruta, yogur, etc.).
- Cada comida debe ser lógica y apropiada para su horario.
- DIVERSIDAD DE DÍAS: Si estás generando múltiples días, asegúrate de crear la mayoría de los días COMPLETAMENTE DIFERENTES entre sí. Puedes repetir las comidas de 1 o 2 días, pero no repitas la misma estructura todos los días.

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
        
        print("GEMINI RAW RESP:", text_resp)
        
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
            
            for slot_key, m_type in slots:
                media_id = day_obj.get(slot_key)
                if not media_id:
                    continue
                
                recipe = self.db.query(Recipe).filter(Recipe.media_id == media_id).first()
                if not recipe:
                    continue
                    
                ing_raw = []
                if recipe.ingredients_raw:
                    try:
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
                        instructions = json.loads(recipe.instructions)
                    except:
                        pass

                meals_result.append({
                    "meal_type": m_type,
                    "recipe_id": recipe.id,
                    "nombre": recipe.nombre,
                    "calorias": recipe.nutrition.calories if recipe.nutrition else 0,
                    "proteinas": recipe.nutrition.proteins if recipe.nutrition else 0,
                    "carbohidratos": recipe.nutrition.carbohydrates if recipe.nutrition else 0,
                    "grasas": recipe.nutrition.fats if recipe.nutrition else 0,
                    "thumbnail_url": recipe.thumbnail_url,
                    "video_url": recipe.video_url,
                    "ingredients": ing_mapped,
                    "instructions": instructions
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
            
        if is_multi_day:
            return result_days
        else:
            return result_days[0] if len(result_days) > 0 else {}
