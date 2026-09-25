# Mealprep Batch Planning — Documentación

Fecha: 2026-09-24
Actualizado: 2026-09-25

## 1. Problema

Cuando el usuario genera un plan de comidas (diario o semanal) en `Planner.tsx`, no tiene
ninguna guía sobre **cómo cocinar todo de forma eficiente**: qué cortar junto, qué se puede
cocinar en paralelo (horno + estufa), en qué orden hacer las cosas para minimizar tiempo
muerto y evitar repetir tareas (ej. cortar cebolla tres veces en vez de una sola vez para
tres recetas).

## 2. Objetivo

Agregar un feature "Mealprep" que, a partir del plan ya generado (cualquiera sea su
cantidad de días), le pregunte al usuario cómo va a distribuir su tiempo de cocina (en
cuántas sesiones, qué días, cuántas horas por sesión) y genere un plan de batch-cooking:
fases con tareas agrupadas entre recetas, con tiempos estimados, para reducir el tiempo
total en cocina.

## 3. Alcance

- Aplica a **cualquier plan generado**, sin asumir una cantidad fija de días. Mealprep
  lee **N = cantidad real de días que trae el plan**
  (`Array.isArray(plan) ? plan.length : 1`). `Planner.tsx` ahora deja elegir cualquier
  N entre 1 y 14 (input numérico, reemplazó el toggle Daily/Weekly original) — Mealprep
  no necesitó ningún cambio cuando se agregó eso, porque ya estaba preparado para leerlo
  genéricamente desde el día 1.
- Parte siempre del plan ya generado en el Planner — no hay selección manual de recetas
  del Cookbook para esto (YAGNI: ya existe una entrada de datos clara, no hace falta una
  segunda).
- Un solo usuario, sin autenticación — el estado vive client-side, igual que el resto de
  la app (`currentMealPlan` en `idb-keyval`).

## 4. Flujo de usuario

1. En `Planner.tsx`, si `plan` no es null (sin importar cuántos días tenga), aparece un
   botón "Mealprep" que navega a la ruta nueva `/mealprep`.
2. Al entrar a `/mealprep`:
   - Si hay un mealprep guardado en progreso (algún check marcado, no 100% completo) **y**
     sigue correspondiendo al plan actual del Planner → se muestra directo el checklist
     donde el usuario iba. Hay un botón "+ Nuevo Mealprep" para descartarlo y empezar de
     cero (con confirmación antes de borrar).
   - Si el plan del Planner cambió desde que se generó ese mealprep guardado (se
     regeneró el plan diario/semanal) → el cache queda inválido automáticamente y se
     muestra el cuestionario de entrada en vez de un checklist con recetas que ya no
     aplican.
   - Si no hay nada guardado → cuestionario de entrada.
3. Cuestionario de entrada (siempre se pregunta de cero al generar un mealprep nuevo, no
   se guardan defaults). Sea N la cantidad de días del plan actual:
   - Si N = 1: se salta el builder de sesiones — hay una sola sesión implícita — y solo
     se pregunta cuántos minutos tiene disponibles.
   - Si N > 1: **builder secuencial de sesiones** (rediseñado el 2026-09-25 — el diseño
     original de "elige cuántas sesiones + auto-split o asignación manual por día" no
     modelaba bien un ritmo real de batch-cooking, ej. cocinar domingo para lunes y
     martes, martes para miércoles y jueves, jueves para viernes/sábado/domingo). Ahora
     el usuario arma las sesiones una por una: cada sesión declara cuántos días
     **consecutivos** cubre (empezando desde el día 1 del plan) y cuántos minutos tiene
     esa sesión. Un indicador ("Cubres X de N días") y chips por día (con el número de
     sesión, o gris si no tiene sesión) muestran la cobertura en vivo. **No es
     obligatorio cubrir el 100% de los días** — si el usuario deja de agregar sesiones,
     los días restantes (ej. un domingo que no va a cocinar) simplemente no generan
     tareas de mealprep, no se fuerzan a entrar en alguna sesión.
