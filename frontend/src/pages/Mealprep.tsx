import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../lib/store';
import { ChefHat, Loader2, ArrowLeft, RotateCcw } from 'lucide-react';
import {
  buildPlanFingerprint,
  loadMealprepCache,
  saveMealprepCache,
  clearMealprepCache,
  newMealprepCache,
} from '../lib/mealprepStorage';
import { MealprepCache } from '../lib/types';

type ViewState = 'loading' | 'no_plan' | 'questionnaire' | 'results';

type SessionInput = { days: number; minutes: number };

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

  const [sessions, setSessions] = useState<SessionInput[]>([{ days: 1, minutes: 60 }]);

  const resetQuestionnaire = () => {
    setSessions([{ days: 1, minutes: 60 }]);
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

  const updateSessionDays = (idx: number, days: number) => {
    setSessions((prev) => {
      const otherTotal = prev.reduce((sum, s, i) => (i === idx ? sum : sum + s.days), 0);
      const maxAllowed = Math.max(1, numDays - otherTotal);
      const clamped = Math.max(1, Math.min(maxAllowed, days || 1));
      const next = [...prev];
      next[idx] = { ...next[idx], days: clamped };
      return next;
    });
  };

  const updateSessionMinutes = (idx: number, minutes: number) => {
    setSessions((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], minutes };
      return next;
    });
  };

  const addSession = () => {
    setSessions((prev) => [...prev, { days: 1, minutes: 60 }]);
  };

  const removeSession = (idx: number) => {
    setSessions((prev) => prev.filter((_, i) => i !== idx));
  };

  const generateMealprep = async () => {
    let cursor = 0;
    const activeSessions = sessions
      .map((s) => {
        const dayIndices: number[] = [];
        for (let i = 0; i < s.days && cursor < numDays; i++) {
          dayIndices.push(cursor);
          cursor++;
        }
        return { minutes: s.minutes, dayIndices };
      })
      .filter((s) => s.dayIndices.length > 0);

    const payload = {
      sessions: activeSessions.map((s, i) => ({
        session_id: i + 1,
        available_minutes: s.minutes,
        recipes: s.dayIndices.flatMap((dayIdx) => {
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
    const totalDaysCovered = Math.min(numDays, sessions.reduce((sum, s) => sum + s.days, 0));
    const remainingDays = numDays - totalDaysCovered;

    const dayAssignments: (number | null)[] = new Array(numDays).fill(null);
    {
      let cursor = 0;
      sessions.forEach((s, sIdx) => {
        for (let i = 0; i < s.days && cursor < numDays; i++) {
          dayAssignments[cursor] = sIdx;
          cursor++;
        }
      });
    }

    return (
      <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 pb-20">
        <header className="mb-4">
          <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Mealprep</h1>
          <p className="text-neutral-400 text-sm">Organicemos tu sesión de cocina.</p>
        </header>

        {numDays > 1 && (
          <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-4 space-y-4">
            <p className="text-sm text-neutral-400">
              Cubres <span className="text-white font-bold">{totalDaysCovered}</span> de {numDays} días del plan
            </p>

            <div className="flex flex-wrap gap-2">
              {planDays.map((_, dayIdx) => {
                const sIdx = dayAssignments[dayIdx];
                return (
                  <div
                    key={dayIdx}
                    className={`px-2 py-1 rounded-lg text-xs font-bold border ${
                      sIdx === null
                        ? 'bg-black border-neutral-800 text-neutral-600'
                        : 'bg-orange-500/10 border-orange-500/30 text-orange-400'
                    }`}
                  >
                    {DAY_LABELS[dayIdx] || `Día ${dayIdx + 1}`}
                    {sIdx !== null && <span className="ml-1 text-neutral-500">S{sIdx + 1}</span>}
                  </div>
                );
              })}
            </div>

            {remainingDays > 0 && (
              <p className="text-xs text-neutral-500">
                {remainingDays} día{remainingDays > 1 ? 's' : ''} sin sesión todavía — agrega otra sesión para
                cubrirlo{remainingDays > 1 ? 's' : ''}, o déjalo así si no vas a cocinar ese día.
              </p>
            )}

            <div className="space-y-3">
              {sessions.map((s, idx) => (
                <div key={idx} className="bg-black border border-neutral-800 rounded-xl p-3 space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="text-sm font-bold text-white">Sesión {idx + 1}</span>
                    {sessions.length > 1 && (
                      <button
                        onClick={() => removeSession(idx)}
                        className="text-xs text-neutral-500 hover:text-red-400"
                      >
                        Quitar
                      </button>
                    )}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-neutral-400">¿Cuántos días cubre?</span>
                    <input
                      type="number"
                      min={1}
                      value={s.days}
                      onChange={(e) => updateSessionDays(idx, Number(e.target.value))}
                      className="w-16 bg-neutral-900 border border-neutral-800 rounded-lg text-sm text-white px-2 py-1 text-right"
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-neutral-400">¿Cuántos minutos tienes?</span>
                    <input
                      type="number"
                      min={10}
                      step={5}
                      value={s.minutes}
                      onChange={(e) => updateSessionMinutes(idx, Number(e.target.value))}
                      className="w-20 bg-neutral-900 border border-neutral-800 rounded-lg text-sm text-white px-2 py-1 text-right"
                    />
                  </div>
                </div>
              ))}
            </div>

            {remainingDays > 0 && (
              <button
                onClick={addSession}
                className="w-full py-2 rounded-lg border border-dashed border-neutral-700 text-sm text-neutral-400 hover:text-white hover:border-neutral-500"
              >
                + Agregar sesión
              </button>
            )}
          </div>
        )}

        {numDays === 1 && (
          <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-4 space-y-3">
            <p className="text-sm text-neutral-400">¿Cuántos minutos tienes disponibles?</p>
            <input
              type="number"
              min={10}
              step={5}
              value={sessions[0]?.minutes ?? 60}
              onChange={(e) => updateSessionMinutes(0, Number(e.target.value))}
              className="w-full bg-black border border-neutral-800 rounded-lg text-sm text-white px-3 py-2 text-right"
            />
          </div>
        )}

        <button
          onClick={generateMealprep}
          disabled={loading || sessions.length === 0}
          className="w-full bg-orange-500 text-black font-bold py-3 rounded-xl flex items-center justify-center gap-2 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : 'Generar Mealprep'}
        </button>
      </div>
    );
  }

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
                        className="w-5 h-5 mt-0.5 shrink-0 accent-orange-500"
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
}
