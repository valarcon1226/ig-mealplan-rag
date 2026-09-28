import json
import re
from typing import Any, Dict, List

from ingredient_normalizer import normalize_ingredient_name, parse_amount_str
from rag_chatbot import get_llm
from langchain_core.messages import SystemMessage, HumanMessage


class MealPrepPlanner:
    def __init__(self):
        self.llm = get_llm()

    def _dedupe_ingredients(self, recipes: List[Dict[str, Any]]) -> str:
        aggregated: Dict[str, Dict[str, Any]] = {}
        for recipe in recipes:
            for ing in recipe.get("ingredients", []):
                raw_name = ing.get("name", "")
                normalized = normalize_ingredient_name(raw_name)
                key = normalized or raw_name.lower().strip()
                if not key:
                    continue
                amount, unit = parse_amount_str(ing.get("amount", ""))
                if key in aggregated and aggregated[key]["unit"] == unit:
                    aggregated[key]["amount"] += amount
                else:
                    aggregated[key] = {"amount": amount, "unit": unit}

        lines = []
        for name, data in aggregated.items():
            if data["amount"] > 0:
                lines.append(f"- {name}: {data['amount']} {data['unit']}".strip())
            else:
                lines.append(f"- {name}")
        return "\n".join(lines) if lines else "- (sin ingredientes)"

    def _build_session_context(self, session: Dict[str, Any]) -> str:
        recipes = session.get("recipes", [])
        ingredients_block = self._dedupe_ingredients(recipes)

        recipes_block = ""
        for recipe in recipes:
            instructions = recipe.get("instructions", [])
            instructions_text = "\n".join(
                f"    {i + 1}. {step}" for i, step in enumerate(instructions)
            )
            recipes_block += (
                f"\n  Receta: {recipe.get('nombre', 'Sin nombre')} "
                f"(ID {recipe.get('recipe_id')}, día {recipe.get('day')}, "
                f"{recipe.get('meal_type')})\n{instructions_text}\n"
            )

        return (
            f"--- SESIÓN {session.get('session_id')} "
            f"(disponible: {session.get('available_minutes')} minutos) ---\n"
            f"Ingredientes combinados de todas las recetas de esta sesión:\n{ingredients_block}\n"
            f"Recetas e instrucciones originales:{recipes_block}"
        )

    def generate(self, sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
        sessions_context = "\n\n".join(
            self._build_session_context(s) for s in sessions
        )

        prompt = f"""Eres un experto en organización de cocina (meal prep) y batch-cooking.
Tu tarea es armar un plan de cocina eficiente para cada sesión, agrupando tareas
similares entre recetas (ej. cortar todos los vegetales juntos, aprovechar el horno
para varias recetas a la vez) para minimizar el tiempo total en cocina.

Para cada sesión debes devolver fases, en este orden fijo cuando aplique:
0. "Preparación previa (día anterior)" -- SOLO pasos con esperas largas que no
   caben en la sesión: remojar legumbres toda la noche, marinar más de 1 hora,
   descongelar, fermentar. No los metas en otras fases como si tomaran minutos.
1. "Corte y preparación"
2. "Cocción activa" (estufa, sartén, algo que requiere atención constante)
3. "Cocción pasiva" (horno, olla, olla a presión, algo que se deja cocinando solo)
4. "Ensamblaje y almacenamiento"

REGLAS DE BATCH-COOKING (esto es lo que hace útil el plan):
- Agrupa por TÉCNICA, no por receta: una sola tarea "Picar cebolla (para
  recetas X, Y, Z)" en vez de una tarea de corte por cada receta. Lo mismo al
  cocinar: si dos recetas usan sartén con cebolla sofrita, hazlo junto.
- Ordena para aprovechar esperas: lo que va al horno u olla a presión se
  arranca PRIMERO, y mientras se cocina se hacen las tareas activas. Indícalo
  en el texto ("mientras el horno trabaja, ...").
- Un meal prep NO sirve comida: nunca escribas "servir". En "Ensamblaje y
  almacenamiento" indica enfriar, porcionar y guardar en recipientes
  etiquetados con el día y comida, y si va a nevera o congelador.
- Lo que pierde calidad hecho con anticipación (bebidas calientes, café,
  huevos pochados, tostadas, cosas crocantes): en la sesión deja solo lo
  adelantable (medir secos, porcionar, preparar bases) y agrega una tarea en
  "Ensamblaje y almacenamiento" que diga qué terminar el día de consumo.
- estimated_minutes debe ser realista y respetar los tiempos de las
  instrucciones originales (si dice "hornear 40 minutos", son 40). No
  inventes tiempos cortos para que el plan quepa.

REGLA CRÍTICA DE COMPLETITUD (no la incumplas para acortar el plan):
- CADA receta de la sesión debe quedar representada en al menos una tarea de
  alguna fase. Antes de responder, revisa que ningún recipe_id de los
  indicados abajo quede fuera de todas las tareas.
- En "Corte y preparación", menciona EXPLÍCITAMENTE por su nombre cada
  ingrediente de la lista combinada que requiera cortar, pelar, picar o medir
  -- no los resumas con frases genéricas como "los vegetales" o "los
  condimentos". Si varias recetas comparten un ingrediente, agrúpalo en una
  sola tarea, pero nombra cada ingrediente individual dentro del texto.
- No omitas pasos importantes de las instrucciones originales (marinar,
  dejar reposar, precalentar el horno, pelar, etc.) solo por acortar el plan
  -- es preferible una tarea más larga y completa que una corta que se salte
  pasos.

Cada tarea debe indicar cuánto tiempo estimado toma (estimated_minutes) y a qué
recetas aplica (recipe_ids, usando los IDs indicados en cada receta).

Si la suma de tiempos estimados de una sesión supera los minutos disponibles de esa
sesión, agrega un "warning" corto explicando qué no alcanza a cubrirse o qué se
podría mover a otra sesión. Si alcanza bien, "warning" debe ser null.

SESIONES A PLANEAR:
{sessions_context}

Devuelve tu respuesta como un objeto JSON estricto con este formato exacto:
{{
  "sessions": [
    {{
      "session_id": 1,
      "estimated_total_minutes": 105,
      "warning": null,
      "phases": [
        {{
          "phase_name": "Corte y preparación",
          "tasks": [
            {{
              "id": "s1-p1-t1",
              "text": "Corta 2 cebollas y 500g de pollo en cubos",
              "estimated_minutes": 15,
              "recipe_ids": [12, 15]
            }}
          ]
        }}
      ]
    }}
  ]
}}
NO agregues texto antes ni después del JSON. Sólo devuelve el JSON.
"""

        messages = [
            SystemMessage(
                content="Eres una API de planeamiento de cocina. Responde solo con JSON válido."
            ),
            HumanMessage(content=prompt),
        ]

        response = self.llm.invoke(messages)
        text_resp = response.content

        print("MEALPREP RAW RESP:", text_resp)

        if isinstance(text_resp, list):
            text_resp = (
                text_resp[0].get("text", "")
                if isinstance(text_resp[0], dict)
                else str(text_resp[0])
            )
        elif not isinstance(text_resp, str):
            text_resp = str(text_resp)

        match = re.search(r"\{[\s\S]*\}", text_resp)
        if not match:
            raise ValueError(
                f"No se pudo parsear el plan de mealprep. Respuesta raw: {text_resp}"
            )

        result = json.loads(match.group(0))
        available = {s.get("session_id"): s.get("available_minutes") for s in sessions}
        for s in result.get("sessions", []):
            self._recompute_timing(s, available.get(s.get("session_id")))
        return result

    @staticmethod
    def _recompute_timing(session: Dict[str, Any], available_minutes) -> None:
        """
        El LLM inventa estimated_total_minutes (ej. decía 115 cuando sus tareas
        sumaban 235), así que se recalcula desde las tareas y se genera el
        warning aquí si no alcanza el tiempo.
        """
        hands_on = 0
        longest_passive = 0
        for phase in session.get("phases", []):
            name = phase.get("phase_name", "").lower()
            minutes = [int(t.get("estimated_minutes") or 0) for t in phase.get("tasks", [])]
            if "previa" in name:
                continue  # se hace el día anterior, no cuenta en la sesión
            if "pasiva" in name:
                longest_passive = max([longest_passive, *minutes])
            else:
                hands_on += sum(minutes)
        # ponytail: asume que la cocción pasiva corre en paralelo con el trabajo
        # activo; si el LLM no la solapa bien, el total real será mayor.
        total = max(hands_on, longest_passive)
        session["estimated_total_minutes"] = total
        if available_minutes and total > int(available_minutes):
            session["warning"] = session.get("warning") or (
                f"El plan toma ~{total} min y tienes {available_minutes}. "
                "Mueve alguna receta a otra sesión o agrega tiempo."
            )
        elif available_minutes:
            session["warning"] = None