4. Al enviar el cuestionario, el frontend arma el payload (recetas de los días de cada
   sesión + parámetros) y llama a `POST /api/mealprep/generate`.
5. El resultado se muestra como checklist agrupado por sesión → fase → tarea. Marcar una
   tarea se guarda inmediatamente en `idb-keyval`.
6. Botón "Regenerar" vuelve al cuestionario de entrada (descarta el plan actual, con
   confirmación).

## 5. Contrato de datos

### Request: `POST /api/mealprep/generate`

```json
{
  "sessions": [
    {
      "session_id": 1,
      "available_minutes": 120,
      "recipes": [
        {
          "recipe_id": 12,
          "nombre": "Pollo al horno con vegetales",
          "meal_type": "almuerzo",
          "day": 1,
          "ingredients": [{ "name": "pollo", "amount": "500 g" }],
          "instructions": ["Precalienta el horno a 200°C", "..."]
        }
      ]
    }
  ]
}
```

Notas:
- El frontend ya resuelve qué días/recetas caen en cada sesión (vía el builder
  secuencial descrito en la sección 4) **antes** de llamar al backend — el backend
  recibe directamente la lista de recetas por sesión, sin saber cómo se armó esa
  distribución ni tocar la base de datos. Es stateless.
- `ingredients`/`instructions` vienen tal cual ya existen en `currentMealPlan` (no hace
  falta volver a consultarlos por `recipe_id`).

### Response

```json
{
  "sessions": [
    {
      "session_id": 1,
      "estimated_total_minutes": 105,
      "warning": null,
      "phases": [
        {
          "phase_name": "Corte y preparación",
          "tasks": [
            {
              "id": "s1-p1-t1",
              "text": "Corta 2 cebollas, 3 pimientos y 500g de pollo en cubos",
              "estimated_minutes": 15,
              "recipe_ids": [12, 15]
            }
          ]
        },
        { "phase_name": "Cocción activa", "tasks": [] },
        { "phase_name": "Cocción pasiva (horno / olla)", "tasks": [] },
        { "phase_name": "Ensamblaje y almacenamiento", "tasks": [] }
      ]
    }
  ]
}
```

- Si `available_minutes` no alcanza para todas las tareas de una sesión, `warning` trae un
  mensaje explicando qué no alcanza a cubrirse (el LLM decide qué recortar/sugerir mover),
  en vez de fallar la llamada.
- `completed` (bool) **no** viene del backend — es estado puramente client-side que se
  añade a cada tarea al guardar en `idb-keyval`.

## 6. Backend

- Nuevo módulo `backend/mealprep_planner.py`, clase `MealPrepPlanner` — mismo patrón que
  `RAGMealPlanner` en `rag_planner.py`:
  - Arma contexto determinístico por sesión: ingredientes deduplicados/normalizados
    (reusa `ingredient_normalizer.parse_amount_str`) + instrucciones crudas de cada
    receta.
  - Una sola llamada LLM por request (`get_llm()`, mismo prompt + parseo de JSON con
    regex que ya usa `rag_planner.py`).
  - Sin acceso a la DB — recibe todo lo que necesita en el request.
- Nuevo endpoint `POST /api/mealprep/generate` en `ig_recetas.py`, junto a
  `/api/mealplan/generate`.
- Nuevo passthrough explícito en `frontend/server.ts` (el proxy genérico rompe el
  prefijo `/api`, como ya pasó con `/api/pantry` — mismo fix, mismo patrón).
- Manejo de errores: si el LLM no devuelve JSON parseable, `ValueError` →
  `HTTPException(400)`, igual que `generate_mealplan`.
