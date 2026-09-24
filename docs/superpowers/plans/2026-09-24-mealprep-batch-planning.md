# Mealprep Batch Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Mealprep" feature that takes the meal plan already generated in the Planner (any number of days) and produces a session-based batch-cooking checklist (fases + tareas agrupadas + tiempos estimados), with progress saved client-side so it survives closing the app.

**Architecture:** Deterministic context assembly (dedupe/normalize ingredients per session) + a single LLM call per generation, following the exact pattern `rag_planner.py` already uses (`get_llm()`, JSON-in-prompt, regex extraction). New stateless FastAPI endpoint, new React page, all progress state persisted client-side via `idb-keyval` (same mechanism as `currentMealPlan`) — no new DB tables.

**Tech Stack:** FastAPI + LangChain (`ChatGoogleGenerativeAI`) on the backend, React + TypeScript + `idb-keyval` on the frontend, Express (`server.ts`) as the dev/prod proxy layer.

**Spec:** `docs/documentacion/mealprep-batch-planning.md`

## Global Constraints

- Este repo no tiene pytest ni vitest configurados (confirmado: no hay `pytest.ini`, `conftest.py` propio, ni script de test en `frontend/package.json`). No se introduce infraestructura de testing nueva — la verificación de cada tarea es manual (scripts sueltos con `python -c`, `curl`, y comprobación en el navegador), igual que el resto del proyecto.
- Backend: seguir el estilo de tipado suelto (`dict`/`list` en vez de genéricos de `typing`) que ya usa `ig_recetas.py` en sus `BaseModel` (ver `MealPlanRequest`).
- El backend FastAPI corre en `127.0.0.1:8001` (variable `vpsUrl` hardcodeada en `server.ts`); Express (`server.ts`) sirve la SPA y hace de proxy hacia él.
- Todo el estado de Mealprep (plan generado + checks completados) vive client-side en `idb-keyval`, bajo la key `app_mealprep`. No se crea ninguna tabla nueva en `backend/models.py`.
- Implementar cada tarea usando la skill `ponytail` (nivel `full`): la solución más simple que funcione, sin abstracciones que el alcance no pide.
- Mealprep aplica a **cualquier plan generado**, sin asumir 1 o 7 días — la cantidad de sesiones nunca supera la cantidad real de días del plan (`planDays.length`).

---

## Task 1: Backend — `MealPrepPlanner` (dedupe de ingredientes + prompt + parseo)

**Files:**
- Create: `backend/mealprep_planner.py`

**Interfaces:**
- Produces: `class MealPrepPlanner` con `__init__(self)` (llama `get_llm()` de `rag_chatbot`) y `generate(self, sessions: List[Dict[str, Any]]) -> Dict[str, Any]`, donde cada `session` trae `{"session_id": int, "available_minutes": int, "recipes": [{"recipe_id", "nombre", "meal_type", "day", "ingredients": [{"name","amount"}], "instructions": [str,...]}]}`. Devuelve `{"sessions": [{"session_id", "estimated_total_minutes", "warning", "phases": [{"phase_name", "tasks": [{"id","text","estimated_minutes","recipe_ids"}]}]}]}`.
- Consumes: `normalize_ingredient_name` y `parse_amount_str` de `backend/ingredient_normalizer.py`, `get_llm()` de `backend/rag_chatbot.py`.

- [ ] **Step 1: Escribir `backend/mealprep_planner.py`**

```python
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
```

- [ ] **Step 2: Verificación manual del dedupe (sin llamar al LLM)**

Desde `backend/` (con el venv activo):

```bash
python -c "
from mealprep_planner import MealPrepPlanner
p = MealPrepPlanner()
recipes = [
    {'ingredients': [{'name': 'cebolla', 'amount': '100 g'}]},
    {'ingredients': [{'name': 'cebollas', 'amount': '50 g'}]},
]
print(p._dedupe_ingredients(recipes))
"
```

Esperado: una sola línea, algo como `- cebolla: 150.0 g` (confirma que 'cebolla' y
'cebollas' se normalizan al mismo nombre vía `ingredient_normalizer` y que las
cantidades con la misma unidad se suman en vez de listarse por separado).

- [ ] **Step 3: Commit**

```bash
git add backend/mealprep_planner.py
git commit -m "feat: add MealPrepPlanner for batch-cooking plan generation"
```

---

