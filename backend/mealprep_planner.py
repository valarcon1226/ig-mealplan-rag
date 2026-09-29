import json
import re
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from ingredient_normalizer import normalize_ingredient_name, parse_amount_str
from rag_chatbot import get_llm
from langchain_core.messages import SystemMessage, HumanMessage


# Orden fijo y nombre visible de cada fase; el LLM solo elige la key.
PHASES = {
    "previa": "Preparación previa (día anterior)",
    "corte": "Corte y preparación",
    "activa": "Cocción activa",
    "pasiva": "Cocción pasiva (horno / olla)",
    "almacenamiento": "Ensamblaje y almacenamiento",
}


class LLMTask(BaseModel):
    fase: Literal["previa", "corte", "activa", "pasiva", "almacenamiento"]
    texto: str = Field(description="Instrucción concreta, nombrando ingredientes y recetas.")
    minutos: int = Field(description="Minutos realistas, respetando los tiempos de los pasos originales.")
    recetas: List[str] = Field(description='Refs de las recetas a las que aplica, ej. ["r1", "r3"].')


class LLMSession(BaseModel):
    session_id: int
    tareas: List[LLMTask] = Field(description="En el orden en que se ejecutan.")


class LLMPlan(BaseModel):
    sesiones: List[LLMSession]


SYSTEM_PROMPT = """Eres un chef experto en meal prep (batch-cooking). Recibes sesiones de cocina en JSON y devuelves las tareas de cada sesión.

Clasifica CADA tarea en exactamente una fase según esta tabla. Si dudas, usa la regla de la columna "criterio".

| fase | criterio | ejemplos | minutos |
|---|---|---|---|
| previa | espera de más de 1 hora que se deja lista el día anterior | remojar legumbres, marinar >1h, descongelar, cuajar gelatina toda la noche | solo el trabajo de la persona (2-10), no la espera |
| corte | sin calor, con cuchillo, rallador, licuadora, balanza o bowl | picar, pelar, rallar, medir, pesar, marinar <1h, mezclar masas, licuar, armar aderezos | 1-2 por verdura chica (ajo, cebolla), 3-5 por verdura grande o por 500 g de proteína, 1 por ingrediente a medir, 3-5 por mezcla o licuado |
| activa | con calor y la persona tiene que estar ahí (voltear, revolver, sacar tandas) | sartén, plancha, wafflera, freír, saltear, sofreír, hervir vigilando | el tiempo de cocción de los pasos x número de tandas |
| pasiva | con calor y se cocina sola; se pone un temporizador | horno, air fryer, Ninja, olla a presión, olla lenta, arrocera, hervir tapado | el tiempo exacto de los pasos (si dice "hornear 40 min", son 40) |
| almacenamiento | la comida ya está hecha, o solo falta que enfríe o cuaje en la nevera/congelador | enfriar, meter a cuajar o congelar, porcionar, etiquetar, guardar; qué terminar el día de consumo | 2 por recipiente; la espera en nevera NO cuenta |

Hornear o usar air fryer SIEMPRE es "pasiva", aunque sea parte de una receta con pasos activos.
Refrigerar, cuajar, congelar o enfriar NUNCA es "pasiva": es "almacenamiento" con 2 minutos (lo que toma meterlo a la nevera).
Una tarea = una fila de la tabla. Si una receta pide "mezclar la masa y cocinar en sartén", son DOS tareas: la mezcla en "corte" y la cocción en "activa". Mezclar y hornear: "corte" + "pasiva".

Reglas:
1. Agrupa por técnica, no por receta: una sola tarea "Picar 3 cebollas (para Pollo al curry y Lentejas)" usando el campo "recetas" de cada ingrediente. Si dos recetas comparten un paso de cocción, hazlo junto.
   Cada tarea es UNA acción (picar, licuar, hornear, marinar...), aunque aplique a varias recetas; no encadenes acciones distintas en la misma tarea. Una sesión suele necesitar de 2 a 3 tareas por receta; texto de 1-2 frases.
   En "texto" nombra las recetas por su nombre; las refs (r1, r2) van solo en el campo "recetas".
2. Cada receta se cocina UNA vez para todas sus porciones ("porciones" y "para" indican cuántas y para cuándo).
3. Arranca primero lo pasivo y haz lo activo mientras espera; dilo en el texto ("mientras el horno trabaja, ...").
4. Nombra cada ingrediente que haya que cortar, pelar o medir; nunca "los vegetales" o "los condimentos".
5. No omitas pasos de las instrucciones originales (marinar, reposar, precalentar, pelar).
6. Nunca "servir". Lo que pierde calidad hecho antes (bebidas calientes, huevos pochados, tostadas, crocantes): prepara solo lo adelantable y agrega una tarea de almacenamiento que diga qué terminar el día de consumo.
7. Toda receta debe aparecer en al menos una tarea.
8. Calcula los minutos con la tabla y los pasos originales. NUNCA los acortes para que quepa en "minutos_disponibles": si no alcanza, el sistema se lo avisa a la persona."""


