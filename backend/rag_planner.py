import json
import re
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from models import Recipe
from vector_db import get_chroma_client, get_or_create_collection, perform_filtered_search
from rag_chatbot import get_llm
from langchain_core.messages import SystemMessage, HumanMessage

# Desvío máximo de calorías de un día contra la meta antes de reajustarlo.
CAL_MARGIN = 0.10


class RAGMealPlanner:
    def __init__(self, db: Session):
        self.db = db
        self.chroma_client = get_chroma_client()
        self.collection = get_or_create_collection(self.chroma_client)
        self.llm = get_llm()

    @staticmethod
    def _valid(results: List[Dict[str, Any]], meal_type: str, restrictions: List[str], exclude=()) -> List[Dict[str, Any]]:
        """Candidatos con receta real, del tipo de comida y que cumplen las restricciones."""
        valid = []
        for res in results:
            # Recetas sin ingredientes son posts de IG donde no se guardó la receta
            # completa -- no hay nada que cocinar.
            if not res.get("ingredientes") or res.get("id") in exclude:
                continue
            tags = [t.strip().lower() for t in (res.get("tags") or "").split(",")]
            if meal_type.lower() not in tags:
                continue
            if any(rest.lower() not in tags for rest in restrictions or []):
                continue
            valid.append(res)
        return valid

    @staticmethod
    def _build_meal(recipe: Recipe, m_type: str) -> Dict[str, Any]:
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

        n = recipe.nutrition
        return {
            "meal_type": m_type,
            "recipe_id": recipe.id,
            "media_id": recipe.media_id,
            "nombre": recipe.nombre,
            "calorias": n.calories if n else 0,
            "proteinas": n.proteins if n else 0,
            "carbohidratos": n.carbohydrates if n else 0,
            "grasas": n.fats if n else 0,
            "thumbnail_url": recipe.thumbnail_url,
            "video_url": recipe.video_url,
            "ingredients": ing_mapped,
            "instructions": instructions,
        }

    def _rebalance_day(self, meals: List[Dict[str, Any]], meal_targets: List[float], target_cals: float, restrictions: List[str]) -> None:
        """
        El LLM no suma bien: con 3 candidatos por comida, un día podía quedar en
        2213 kcal con meta de 1400. La meta es un techo: mientras el día se pase
        (o quede más de CAL_MARGIN por debajo), se toma la comida que más se desvía
        hacia ese lado, se buscan más recetas de ese tipo, se arman 3 opciones que
        dejen el día sin pasarse y se elige la de más proteína.
        """
        floor = 0.7  # el reemplazo se queda en el rango normal de su comida (±30%)
        tried = set()
        for _ in range(4 * len(meals)):  # tope de búsquedas por día
            total = sum(m["calorias"] for m in meals)
            over = total > target_cals
            if not over and total >= target_cals * (1 - CAL_MARGIN):
                return
            if len(tried) == len(meals):
                # Si con porciones normales no baja de la meta, se permiten comidas
                # más livianas (hasta 30% de su objetivo) antes de rendirse.
                if over and floor > 0.3:
                    floor, tried = 0.3, set()
                    continue
                return

            sign = 1 if over else -1
            i = max(
                (j for j in range(len(meals)) if j not in tried),
                key=lambda j: (meals[j]["calorias"] - meal_targets[j]) * sign,
            )
            tried.add(i)
            m_type = meals[i]["meal_type"]
            cur = meals[i]["calorias"]
            # Máximo de calorías que puede tener el reemplazo sin que el día se pase.
            limit = cur - (total - target_cals)

            results = perform_filtered_search(
                self.collection,
                query=f"recetas de {m_type}",
                min_calories=meal_targets[i] * floor,
                max_calories=meal_targets[i] * 1.3,
                n_results=100,
            )
            options = self._valid(results, m_type, restrictions, exclude={m["media_id"] for m in meals})
            cal = lambda r: r.get("calorias") or 0
            if over:
                # Las que dejan el día bajo la meta, empezando por las más cercanas a
                # ella; si ninguna alcanza, las que más bajan (y sigue con otra comida).
                fits = sorted((r for r in options if cal(r) <= limit), key=cal, reverse=True)
                fits = fits or sorted((r for r in options if cal(r) < cur), key=cal)
            else:
                fits = sorted((r for r in options if cur < cal(r) <= limit), key=cal, reverse=True)

            top3 = fits[:3]
            if not top3:
                continue
            best = max(top3, key=lambda r: r.get("proteina") or 0)
            recipe = self.db.query(Recipe).filter(Recipe.media_id == best["id"]).first()
            if not recipe or not recipe.nutrition:
                continue
            meals[i] = self._build_meal(recipe, m_type)
            tried.discard(i)  # la nueva receta puede volver a ajustarse si hace falta

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
            valid_results = self._valid(results, meal_type, restrictions)[:n_results]

            # Si somos muy estrictos y no hay, relajamos calorias
            if not valid_results:
                results = perform_filtered_search(
                    self.collection,
                    query=f"recetas de {meal_type}",
                    n_results=100
                )
                valid_results = self._valid(results, meal_type, restrictions)[:n_results]

            # Si a pesar de relajar calorias sigue sin haber por las restricciones, usamos los mas relevantes sin restriccion estricta
            if not valid_results:
                valid_results = [
                    r for r in results
                    if r.get("ingredientes")
                    and not {"otros", "condimento"} & {t.strip().lower() for t in (r.get("tags") or "").split(",")}
                ][:n_results]
                
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
            meal_targets = []
            for slot_key, m_type in slots:
                media_id = day_obj.get(slot_key)
                if not media_id:
                    continue
                recipe = self.db.query(Recipe).filter(Recipe.media_id == media_id).first()
                if not recipe:
                    continue
                meals_result.append(self._build_meal(recipe, m_type))
                meal_targets.append(total_target_cals * percentages[slot_key])

            self._rebalance_day(meals_result, meal_targets, total_target_cals, restrictions)

            total_cals = sum(m["calorias"] for m in meals_result)
            total_prot = sum(m["proteinas"] for m in meals_result)
            total_carbs = sum(m["carbohidratos"] for m in meals_result)
            total_fats = sum(m["grasas"] for m in meals_result)

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
