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