## Task 2: Backend — endpoint `POST /api/mealprep/generate`

**Files:**
- Modify: `backend/ig_recetas.py` (agregar justo después de `generate_mealplan`, antes del comentario `# --- PANTRY & GROCERY LIST ENDPOINTS ---`, alrededor de la línea 950)

**Interfaces:**
- Consumes: `MealPrepPlanner` de `backend/mealprep_planner.py` (Task 1).
- Produces: endpoint HTTP `POST /api/mealprep/generate` que recibe `{"sessions": [...]}` y devuelve el JSON de `MealPrepPlanner.generate(...)`, o `400` con `{"detail": "..."}` si falla el parseo.

- [ ] **Step 1: Agregar el modelo de request y el endpoint**

En `backend/ig_recetas.py`, justo después del cierre de `generate_mealplan` (después de `return result` en la línea ~949) y antes de `# --- PANTRY & GROCERY LIST ENDPOINTS ---`:

```python
class MealPrepRequest(BaseModel):
    sessions: list

@app.post("/api/mealprep/generate")
def generate_mealprep(request: MealPrepRequest):
    from mealprep_planner import MealPrepPlanner
    planner = MealPrepPlanner()

    try:
        result = planner.generate(request.sessions)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result
```

- [ ] **Step 2: Verificación manual end-to-end**

Levanta el backend desde `backend/` (con el venv activo):

```bash
python -m uvicorn ig_recetas:app --reload --port 8001
```

En otra terminal:

```bash
curl -s -X POST http://127.0.0.1:8001/api/mealprep/generate \
  -H "Content-Type: application/json" \
  -d '{
    "sessions": [
      {
        "session_id": 1,
        "available_minutes": 90,
        "recipes": [
          {
            "recipe_id": 1,
            "nombre": "Pollo al horno con vegetales",
            "meal_type": "almuerzo",
            "day": 1,
            "ingredients": [{"name": "pollo", "amount": "500 g"}, {"name": "cebolla", "amount": "100 g"}],
            "instructions": ["Precalienta el horno a 200C", "Corta el pollo y la cebolla", "Hornea 25 minutos"]
          }
        ]
      }
    ]
  }'
```

Esperado: `200 OK` con un JSON que trae la llave `sessions`, y dentro `phases` con al
menos una fase y una tarea. Si `GEMINI_API_KEY` no está seteada en el entorno del
backend, la llamada falla con `400` (mismo comportamiento que ya tiene
`/api/mealplan/generate` en ese caso — no se agrega manejo especial).

- [ ] **Step 3: Commit**

```bash
git add backend/ig_recetas.py
git commit -m "feat: add POST /api/mealprep/generate endpoint"
```

---

## Task 3: Frontend proxy — passthrough en `server.ts`

**Files:**
- Modify: `frontend/server.ts` (agregar junto a la ruta `/api/mealplan/generate`, alrededor de la línea 218)

**Interfaces:**
- Consumes: endpoint backend `POST http://127.0.0.1:8001/api/mealprep/generate` (Task 2).
- Produces: ruta Express `POST /api/mealprep/generate` que el frontend puede llamar directamente (el proxy genérico de `server.ts` rompe el prefijo `/api`, por eso hace falta esta ruta explícita — mismo motivo por el que ya existe para `/api/pantry`).

- [ ] **Step 1: Agregar la ruta passthrough**

En `frontend/server.ts`, justo después del cierre del handler de `/api/mealplan/generate` (después de la línea 218):

```typescript
  app.post("/api/mealprep/generate", async (req, res) => {
    try {
      const vpsUrl = "http://127.0.0.1:8001";
      const response = await fetch(`${vpsUrl}/api/mealprep/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "ngrok-skip-browser-warning": "true"
        },
        body: JSON.stringify(req.body)
      });
      const data = await response.json();
      res.status(response.status).json(data);
    } catch (error: any) {
      console.error("Mealprep Error:", error);
      res.status(500).json({ error: "Failed to generate mealprep: " + error.message });
    }
  });
