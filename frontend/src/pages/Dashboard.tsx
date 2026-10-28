import { useStore } from '../lib/store';
import { Flame, Target, Utensils, Activity, HeartPulse, CalendarCheck, Check } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { format } from 'date-fns';
import { planDays, todayPlanIndex, planIdOf, dayEntries, realScore, mealMacros } from '../lib/plan';
import { getPregnancyWeeks } from '../lib/macroCalculator';
import toast from 'react-hot-toast';

const getCyclePhase = (dateStr?: string) => {
  if (!dateStr) return 'none';
  const start = new Date(dateStr);
  const now = new Date();
  const diffTime = now.getTime() - start.getTime();
  const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
  if (diffDays < 0) return 'none';
  
  const cycleDay = (diffDays % 28) + 1; // 28 day cycle average
  if (cycleDay >= 1 && cycleDay <= 5) return 'menstrual';
  if (cycleDay >= 6 && cycleDay <= 13) return 'follicular';
  if (cycleDay >= 14 && cycleDay <= 17) return 'ovulation';
  return 'luteal';
}

export default function Dashboard() {
  const { profile, dailyConsumption, updateDailyConsumption, streakDays, eatLog, logMeal, unlogMeal, currentMealPlan, planStart } = useStore();
  const [burnedInput, setBurnedInput] = useState('');
  const [isSyncingGarmin, setIsSyncingGarmin] = useState(false);

  const syncGarmin = async () => {
    if (!profile.garminConnected || !profile.garminCredentials) return toast.error("Not connected to Garmin");
    setIsSyncingGarmin(true);
    try {
       const today = new Date().toISOString().split('T')[0];
       const res = await fetch("/api/garmin/calories", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ 
             username: profile.garminCredentials.user, 
             password: profile.garminCredentials.pass, 
             date: today 
          })
       });
       const data = await res.json();
       if (res.ok && data.summary) {
          // Garmin gives activeKilocalories and bmrKilocalories... Usually active = burned via exercise
          // If totalKilocalories is there, or activeKilocalories:
          const activeCal = data.summary.activeKilocalories || data.summary.wellnessActiveKilocalories || 0;
          if (activeCal > 0) {
             updateDailyConsumption({ caloriesBurned: activeCal });
             toast.success(`Synced ${activeCal} active calories from Garmin!`);
          } else {
             toast("Garmin synced, but 0 active calories today.", { icon: 'ℹ️' });
          }
       } else {
          toast.error("Could not fetch Garmin summary.");
       }
    } catch (err: any) {
       toast.error("Error syncing with Garmin APIs");
    } finally {
       setIsSyncingGarmin(false);
    }
  };

  const addBurnedCalories = () => {
    const val = parseInt(burnedInput);
    if (!isNaN(val) && val > 0) {
      updateDailyConsumption({ caloriesBurned: dailyConsumption.caloriesBurned + val });
      setBurnedInput('');
      toast.success(`Added ${val} burned calories`);
    } else {
      toast.error("Enter a valid number");
    }
  };

  // Today's plan day: its targets are the goals (same numbers the Planner scored against,
  // e.g. fiber adjusted to protein); without a plan, the profile goals.
  const plan = planDays(currentMealPlan);
  const dayIndex = todayPlanIndex(currentMealPlan, planStart);
  const today = plan[dayIndex];
  const t = today?.targets;
  const pg = profile.dailyGoals;
  const goals = t
    ? { calories: t.calorias ?? pg.calories, protein: t.proteinas ?? pg.protein, carbs: t.carbohidratos ?? pg.carbs,
        fat: t.grasas ?? pg.fat, fiber: t.fibra ?? pg.fiber, sugar: t.azucares ?? pg.sugar }
    : pg;
  const todaysLog = eatLog.filter(e => e.date === format(new Date(), 'yyyy-MM-dd'));
  // Score of what was actually eaten today, against today's plan targets (or the profile goals).
  const planId = planIdOf(currentMealPlan);
  const planEntries = dayEntries(eatLog, planId, dayIndex);
  const doneKeys = new Set(planEntries.map(e => e.planKey));
  // With a plan, the score is how much of it was followed: share of its meals checked (a Cookbook
  // replacement counts; "ate something else" doesn't). All checked = 100 even if the plan itself
  // doesn't reach the daily goal. Without a plan: today's intake against the profile goals.
  const score = today?.meals.length
    ? Math.round((planEntries.filter(e => e.macros).length / today.meals.length) * 100)
    : realScore(todaysLog, { calorias: pg.calories, proteinas: pg.protein, carbohidratos: pg.carbs,
        grasas: pg.fat, fibra: pg.fiber, azucares: pg.sugar }, profile);

  const macros = dailyConsumption.macros;
  const consumedCalories = Math.round(macros.calories);
  const netCalories = consumedCalories - dailyConsumption.caloriesBurned;
  const remaining = goals.calories - netCalories;
  
  return (
    <div className="p-4 max-w-lg mx-auto space-y-6 pt-8">
      <header className="flex justify-between items-end mb-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white mb-1">Today</h1>
          <p className="text-neutral-400 text-sm font-medium">Keep up the momentum.</p>
        </div>
        <div className="flex items-center gap-2 bg-orange-500/10 text-orange-500 px-3 py-1.5 rounded-full">
          <Flame className="w-4 h-4" />
          <span className="font-bold text-sm tracking-wide">{streakDays} Day Streak</span>
        </div>
      </header>

      {/* Main Calorific Metric */}
      <section className="bg-neutral-900 rounded-2xl p-6 border border-neutral-800">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
             <Target className="w-5 h-5 text-orange-500" />
             <h2 className="text-lg font-bold">Energy Balance</h2>
          </div>
          <div className="text-xs font-mono text-neutral-500">Goal: {Math.round(goals.calories)}</div>
        </div>
        
        <div className="grid grid-cols-3 gap-4 mb-6 text-center">
          <div>
            <div className="text-2xl font-bold text-white">{consumedCalories}</div>
            <div className="text-xs text-neutral-500 uppercase tracking-widest mt-1">Eaten</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-orange-500">- {dailyConsumption.caloriesBurned}</div>
            <div className="text-xs text-neutral-500 uppercase tracking-widest mt-1">Burned</div>
          </div>
          <div>
            <div className={`text-2xl font-bold ${remaining < 0 ? 'text-red-400' : 'text-blue-400'}`}>= {Math.round(netCalories)}</div>
            <div className="text-xs text-neutral-500 uppercase tracking-widest mt-1">Net</div>
          </div>
        </div>

        <div className="flex flex-col gap-3 mt-2">
          <div className="flex items-center gap-2 bg-neutral-950 p-1.5 rounded-xl border border-neutral-800">
            <input
              type="number"
              value={burnedInput}
              onChange={(e) => setBurnedInput(e.target.value)}
              placeholder="Ej. 300 kcal"
              className="bg-transparent flex-1 text-sm outline-none px-3 text-white placeholder:text-neutral-600"
            />
            <button 
              onClick={addBurnedCalories}
              className="bg-neutral-800 hover:bg-neutral-700 text-white px-4 py-2 rounded-lg text-sm font-bold transition-colors"
            >
              Add Manual
            </button>
          </div>
          
          {profile.garminConnected && (
            <button 
              onClick={syncGarmin}
              disabled={isSyncingGarmin}
              className="w-full flex justify-center items-center gap-2 bg-blue-600/10 border border-blue-500/20 hover:bg-blue-600/20 disabled:opacity-50 text-blue-400 px-4 py-3 rounded-xl text-sm font-bold transition-colors"
            >
              {isSyncingGarmin ? (
                <>Syncing...</>
              ) : (
                <><Activity className="w-4 h-4"/> Sync Garmin Connect</>
              )}
            </button>
          )}
        </div>
      </section>

      {/* Today's plan: progress and real vs planned score (the Planner only lists meals) */}
      {today && (
        <section className="bg-neutral-900 border border-neutral-800 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <CalendarCheck className="w-5 h-5 text-orange-500" />
              <h2 className="text-lg font-bold">Plan de hoy{plan.length > 1 && <span className="text-neutral-500 font-normal text-sm"> · día {dayIndex + 1}/{plan.length}</span>}</h2>
            </div>
            <Link to="/planner" className="text-xs text-orange-400 hover:text-orange-300">Abrir plan →</Link>
          </div>

          <div className="grid grid-cols-2 gap-4 mb-4 text-center">
            <div>
              <div className={`text-2xl font-bold ${doneKeys.size === today.meals.length ? 'text-green-400' : 'text-white'}`}>{doneKeys.size}/{today.meals.length}</div>
              <div className="text-xs text-neutral-500 uppercase tracking-widest mt-1">Comidas</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-green-400">{score ?? '—'}</div>
              <div className="text-xs text-neutral-500 uppercase tracking-widest mt-1">Puntaje real</div>
            </div>
          </div>

          <ul className="space-y-2">
            {today.meals.map((meal: any, i: number) => {
              const key = `${planId}:${dayIndex}:${i}`;
              const entry = eatLog.find(e => e.planKey === key);
              // Same toggle as the Planner: logs the planned meal (macros, Cookbook "Eaten", streak) or undoes it.
              const toggle = () => entry
                ? unlogMeal(entry.id)
                : logMeal({ title: meal.nombre, recipeId: String(meal.recipe_id), planKey: key, macros: mealMacros(meal) });
              return (
                <li key={i}>
                  <button onClick={toggle} aria-pressed={!!entry}
                    aria-label={entry ? `Desmarcar ${meal.meal_type}` : `Marcar ${meal.meal_type} como comido`}
                    className="w-full flex items-center gap-3 text-sm text-left rounded-lg p-1 -m-1 hover:bg-neutral-800 transition-colors">
                    <span className={`w-5 h-5 shrink-0 rounded-full border flex items-center justify-center ${entry ? 'bg-green-500 border-green-500 text-black' : 'border-neutral-600 text-transparent'}`}>
                      <Check className="w-3.5 h-3.5" />
                    </span>
                    <span className="w-16 shrink-0 text-orange-500 font-bold uppercase text-[10px]">{meal.meal_type}</span>
                    <span className={`truncate ${entry ? 'text-neutral-500 line-through' : 'text-white'}`}>
                      {entry && entry.recipeId !== String(meal.recipe_id) ? `${meal.nombre} → ${entry.title}` : meal.nombre}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {/* Macros */}
      <section className="bg-neutral-900 border border-neutral-800 rounded-2xl p-6">
        <div className="flex items-center gap-3 mb-6">
          <Utensils className="w-5 h-5 text-orange-500" />
          <h2 className="text-lg font-bold">Macronutrients</h2>
        </div>

        <div className="space-y-5">
          <MacroBar label="Protein" current={macros.protein} goal={goals.protein} />
          <MacroBar label="Carbs" current={macros.carbs} goal={goals.carbs} />
          <MacroBar label="Fats" current={macros.fat} goal={goals.fat} />
          <MacroBar label="Fiber" current={macros.fiber} goal={goals.fiber} />
          <MacroBar label="Sugar" current={macros.sugar} goal={goals.sugar} limit />
        </div>
      </section>

      {profile.isPregnant ? (
        (() => {
          const pregnancyInfo = getPregnancyWeeks(profile.pregnancyDueDate);
          if (!pregnancyInfo) return null;
          return (
            <section className="bg-orange-500/10 text-orange-400 border border-orange-500/20 rounded-2xl p-5 mb-8 flex gap-4">
              <HeartPulse className="w-6 h-6 shrink-0 mt-0.5" />
              <div>
                <h3 className="font-bold mb-1">Semana {pregnancyInfo.week} - Trimestre {pregnancyInfo.trimester}</h3>
                <p className="text-sm opacity-80 leading-relaxed text-orange-200">
                  {pregnancyInfo.trimester === 1 && "Trimestre 1: Tus requerimientos calóricos base no aumentan, pero prioriza ácido fólico y mantén la hidratación."}
                  {pregnancyInfo.trimester === 2 && "Trimestre 2: El bebé crece rápido. Tus calorías y proteínas han sido ajustadas. Asegúrate de comer grasas saludables para el desarrollo cerebral."}
                  {pregnancyInfo.trimester === 3 && "Trimestre 3: Máxima demanda energética. Come pequeñas porciones más seguido si tienes saciedad temprana. Tus calorías están al máximo."}
                </p>
              </div>
            </section>
          )
        })()
      ) : (
        getCyclePhase(profile.lastPeriodStart) !== 'none' && (
          <section className="bg-orange-500/10 text-orange-400 border border-orange-500/20 rounded-2xl p-5 mb-8 flex gap-4">
            <Activity className="w-6 h-6 shrink-0 mt-0.5" />
            <div>
              <h3 className="font-bold mb-1 capitalize">{getCyclePhase(profile.lastPeriodStart)} Phase</h3>
              <p className="text-sm opacity-80 leading-relaxed text-orange-200">
                {getCyclePhase(profile.lastPeriodStart) === 'luteal' && "Your body might crave more energy. Prioritize complex carbs and slightly sweeter healthy treats."}
                {getCyclePhase(profile.lastPeriodStart) === 'menstrual' && "Focus on iron-rich foods, anti-inflammatory ingredients, and hydration."}
                {getCyclePhase(profile.lastPeriodStart) === 'follicular' && "Energy levels are rising. Fresh, light, and protein-forward meals are great right now."}
                {getCyclePhase(profile.lastPeriodStart) === 'ovulation' && "Peak energy. Great time for high-intensity workouts and balanced lighter meals."}
              </p>
            </div>
          </section>
        )
      )}
    </div>
  );
}

// Fills in proportion to what's been eaten. A `limit` (sugar) is a maximum, not a target:
// the bar is a green -> yellow -> red gradient sized to the whole track, so filling it reveals
// more of it: little sugar shows only green, reaching the max shows the red end. Over the max the
// bar stays full and the number keeps growing (in red).
function MacroBar({ label, current, goal, limit = false }: { label: string, current: number, goal: number, limit?: boolean }) {
  const ratio = goal > 0 ? Math.max(0, current / goal) : 0;
  const percent = Math.min(100, ratio * 100);
  const gradient = limit && percent > 0 ? {
    backgroundImage: 'linear-gradient(to right, #22c55e, #eab308 55%, #ef4444)',
    backgroundSize: `${(100 / percent) * 100}% 100%`, // gradient spans the full track, not just the fill
  } : {};
  return (
    <div>
      <div className="flex justify-between text-sm mb-2 font-medium">
        <span>{label}</span>
        <span className="text-neutral-400">
          <span className={limit && ratio > 1 ? 'text-red-400' : 'text-white'}>{Math.round(current)}g</span>
          {' / '}{limit && 'máx '}{Math.round(goal)}g
        </span>
      </div>
      <div className="h-2 w-full bg-neutral-950 rounded-full overflow-hidden"
        role="progressbar" aria-label={label} aria-valuenow={Math.round(current)} aria-valuemin={0} aria-valuemax={Math.round(goal)}>
        <div className={`h-full transition-all duration-500 ${limit ? '' : 'bg-orange-500'}`} style={{ width: `${percent}%`, ...gradient }} />
      </div>
    </div>
  );
}