- **Completitud (fix 2026-09-25)**: se detectó que el plan de mealprep podía "perder"
  recetas e ingredientes en el camino, por dos causas distintas:
  1. `rag_planner.py` podía seleccionar recetas sin datos reales (posts de IG donde solo
     se guardó el título/hashtags, ej. una receta con 0 ingredientes y una instrucción
     placeholder tipo "la receta completa no fue proporcionada"). Ahora el retrieval de
     candidatos filtra cualquier receta sin `ingredientes` en las tres rutas de
     fallback (filtro estricto, filtro relajado, y el último recurso sin restricciones).
  2. El prompt de `mealprep_planner.py` dejaba que el LLM resumiera la fase "Corte y
     preparación" con frases vagas ("picar los vegetales para..."), perdiendo
     ingredientes específicos en el camino (ej. nunca mencionaba pelar las papas de un
     puré, o los aromáticos de una salsa). Se agregó una regla explícita de
     completitud al prompt: cada `recipe_id` de la sesión debe quedar representado en
     al menos una tarea, y cada ingrediente que necesite corte/pelado/picado debe
     nombrarse explícitamente (no resumirse con frases genéricas).

## 7. Frontend

- Nuevo archivo `frontend/src/pages/Mealprep.tsx` + ruta `/mealprep` en `App.tsx` (no se
  agrega a la navegación inferior; se llega solo desde el botón en `Planner.tsx`).
- Builder secuencial de sesiones (`sessions: {days, minutes}[]` en estado local): cada
  fila deja editar cuántos días consecutivos cubre esa sesión y cuántos minutos tiene;
  "+ Agregar sesión" añade otra fila. El día-a-sesión se deriva sumando
  acumulativamente los `days` de cada sesión en orden (sesión 1 cubre los primeros
  `days` días del plan, sesión 2 los siguientes, etc.) — todo lógica pura de cliente,
  sin llamar al backend hasta el submit final.
  - Cada fila tiene un clamp: no se puede poner un `days` que haga que la suma total
    supere N (el máximo permitido para esa fila es `N - suma de las demás filas`).
  - Chips por día (etiquetados Lun-Dom cuando N = 7, o "Día 1"/"Día 2" etc. en otro
    caso) muestran en vivo a qué sesión cae cada día, o gris si quedó sin cubrir.
- Recordatorio de Pantry: en la pantalla de resultados (checklist), un banner fijo tipo
  "Recuerda actualizar tu Pantry con lo que ya tienes en la cocina antes de empezar" —
  texto estático, sin cruzar inventario contra ingredientes (ver sección 9, por qué no se
  hace ese cruce).
- Reutiliza el patrón de modal/wizard que ya tiene `Planner.tsx` para el cuestionario.

## 8. Persistencia y cache

- Todo vive client-side en `idb-keyval`, bajo una key nueva (ej. `app_mealprep`), mismo
  mecanismo que `currentMealPlan` (key `app_mealplan`).
- El objeto guardado incluye: el plan completo devuelto por el backend + el estado
  `completed` de cada tarea + una referencia al plan del Planner del que se generó (para
  poder detectar que quedó obsoleto si el usuario regenera el plan).
- No se crea ninguna tabla nueva en `models.py` — es un cambio deliberado de YAGNI: no
  hay auth ni multi-dispositivo, y el patrón existente de la app ya resuelve
  "recordar el último plan" del mismo modo.

## 9. Fuera de alcance (explícitamente)

- Selección manual de recetas del Cookbook para armar una sesión de mealprep ad-hoc.
- Sincronización del progreso entre dispositivos (queda solo en el `idb-keyval` local).
- Persistencia del cuestionario de entrada como default (se pregunta siempre de cero).
- Integración con Grocery list — no tiene relación directa con el orden/tiempo de
  cocina.
- Cruzar el inventario del Pantry contra las tareas generadas (ej. desactivar "picar
  cebolla" si no hay cebolla en Pantry). Esto requeriría que el backend consulte Pantry
  y que el LLM razone sobre disponibilidad real de ingredientes — mucho más alcance para
  un beneficio marginal. En su lugar, se agrega el recordatorio estático de la sección 7:
  el usuario decide si su Pantry está al día antes de empezar.

## 10. Notas de implementación

- Implementar usando la skill `ponytail` (nivel `full`) para mantener la solución más
  simple que funcione — sin abstracciones ni capas que este alcance no pide.
- Usar las skills de ECC relevantes al tocar cada parte del stack (ej. `fastapi-patterns`
  / `python-patterns` para el backend, `react-patterns` para el frontend) en vez de código
  libre.