```

- [ ] **Step 2: Verificación manual**

Con el backend corriendo (`python -m uvicorn ig_recetas:app --reload --port 8001` desde
`backend/`), levanta el frontend desde `frontend/`:

```bash
npm run dev
```

Repite el mismo `curl` del Task 2 pero apuntando al puerto del frontend (revisa en la
consola de `npm run dev` en qué puerto quedó, normalmente 5173 con Vite o el que
exponga `server.ts`):

```bash
curl -s -X POST http://localhost:5173/api/mealprep/generate \
  -H "Content-Type: application/json" \
  -d '{"sessions":[{"session_id":1,"available_minutes":90,"recipes":[{"recipe_id":1,"nombre":"Test","meal_type":"almuerzo","day":1,"ingredients":[{"name":"cebolla","amount":"100 g"}],"instructions":["Corta la cebolla"]}]}]}'
```

Esperado: mismo JSON con `sessions` que devolvió el backend directamente en el Task 2.

- [ ] **Step 3: Commit**

```bash
git add frontend/server.ts
git commit -m "feat: proxy POST /api/mealprep/generate through the frontend server"
```

---

## Task 4: Frontend — tipos TypeScript para Mealprep

**Files:**
- Modify: `frontend/src/lib/types.ts`

**Interfaces:**
- Produces: `MealprepTaskResult`, `MealprepPhaseResult`, `MealprepSessionResult`, `MealprepGenerateResponse`, `MealprepCache` — usados por `mealprepStorage.ts` (Task 5) y `Mealprep.tsx` (Task 6/7).

- [ ] **Step 1: Agregar los tipos al final de `frontend/src/lib/types.ts`**

```typescript
export type MealprepTaskResult = {
  id: string;
  text: string;
  estimated_minutes: number;
  recipe_ids: number[];
};

export type MealprepPhaseResult = {
  phase_name: string;
  tasks: MealprepTaskResult[];
};

export type MealprepSessionResult = {
  session_id: number;
  estimated_total_minutes: number;
  warning: string | null;
  phases: MealprepPhaseResult[];
};

export type MealprepGenerateResponse = {
  sessions: MealprepSessionResult[];
};

export type MealprepCache = {
  planFingerprint: string;
  sessions: MealprepSessionResult[];
  completedTaskIds: string[];
};
```

- [ ] **Step 2: Verificación manual (type-check)**

Desde `frontend/`:

```bash
npm run lint
```

Esperado: `tsc --noEmit` termina sin errores relacionados a `types.ts` (los tipos
nuevos no se usan todavía en ningún lado, así que no deberían generar ningún error).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat: add TypeScript types for mealprep plan and cache"
```

---

## Task 5: Frontend — helper de almacenamiento client-side (`mealprepStorage.ts`)

**Files:**
- Create: `frontend/src/lib/mealprepStorage.ts`

**Interfaces:**
- Consumes: `get`/`set`/`del` de `idb-keyval` (ya es dependencia del proyecto), tipos `MealprepCache` y `MealprepGenerateResponse` del Task 4.
- Produces: `buildPlanFingerprint(plan: any): string`, `loadMealprepCache(currentFingerprint: string): Promise<MealprepCache | null>`, `saveMealprepCache(cache: MealprepCache): Promise<void>`, `clearMealprepCache(): Promise<void>`, `newMealprepCache(fingerprint: string, response: MealprepGenerateResponse): MealprepCache`. Usados por `Mealprep.tsx` (Task 6/7).

- [ ] **Step 1: Escribir `frontend/src/lib/mealprepStorage.ts`**

```typescript
import { get, set, del } from 'idb-keyval';
import { MealprepCache, MealprepGenerateResponse } from './types';

const CACHE_KEY = 'app_mealprep';

export function buildPlanFingerprint(plan: any): string {
  if (!plan) return '';
  const days = Array.isArray(plan) ? plan : [plan];
  const shape = days.map((d: any) => ({
    day: d.day,
    meals: (d.meals || []).map((m: any) => ({ meal_type: m.meal_type, recipe_id: m.recipe_id })),
  }));
  return JSON.stringify(shape);
}

export async function loadMealprepCache(currentFingerprint: string): Promise<MealprepCache | null> {
  const cached = (await get(CACHE_KEY)) as MealprepCache | undefined;
  if (!cached) return null;
  if (cached.planFingerprint !== currentFingerprint) {
    await del(CACHE_KEY);
    return null;
  }
  return cached;
}

export async function saveMealprepCache(cache: MealprepCache): Promise<void> {
  await set(CACHE_KEY, cache);
}

export async function clearMealprepCache(): Promise<void> {
  await del(CACHE_KEY);
}

export function newMealprepCache(fingerprint: string, response: MealprepGenerateResponse): MealprepCache {
  return { planFingerprint: fingerprint, sessions: response.sessions, completedTaskIds: [] };
}
```

