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
1. "Corte y preparación"
2. "Cocción activa" (estufa, sartén, algo que requiere atención constante)
3. "Cocción pasiva" (horno, olla, algo que se deja cocinando solo)
4. "Ensamblaje y almacenamiento"

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

        return json.loads(match.group(0))