def _fmt(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


class MealPrepPlanner:
    def __init__(self):
        self.llm = get_llm()
        if self.llm:
            # get_llm() crea una instancia nueva; con 0.7 compactaba todo en pocas tareas enormes
            self.llm.temperature = 0.2

    @staticmethod
    def _session_input(session: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Arma el JSON compacto que ve el LLM y el mapa ref -> recipe_id real.
        Una receta repetida en la sesión aparece una sola vez con sus porciones,
        y cada ingrediente dice a qué recetas pertenece.
        """
        recipes: Dict[Any, Dict[str, Any]] = {}
        ingredients: Dict[tuple, Dict[str, Any]] = {}

        for meal in session.get("recipes", []):
            rid = meal.get("recipe_id")
            if rid not in recipes:
                recipes[rid] = {
                    "ref": f"r{len(recipes) + 1}",
                    "nombre": meal.get("nombre") or "Sin nombre",
                    "porciones": 0,
                    "para": [],
                    "pasos": meal.get("instructions", []),
                }
            recipe = recipes[rid]
            recipe["porciones"] += 1
            recipe["para"].append(f"día {meal.get('day')} {meal.get('meal_type')}")

            for ing in meal.get("ingredients", []):
                raw_name = ing.get("name", "")
                name = normalize_ingredient_name(raw_name) or raw_name.lower().strip()
                if not name:
                    continue
                amount, unit = parse_amount_str(ing.get("amount", ""))
                entry = ingredients.setdefault((name, unit), {"amount": 0, "recetas": []})
                entry["amount"] += amount
                if recipe["ref"] not in entry["recetas"]:
                    entry["recetas"].append(recipe["ref"])

        payload = {
            "session_id": session.get("session_id"),
            "minutos_disponibles": session.get("available_minutes"),
            "recetas": list(recipes.values()),
            "ingredientes": [
                {
                    "nombre": name,
                    "cantidad": f"{round(e['amount'], 2):g} {unit}".strip() if e["amount"] > 0 else None,
                    "recetas": e["recetas"],
                }
                for (name, unit), e in ingredients.items()
            ],
        }
        refs = {r["ref"]: (rid, r["nombre"]) for rid, r in recipes.items()}
        return payload, refs

    def generate(self, sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.llm:
            raise ValueError("El LLM no está configurado (falta GEMINI_API_KEY).")

        inputs = {s.get("session_id"): self._session_input(s) for s in sessions}
        payload = [p for p, _ in inputs.values()]

        plan: LLMPlan = self.llm.with_structured_output(LLMPlan).invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ])
        if plan is None:
            raise ValueError("El LLM no devolvió un plan de mealprep válido.")

        by_id = {s.session_id: s for s in plan.sesiones}
        available = {s.get("session_id"): s.get("available_minutes") for s in sessions}
        result = []
        for session_id, (_, refs) in inputs.items():
            llm_session = by_id.get(session_id)
            tasks = llm_session.tareas if llm_session else []
            result.append(self._to_response(session_id, tasks, refs, available.get(session_id)))
        return {"sessions": result}

    @staticmethod
    def _to_response(session_id, tasks: List[LLMTask], refs: Dict[str, tuple], available_minutes) -> Dict[str, Any]:
        """
        Convierte las tareas del LLM al contrato del frontend: fases en orden fijo,
        ids determinísticos, tiempo total recalculado y warnings calculados aquí
        (el LLM inventaba el total, ej. decía 115 cuando sus tareas sumaban 235).
        """
        # El LLM a veces pone "refrigerar 3 h" como cocción pasiva, y eso inflaba el
        # total y la sugerencia de partir la sesión. Esperar en nevera no ocupa a nadie.
        # ponytail: por palabra clave; si aparecen falsos positivos, pasar a un campo del esquema.
        for t in tasks:
            if t.fase == "pasiva" and re.search(r"refriger|cuaj|congel|enfri|nevera", t.texto, re.I):
                t.fase, t.minutos = "almacenamiento", min(t.minutos, 2)

        phases = []
        for p_idx, (key, name) in enumerate(PHASES.items(), start=1):
            phase_tasks = [t for t in tasks if t.fase == key]
            if not phase_tasks:
                continue
            phases.append({
                "phase_name": name,
                "tasks": [
                    {
                        "id": f"s{session_id}-p{p_idx}-t{t_idx}",
                        "text": t.texto,
                        "estimated_minutes": max(0, t.minutos),
                        "recipe_ids": [refs[r][0] for r in t.recetas if r in refs],
                    }
                    for t_idx, t in enumerate(phase_tasks, start=1)
                ],
            })

        hands_on = sum(max(0, t.minutos) for t in tasks if t.fase not in ("previa", "pasiva"))
        longest_passive = max((t.minutos for t in tasks if t.fase == "pasiva"), default=0)
        # ponytail: asume que la cocción pasiva corre en paralelo con el trabajo
        # activo; si el LLM no la solapa bien, el total real será mayor.
        total = max(hands_on, longest_passive)

        warnings = []
        covered = {r for t in tasks for r in t.recetas}
        missing = [name for ref, (_, name) in refs.items() if ref not in covered]
        if missing:
            warnings.append(f"El plan no incluyó: {', '.join(missing)}. Vuelve a generarlo.")
        if available_minutes and total > int(available_minutes):
            available_minutes = int(available_minutes)
            warnings.append(
                f"El mealprep de estos días toma ~{_fmt(total)} y tienes {_fmt(available_minutes)}. "
                f"Puedes hacerlo todo en una sesión de {_fmt(total)} o partirlo en una sesión de "
                f"{_fmt(available_minutes)} y otra de ~{_fmt(total - available_minutes)}."
            )

        return {
            "session_id": session_id,
            "estimated_total_minutes": total,
            "warning": " ".join(warnings) or None,
            "phases": phases,
        }