- [ ] **Step 2: Verificación manual (type-check)**

Desde `frontend/`:

```bash
npm run lint
```

Esperado: sin errores nuevos (el archivo no se usa todavía en ningún componente, así
que solo se valida que compila).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/mealprepStorage.ts
git commit -m "feat: add client-side mealprep cache helpers using idb-keyval"
```

---

## Task 6: Frontend — página `Mealprep.tsx` (cuestionario + llamada al backend)

**Files:**
- Create: `frontend/src/pages/Mealprep.tsx`
- Modify: `frontend/src/App.tsx` (agregar ruta `/mealprep`)

**Interfaces:**
- Consumes: `useStore()` (`currentMealPlan`) de `frontend/src/lib/store.tsx`; `buildPlanFingerprint`, `loadMealprepCache`, `saveMealprepCache`, `newMealprepCache` de `frontend/src/lib/mealprepStorage.ts` (Task 5); tipo `MealprepCache` de `frontend/src/lib/types.ts` (Task 4); endpoint `POST /api/mealprep/generate` (Task 3).
- Produces: componente `Mealprep` con estados `'loading' | 'no_plan' | 'questionnaire' | 'results'` — el estado `'results'` y su UI de checklist se completan en el Task 7, acá solo queda el placeholder mínimo para poder probar el flujo de cuestionario → generación.

- [ ] **Step 1: Escribir `frontend/src/pages/Mealprep.tsx`**

```tsx
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../lib/store';
import { ChefHat, Loader2, ArrowLeft } from 'lucide-react';
import {
  buildPlanFingerprint,
  loadMealprepCache,
  saveMealprepCache,
  newMealprepCache,
} from '../lib/mealprepStorage';
import { MealprepCache } from '../lib/types';

type ViewState = 'loading' | 'no_plan' | 'questionnaire' | 'results';

function autoSplitDays(numDays: number, numSessions: number): number[][] {
  const base = Math.floor(numDays / numSessions);
  const remainder = numDays % numSessions;
  const groups: number[][] = [];
  let dayIndex = 0;
  for (let s = 0; s < numSessions; s++) {
    const size = base + (s < remainder ? 1 : 0);
    const group: number[] = [];
    for (let i = 0; i < size; i++) {
      group.push(dayIndex);
      dayIndex++;
    }
    groups.push(group);
  }
  return groups;
}

const DAY_LABELS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

