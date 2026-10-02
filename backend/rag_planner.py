import json
import re
from collections import Counter
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from models import Recipe
from vector_db import get_chroma_client, get_or_create_collection, perform_filtered_search
from rag_chatbot import get_llm
from diet import avoids
from langchain_core.messages import SystemMessage, HumanMessage

# Desvío máximo de calorías de un día contra la meta antes de reajustarlo.
CAL_MARGIN = 0.10
# Costo extra por cada día en que ya aparece una receta: el reajuste puede repetir
# (hay pocas recetas altas en fibra) pero solo si mejora bastante los macros.
REPEAT_PENALTY = 8

# Intake Score: puntos máximos por métrica (suman 100).
SCORE_POINTS = {"calorias": 45, "proteinas": 20, "carbohidratos": 15, "grasas": 10, "fibra": 5, "azucar": 5}
# Rango de calorías/carbs/grasa por objetivo, como fracción de la meta:
# (inicio puntaje completo, fin puntaje completo, 0 pts por abajo, 0 pts por arriba).
GOAL_BANDS = {
    "lose": (0.80, 1.00, 0.60, 1.20),
    "gain": (0.90, 1.10, 0.70, 1.30),
    "maintain": (0.95, 1.05, 0.75, 1.25),
}


def _band(value: float, target: float, lo: float, hi: float, zero_lo: float, zero_hi: float) -> float:
    """1.0 si value/target está en [lo, hi]; baja lineal hasta 0 en zero_lo / zero_hi."""
    if not target:
        return 1.0
    r = value / target
    if r < lo:
        return max(0.0, (r - zero_lo) / (lo - zero_lo))
    if r > hi:
        return max(0.0, (zero_hi - r) / (zero_hi - hi))
    return 1.0


def intake_score(totals: Dict[str, float], targets: Dict[str, float], goal: str = "maintain",
                 is_pregnant: bool = False) -> Dict[str, Any]:
    """Puntaje 0-100 de lo que se come en el día contra las metas, con desglose por métrica."""
    # En embarazo nunca se premia el déficit.
    band = GOAL_BANDS.get("maintain" if is_pregnant else goal, GOAL_BANDS["maintain"])
    fractions = {
        "calorias": _band(totals.get("calorias", 0), targets.get("calorias"), *band),
        "carbohidratos": _band(totals.get("carbohidratos", 0), targets.get("carbohidratos"), *band),
        "grasas": _band(totals.get("grasas", 0), targets.get("grasas"), *band),
        # mínimo: proporcional hasta la meta; un exceso grande (>130%) resta un poco
        "proteinas": _band(totals.get("proteinas", 0), targets.get("proteinas"), 1.0, 1.3, 0.0, 2.3),
        "fibra": _band(totals.get("fibra", 0), targets.get("fibra"), 1.0, float("inf"), 0.0, float("inf")),
        # máximo: puntaje completo hasta el tope, 0 al 150%
        "azucar": _band(totals.get("azucar", 0), targets.get("azucares"), 0.0, 1.0, -1.0, 1.5),
    }
    breakdown = {k: round(SCORE_POINTS[k] * f, 1) for k, f in fractions.items()}
    return {"total": round(sum(breakdown.values())), "breakdown": breakdown}