export default function Mealprep() {
  const { currentMealPlan } = useStore();
  const navigate = useNavigate();

  const [view, setView] = useState<ViewState>('loading');
  const [cache, setCache] = useState<MealprepCache | null>(null);
  const [loading, setLoading] = useState(false);

  const planDays: any[] = Array.isArray(currentMealPlan)
    ? currentMealPlan
    : currentMealPlan
    ? [currentMealPlan]
    : [];
  const numDays = planDays.length;
  const fingerprint = buildPlanFingerprint(currentMealPlan);

  const [numSessions, setNumSessions] = useState(1);
  const [splitMode, setSplitMode] = useState<'auto' | 'manual'>('auto');
  const [manualAssignment, setManualAssignment] = useState<number[]>([]);
  const [minutesPerSession, setMinutesPerSession] = useState<number[]>([60]);

  const resetQuestionnaire = () => {
    setNumSessions(1);
    setSplitMode('auto');
    setManualAssignment(new Array(numDays).fill(0));
    setMinutesPerSession([60]);
  };

  useEffect(() => {
    const init = async () => {
      if (numDays === 0) {
        setView('no_plan');
        return;
      }
      const stored = await loadMealprepCache(fingerprint);
      if (stored) {
        setCache(stored);
        setView('results');
      } else {
        resetQuestionnaire();
        setView('questionnaire');
      }
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fingerprint, numDays]);

  const changeNumSessions = (n: number) => {
    setNumSessions(n);
    setMinutesPerSession(new Array(n).fill(60));
    setManualAssignment(new Array(numDays).fill(0));
  };

  const assignDayToSession = (dayIdx: number, sessionIdx: number) => {
    setManualAssignment((prev) => {
      const next = [...prev];
      next[dayIdx] = sessionIdx;
      return next;
    });
  };

  const updateMinutes = (sessionIdx: number, minutes: number) => {
    setMinutesPerSession((prev) => {
      const next = [...prev];
      next[sessionIdx] = minutes;
      return next;
    });
  };

  const generateMealprep = async () => {
    let sessionsDays: number[][];
    if (numDays === 1) {
      sessionsDays = [[0]];
    } else if (splitMode === 'auto') {
      sessionsDays = autoSplitDays(numDays, numSessions);
    } else {
      sessionsDays = Array.from({ length: numSessions }, (_, s) =>
        manualAssignment
          .map((sessionIdx, dayIdx) => ({ sessionIdx, dayIdx }))
          .filter((x) => x.sessionIdx === s)
          .map((x) => x.dayIdx)
      );
    }

    const payload = {
      sessions: sessionsDays.map((dayIndices, i) => ({
        session_id: i + 1,
        available_minutes: minutesPerSession[i] ?? 60,
        recipes: dayIndices.flatMap((dayIdx) => {
          const day = planDays[dayIdx];
          return (day.meals || []).map((m: any) => ({
            recipe_id: m.recipe_id,
            nombre: m.nombre,
            meal_type: m.meal_type,
            day: day.day ?? dayIdx + 1,
            ingredients: m.ingredients || [],
            instructions: m.instructions || [],
          }));
        }),
      })),
    };

    setLoading(true);
    try {
      const res = await fetch('/api/mealprep/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.error || data.detail || 'No se pudo generar el mealprep');
        return;
      }
      const newCache = newMealprepCache(fingerprint, data);
      await saveMealprepCache(newCache);
      setCache(newCache);
      setView('results');
    } catch (err) {
      console.error(err);
      alert('No se pudo generar el mealprep');
    } finally {
      setLoading(false);
    }
  };

  if (view === 'loading') {
    return (
      <div className="p-4 max-w-lg mx-auto pt-8 flex justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-orange-500" />
      </div>
    );
  }

  if (view === 'no_plan') {
    return (
      <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 pb-20">
        <header className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Mealprep</h1>
        </header>
        <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-8 text-center">
          <ChefHat className="w-12 h-12 mx-auto text-orange-500 mb-4" />
          <h2 className="font-bold text-xl mb-2">Primero genera un plan</h2>
          <p className="text-sm text-neutral-400 mb-6">
            Necesitas un plan de comidas generado en el Planner antes de armar tu sesión de mealprep.
          </p>
          <button
            onClick={() => navigate('/planner')}
            className="w-full bg-orange-500 text-black font-bold py-3 rounded-xl flex items-center justify-center gap-2"
          >
            <ArrowLeft className="w-4 h-4" /> Ir al Planner
          </button>
        </div>
      </div>
    );
  }

  if (view === 'questionnaire') {
    return (
      <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 pb-20">
        <header className="mb-4">
          <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Mealprep</h1>
          <p className="text-neutral-400 text-sm">Organicemos tu sesión de cocina.</p>
        </header>

        {numDays > 1 && (
          <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-4 space-y-4">
            <div>
              <p className="text-sm text-neutral-400 mb-2">
                ¿En cuántos días vas a cocinar? (de {numDays} días del plan)
              </p>
              <div className="flex flex-wrap gap-2">
                {Array.from({ length: numDays }, (_, i) => i + 1).map((n) => (
                  <button
                    key={n}
                    onClick={() => changeNumSessions(n)}
                    className={`w-10 h-10 rounded-lg font-bold text-sm ${
                      numSessions === n ? 'bg-orange-500 text-black' : 'bg-black border border-neutral-800 text-neutral-400'
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>

            {numSessions > 1 && (
              <div>
                <p className="text-sm text-neutral-400 mb-2">¿Cómo repartimos los días?</p>
                <div className="flex bg-black rounded-lg p-1 border border-neutral-800">
                  <button
                    onClick={() => setSplitMode('auto')}
                    className={`flex-1 py-2 rounded-md text-sm font-bold ${
                      splitMode === 'auto' ? 'bg-orange-500 text-black' : 'text-neutral-400'
                    }`}
                  >
                    Automático
                  </button>
                  <button
                    onClick={() => setSplitMode('manual')}
                    className={`flex-1 py-2 rounded-md text-sm font-bold ${
                      splitMode === 'manual' ? 'bg-orange-500 text-black' : 'text-neutral-400'
                    }`}
                  >
                    Yo elijo
                  </button>
                </div>
              </div>
            )}

            {numSessions > 1 && splitMode === 'manual' && (
              <div className="space-y-2">
                {planDays.map((day, dayIdx) => (
                  <div
                    key={dayIdx}
                    className="flex items-center justify-between bg-black p-2 rounded-lg border border-neutral-800"
                  >
                    <span className="text-sm text-white">{DAY_LABELS[dayIdx] || `Día ${dayIdx + 1}`}</span>
                    <select
                      value={manualAssignment[dayIdx] ?? 0}
                      onChange={(e) => assignDayToSession(dayIdx, Number(e.target.value))}
                      className="bg-neutral-900 border border-neutral-800 rounded-lg text-sm text-white px-2 py-1"
                    >
                      {Array.from({ length: numSessions }, (_, s) => (
                        <option key={s} value={s}>
                          Sesión {s + 1}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-4 space-y-3">
          <p className="text-sm text-neutral-400">¿Cuántos minutos tienes disponibles en cada sesión?</p>
          {Array.from({ length: numDays === 1 ? 1 : numSessions }, (_, i) => i).map((i) => (
            <div key={i} className="flex items-center justify-between">
              <span className="text-sm text-white">Sesión {i + 1}</span>
              <input
                type="number"
                min={10}
                step={5}
                value={minutesPerSession[i] ?? 60}
                onChange={(e) => updateMinutes(i, Number(e.target.value))}
                className="w-24 bg-black border border-neutral-800 rounded-lg text-sm text-white px-2 py-1 text-right"
              />
            </div>
          ))}
        </div>

        <button
          onClick={generateMealprep}
          disabled={loading}
          className="w-full bg-orange-500 text-black font-bold py-3 rounded-xl flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : 'Generar Mealprep'}
        </button>
      </div>
    );
  }

  // view === 'results' — placeholder mínimo, se completa en el Task 7
  return (
    <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 pb-20">
      <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Mealprep</h1>
      <pre className="text-xs text-neutral-400 overflow-auto">{JSON.stringify(cache, null, 2)}</pre>
    </div>
  );
}
```

- [ ] **Step 2: Agregar la ruta en `frontend/src/App.tsx`**

Agregar el import junto a los demás `import ... from './pages/...'`:

```typescript
import Mealprep from './pages/Mealprep';
```

Y agregar la ruta dentro de `<Routes>`, junto a la de `/planner`:

```typescript
            <Route path="/mealprep" element={<Mealprep />} />
```

- [ ] **Step 3: Verificación manual en el navegador**

Con backend (`python -m uvicorn ig_recetas:app --reload --port 8001`) y frontend
(`npm run dev`) corriendo:

1. Ve a `/planner`, genera un plan diario (1 día).
2. Navega manualmente a `/mealprep` en la URL. Debe saltar directo a la pregunta de
   minutos (sin preguntar reparto de días, porque `numDays === 1`).
3. Ingresa minutos y dale a "Generar Mealprep". Debe mostrar un loading y luego el
   JSON crudo de la respuesta (placeholder del Task 7).
4. Vuelve a `/planner`, genera esta vez un plan semanal (7 días), navega a
   `/mealprep` de nuevo. Debe mostrar la pregunta de "¿en cuántos días vas a
   cocinar?" con opciones 1-7, y al elegir más de 1, el toggle Automático/Yo elijo.
5. Prueba el modo manual: asignar días a sesiones distintas y confirmar que el
   payload que se arma (revisa la pestaña Network del navegador) trae las recetas
   correctas agrupadas por sesión.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Mealprep.tsx frontend/src/App.tsx
git commit -m "feat: add Mealprep page with day-split questionnaire and generation call"
```

---

## Task 7: Frontend — checklist de resultados, resume y "+ Nuevo Mealprep"

**Files:**
- Modify: `frontend/src/pages/Mealprep.tsx` (reemplaza el placeholder del `view === 'results'` del Task 6)

**Interfaces:**
- Consumes: `clearMealprepCache` de `frontend/src/lib/mealprepStorage.ts` (Task 5, no usado todavía).
- Produces: vista de checklist completa por sesión → fase → tarea, con banner de recordatorio de Pantry, checkboxes que persisten en `idb-keyval` vía `toggleTask`, y botón "+ Nuevo Mealprep" que confirma antes de borrar el progreso.

- [ ] **Step 1: Importar `clearMealprepCache` y el ícono `RotateCcw`**

En `frontend/src/pages/Mealprep.tsx`, actualizar los imports:

```typescript
import { ChefHat, Loader2, ArrowLeft, RotateCcw } from 'lucide-react';
import {
  buildPlanFingerprint,
  loadMealprepCache,
  saveMealprepCache,
  clearMealprepCache,
  newMealprepCache,
} from '../lib/mealprepStorage';
```

- [ ] **Step 2: Agregar `toggleTask` y `startNewMealprep` antes del `return` de `view === 'loading'`**

```typescript
  const toggleTask = async (taskId: string) => {
    if (!cache) return;
    const isCompleted = cache.completedTaskIds.includes(taskId);
    const updated: MealprepCache = {
      ...cache,
      completedTaskIds: isCompleted
        ? cache.completedTaskIds.filter((id) => id !== taskId)
        : [...cache.completedTaskIds, taskId],
    };
    setCache(updated);
    await saveMealprepCache(updated);
  };

  const startNewMealprep = async () => {
    if (cache) {
      const confirmed = window.confirm('Esto borra el progreso del mealprep actual. ¿Continuar?');
      if (!confirmed) return;
      await clearMealprepCache();
      setCache(null);
    }
    resetQuestionnaire();
    setView('questionnaire');
  };
```

- [ ] **Step 3: Reemplazar el placeholder de `view === 'results'`**

```tsx
  // view === 'results'
  if (!cache) return null;

  return (
    <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 pb-20">
      <header className="flex justify-between items-center mb-4">
        <h1 className="text-3xl font-bold tracking-tight text-white">Mealprep</h1>
        <button
          onClick={startNewMealprep}
          className="p-2 border border-neutral-800 rounded-lg text-neutral-400 hover:text-white"
          title="Nuevo Mealprep"
        >
          <RotateCcw className="w-4 h-4" />
        </button>
      </header>

      <div className="bg-neutral-900/50 border border-neutral-800/50 rounded-xl p-4 text-sm text-neutral-300">
        Recuerda actualizar tu Pantry con lo que ya tienes en la cocina antes de
        empezar, así estas tareas reflejan lo que de verdad te falta.
      </div>

      {cache.sessions.map((session) => (
        <div key={session.session_id} className="bg-neutral-900 border border-neutral-800 rounded-2xl p-4 space-y-4">
          <div className="flex justify-between items-center">
            <h2 className="font-bold text-lg text-white">Sesión {session.session_id}</h2>
            <span className="text-xs text-neutral-500">~{session.estimated_total_minutes} min</span>
          </div>
          {session.warning && (
            <div className="bg-orange-500/10 border border-orange-500/30 rounded-lg p-3 text-xs text-orange-400">
              {session.warning}
            </div>
          )}
          {session.phases.map((phase, pIdx) => (
            <div key={pIdx}>
              <h3 className="font-bold text-xs text-neutral-400 uppercase tracking-widest mb-2">
                {phase.phase_name}
              </h3>
              <div className="space-y-2">
                {phase.tasks.map((task) => {
                  const completed = cache.completedTaskIds.includes(task.id);
                  return (
                    <label
                      key={task.id}
                      className="flex items-start gap-3 p-2 rounded-lg hover:bg-neutral-800 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={completed}
                        onChange={() => toggleTask(task.id)}
                        className="w-5 h-5 mt-0.5 accent-orange-500"
                      />
                      <span className={`text-sm ${completed ? 'line-through text-neutral-600' : 'text-white'}`}>
                        {task.text} <span className="text-neutral-500">({task.estimated_minutes} min)</span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
```

- [ ] **Step 4: Verificación manual del resume y de la invalidación de cache**

Con backend y frontend corriendo:

1. Genera un mealprep (cualquier plan). Debe mostrar el checklist real (no el JSON
   crudo del Task 6).
2. Marca 2-3 tareas. Navega a otra página (`/pantry`) y vuelve a `/mealprep`. Los
   checks deben seguir marcados (retomó el cache sin mostrar el cuestionario).
3. Recarga la página completa (F5). Los checks deben seguir marcados (confirma que
   persiste en `idb-keyval`, no solo en memoria de React).
4. Ve a `/planner` y regenera el plan (mismo tipo, diario o semanal). Vuelve a
   `/mealprep`: debe mostrar el cuestionario de entrada de cero, no el checklist
   viejo (confirma que la invalidación por fingerprint funciona).
5. Genera un mealprep nuevo, dale click al botón de "Nuevo Mealprep" (ícono
   `RotateCcw`): debe pedir confirmación antes de borrar el progreso.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Mealprep.tsx
git commit -m "feat: add mealprep results checklist with resume and reset"
```

---

## Task 8: Frontend — botón "Mealprep" en `Planner.tsx`

**Files:**
- Modify: `frontend/src/pages/Planner.tsx`

**Interfaces:**
- Consumes: ruta `/mealprep` (Task 6).
- Produces: botón visible en la vista de plan generado que navega a `/mealprep`, gateado en `plan` truthy (no en `isWeekly`).

- [ ] **Step 1: Agregar el import de `Link` y el ícono `ChefHat`**

En `frontend/src/pages/Planner.tsx`, actualizar los imports:

```typescript
import { Link } from 'react-router-dom';
import { Calendar as CalIcon, ShoppingBag, Send, FileDown, Loader2, Plus, ChevronLeft, ChevronRight, ChefHat } from 'lucide-react';
```

- [ ] **Step 2: Agregar el botón junto al de "Regenerate Plan"**

En `frontend/src/pages/Planner.tsx`, justo antes del `<button onClick={() => setShowModal(true)} ...>Regenerate Plan</button>` (línea ~249), agregar:

```tsx
          <Link
            to="/mealprep"
            className="w-full bg-neutral-900 border border-orange-500/40 py-3 rounded-xl flex items-center justify-center gap-2 mt-4 text-xs font-bold text-orange-400 uppercase tracking-widest"
          >
            <ChefHat className="w-4 h-4" /> Mealprep
          </Link>
```

- [ ] **Step 3: Verificación manual**

Genera un plan (diario o semanal) en `/planner`. Debe aparecer el botón "Mealprep"
debajo del listado de comidas, junto al de "Regenerate Plan". Al hacer click, navega
a `/mealprep`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Planner.tsx
git commit -m "feat: add Mealprep entry button to the Planner page"
```

---

## Task 9: Verificación end-to-end completa

No se crean archivos nuevos — este task es un recorrido manual final por todo el
flujo descrito en el spec (`docs/documentacion/mealprep-batch-planning.md`), con
backend y frontend corriendo.

- [ ] **Step 1: Flujo de plan diario (N=1)**

1. Genera un plan diario en `/planner`.
2. Click en "Mealprep" → debe saltar directo a "¿cuántos minutos tienes?" sin
   preguntar reparto de días.
3. Genera el mealprep → debe mostrar 1 sesión con fases y tareas.

- [ ] **Step 2: Flujo de plan semanal con reparto automático**

1. Genera un plan semanal en `/planner`.
2. Click en "Mealprep" → elige 2 sesiones, modo Automático, minutos distintos por
   sesión (ej. 120 y 90).
3. Genera → deben aparecer 2 sesiones, cada una cubriendo un bloque contiguo de
   días (revisa que los `recipe_ids` en las tareas correspondan a recetas de los
   días esperados).

- [ ] **Step 3: Flujo de plan semanal con reparto manual**

1. Con el mismo plan semanal, dale "Nuevo Mealprep", elige 3 sesiones, modo "Yo
   elijo", asigna los 7 días a las 3 sesiones a tu gusto.
2. Genera → confirma que cada sesión trae las recetas de los días que asignaste.

- [ ] **Step 4: Warning por tiempo insuficiente**

1. Genera un mealprep con muy pocos minutos disponibles (ej. 10 minutos) para una
   sesión con varias recetas.
2. Confirma que esa sesión muestra el bloque de `warning` en naranja en vez de
   fallar la generación.

- [ ] **Step 5: Recordatorio de Pantry**

Confirma que el banner "Recuerda actualizar tu Pantry..." aparece siempre arriba del
checklist de resultados, para cualquier mealprep generado.

- [ ] **Step 6: Resume tras cerrar la app**

1. Genera un mealprep, marca algunas tareas.
2. Cierra la pestaña/navegador por completo y vuelve a abrir la app.
3. Ve a `/mealprep` (o dale click al botón desde `/planner`) → debe retomar
   directamente el checklist con los checks que habías marcado, sin pedir el
   cuestionario de nuevo.

Si los 6 pasos anteriores pasan, el feature está completo según el spec.