class RAGMealPlanner:
    def __init__(self, db: Session):
        self.db = db
        self.chroma_client = get_chroma_client()
        self.collection = get_or_create_collection(self.chroma_client)
        self.llm = get_llm()

    def _diet_ok(self, res: Dict[str, Any], restrictions: List[str]) -> bool:
        """
        Restricciones (Vegano, Apto Diabético...) contra las que la receta cumple
        según diet.py (metadata "restricciones"), no contra los tags: los tags
        casi nunca dicen "vegano". Y nada de lo que el usuario no come.
        """
        cumple = {r.strip().lower() for r in (res.get("restricciones") or "").split(",")}
        if any(rest.strip().lower() not in cumple for rest in restrictions or []):
            return False
        return avoids([res.get("nombre"), res.get("ingredientes")], getattr(self, "avoid", []))

    def _valid(self, results: List[Dict[str, Any]], meal_type: str, restrictions: List[str], exclude=()) -> List[Dict[str, Any]]:
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
            if not self._diet_ok(res, restrictions):
                continue
            valid.append(res)
        return valid

    def _query(self, meal_type: str) -> str:
        """Texto de búsqueda semántica: el tipo de comida + lo que le gusta al usuario."""
        likes = getattr(self, "likes", [])
        return f"recetas de {meal_type}" + (f" con {', '.join(likes)}" if likes else "")

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
            "fibra": (n.fiber or 0) if n else 0,
            "azucar": (n.sugars or 0) if n else 0,
            "thumbnail_url": recipe.thumbnail_url,
            "video_url": recipe.video_url,
            "ingredients": ing_mapped,
            "instructions": instructions,
        }

    @staticmethod
    def fiber_target(protein: float, targets: Dict[str, float]) -> float:
        """Meta de fibra del día: sube en proporción a cuánto se pasa la proteína de su meta."""
        base = targets.get("fibra") or 25
        return base * max(1.0, protein / (targets.get("proteinas") or 150))

    def _macro_cost(self, protein: float, fiber: float, sugar: float, targets: Dict[str, float]) -> float:
        """Qué tan lejos está el día de su proteína, su fibra mínima y su azúcar máxima (menor es mejor)."""
        # ponytail: pesos fijos (1 g de proteína = 1, 1 g de fibra faltante = 2,
        # 1 g de azúcar de más = 1); ajustar si una domina demasiado las elecciones.
        sugar_excess = max(0.0, sugar - targets["azucares"]) if targets.get("azucares") else 0.0
        return (
            abs(protein - (targets.get("proteinas") or 150))
            + 2 * max(0.0, self.fiber_target(protein, targets) - fiber)
            + sugar_excess
        )

    def _day_cost(self, meals: List[Dict[str, Any]], targets: Dict[str, float], i: int = None, option: Dict[str, Any] = None) -> float:
        """Costo de macros del día; con `i`/`option`, como si la comida i se cambiara por esa opción."""
        def val(meal_key, opt_key):
            total = sum(m[meal_key] for m in meals)
            if option is not None:
                total += (option.get(opt_key) or 0) - meals[i][meal_key]
            return total
        return self._macro_cost(val("proteinas", "proteina"), val("fibra", "fibra"), val("azucar", "azucar"), targets)

    def _macros_ok(self, meals: List[Dict[str, Any]], targets: Dict[str, float]) -> bool:
        protein = sum(m["proteinas"] for m in meals)
        return (
            protein <= (targets.get("proteinas") or 150) * (1 + CAL_MARGIN)
            and sum(m["fibra"] for m in meals) >= self.fiber_target(protein, targets)
            and (not targets.get("azucares") or sum(m["azucar"] for m in meals) <= targets["azucares"])
        )

    def _options(self, m_type: str, low: float, high: float, restrictions: List[str], meals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = perform_filtered_search(
            self.collection,
            query=self._query(m_type),
            min_calories=low,
            max_calories=high,
            n_results=100,
        )
        return self._valid(results, m_type, restrictions, exclude={m["media_id"] for m in meals})

    def _swap(self, meals: List[Dict[str, Any]], i: int, option: Dict[str, Any]) -> bool:
        recipe = self.db.query(Recipe).filter(Recipe.media_id == option["id"]).first()
        if not recipe or not recipe.nutrition:
            return False
        meals[i] = self._build_meal(recipe, meals[i]["meal_type"])
        return True

    def _rebalance_day(self, meals: List[Dict[str, Any]], meal_targets: List[float], targets: Dict[str, float], restrictions: List[str], used: Counter = None) -> None:
        """
        El LLM no suma bien: con 3 candidatos por comida, un día podía quedar en
        2213 kcal con meta de 1400, y la proteína quedaba alta todos los días.
        1. Calorías (la meta es un techo): mientras el día se pase (o quede más de
           CAL_MARGIN por debajo), se toma la comida que más se desvía hacia ese lado,
           se buscan más recetas de ese tipo, se arman 3 opciones que dejen el día
           sin pasarse y se elige la que deja proteína y fibra más cerca de su meta.
        2. Proteína y fibra: con las calorías ya bien, si la proteína se pasa más de
           CAL_MARGIN o falta fibra, se prueba cambiar cada comida por otra que
           mantenga las calorías en rango y acerque ambas a su meta.
        """
        used = used or Counter()
        self._rebalance_calories(meals, meal_targets, targets, restrictions, used)

        target_cals = targets.get("calorias", 2000)
        cal_ok = lambda c: target_cals * (1 - CAL_MARGIN) <= c <= target_cals
        for i in list(range(len(meals))) * 2:  # dos pasadas por las comidas
            if self._macros_ok(meals, targets):
                return
            total = sum(m["calorias"] for m in meals)
            cur = meals[i]
            best, best_cost = None, self._day_cost(meals, targets)
            for r in self._options(cur["meal_type"], meal_targets[i] * 0.7, meal_targets[i] * 1.3, restrictions, meals):
                if not cal_ok(total - cur["calorias"] + (r.get("calorias") or 0)):
                    continue
                cost = self._day_cost(meals, targets, i, r) + REPEAT_PENALTY * used[r["id"]]
                if cost < best_cost - 1:
                    best, best_cost = r, cost
            if best:
                self._swap(meals, i, best)

    def _rebalance_calories(self, meals: List[Dict[str, Any]], meal_targets: List[float], targets: Dict[str, float], restrictions: List[str], used: Counter) -> None:
        target_cals = targets.get("calorias", 2000)
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

            options = self._options(m_type, meal_targets[i] * floor, meal_targets[i] * 1.3, restrictions, meals)
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
            best = min(top3, key=lambda r: self._day_cost(meals, targets, i, r) + REPEAT_PENALTY * used[r["id"]])
            if self._swap(meals, i, best):
                tried.discard(i)  # la nueva receta puede volver a ajustarse si hace falta

    def generate(self, meal_structure: List[str], target_macros: Dict[str, float], restrictions: List[str], cycle_phase: str, num_days: int = 1, profile: Dict[str, Any] = None) -> Any:
        """
        `profile`: goal / is_pregnant para el Intake Score, y las preferencias del
        perfil: avoid (no me gusta / alergias, filtro duro) y likes (se priorizan).
        """
        profile = profile or {}
        restrictions = list(restrictions or [])
        self.avoid = [a for a in profile.get("avoid") or [] if a.strip()]
        self.likes = [l for l in profile.get("likes") or [] if l.strip()]
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
        slot_candidates: Dict[str, List[str]] = {}
        for slot_key, meal_type in slots:
            meal_cals = total_target_cals * percentages[slot_key]
            min_cals = meal_cals * 0.70
            max_cals = meal_cals * 1.30
            
            # Pedimos muchos resultados filtrando por calorias
            results = perform_filtered_search(
                self.collection,
                query=self._query(meal_type),
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
                    query=self._query(meal_type),
                    n_results=100
                )
                valid_results = self._valid(results, meal_type, restrictions)[:n_results]

            # Si aun así no hay, se relaja el TIPO de comida, nunca la dieta: a un
            # vegano o diabético no se le puede colar una receta que no puede comer.
            if not valid_results:
                valid_results = [
                    r for r in results
                    if r.get("ingredientes")
                    and not {"otros", "condimento"} & {t.strip().lower() for t in (r.get("tags") or "").split(",")}
                    and self._diet_ok(r, restrictions)
                ][:n_results]
            if not valid_results:
                raise ValueError(
                    f"No hay recetas de {meal_type} que cumplan tu dieta y preferencias "
                    f"({', '.join(restrictions + self.avoid) or 'ninguna'}). Agrega más recetas o ajusta tu perfil."
                )
                
            slot_candidates[slot_key] = [r["id"] for r in valid_results]
            all_candidates_context += f"\n--- Candidatos para {slot_key.upper()} (tipo: {meal_type}, Objetivo: ~{int(meal_cals)} kcal) ---\n"
            for r in valid_results:
                all_candidates_context += (
                    f"ID: {r.get('id', 'UNKNOWN')} | Nombre: {r['nombre']} | "
                    f"Calorias: {r.get('calorias', 0)} | Prot: {r.get('proteina', 0)}g | "
                    f"Fibra: {r.get('fibra') if r.get('fibra') is not None else '?'}g | "
                    f"Azúcar: {r.get('azucar') if r.get('azucar') is not None else '?'}g | "
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
- No come / alergias: {', '.join(self.avoid) if self.avoid else 'Nada'}
- Le gusta (prioriza estas recetas cuando cumplan los macros): {', '.join(self.likes) if self.likes else 'Sin preferencias'}

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
        used_in_plan = Counter()  # el reajuste penaliza repetir recetas de otros días
        for day_obj in days:
            meals_result = []
            meal_targets = []
            for slot_key, m_type in slots:
                media_id = day_obj.get(slot_key)
                if not media_id:
                    continue
                # Solo IDs de los candidatos (que ya cumplen dieta y preferencias):
                # si el LLM inventa o mezcla un ID, se usa el primer candidato.
                if media_id not in slot_candidates.get(slot_key, []):
                    media_id = slot_candidates[slot_key][0]
                recipe = self.db.query(Recipe).filter(Recipe.media_id == media_id).first()
                if not recipe:
                    continue
                meals_result.append(self._build_meal(recipe, m_type))
                meal_targets.append(total_target_cals * percentages[slot_key])

            self._rebalance_day(meals_result, meal_targets, target_macros, restrictions, used_in_plan)
            used_in_plan.update(m["media_id"] for m in meals_result)

            total_cals = sum(m["calorias"] for m in meals_result)
            total_prot = sum(m["proteinas"] for m in meals_result)
            total_carbs = sum(m["carbohidratos"] for m in meals_result)
            total_fats = sum(m["grasas"] for m in meals_result)
            total_fiber = sum(m["fibra"] for m in meals_result)
            total_sugar = sum(m["azucar"] for m in meals_result)

            totals = {
                "calorias": total_cals,
                "proteinas": total_prot,
                "carbohidratos": total_carbs,
                "grasas": total_fats,
                "fibra": total_fiber,
                "azucar": total_sugar,
            }
            # fibra ajustada: sube si ese día la proteína se pasa de su meta
            day_targets = {**target_macros, "fibra": round(self.fiber_target(total_prot, target_macros))}
            score = intake_score(totals, day_targets, goal=profile.get("goal") or "maintain", is_pregnant=bool(profile.get("is_pregnant")))

            result_days.append({
                "day": day_obj.get("day", 1),
                "score": score["total"],
                "score_breakdown": score["breakdown"],
                "totals": totals,
                "targets": day_targets,
                "meals": meals_result
            })
            
        if is_multi_day:
            return result_days
        else:
            return result_days[0] if len(result_days) > 0 else {}
