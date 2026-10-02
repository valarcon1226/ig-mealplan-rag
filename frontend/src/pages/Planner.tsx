import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useStore, sumMacros } from '../lib/store';
import { buildPlanFingerprint } from '../lib/mealprepStorage';
import { Calendar as CalIcon, ShoppingBag, Send, FileDown, Loader2, Plus, ChevronLeft, ChevronRight, ChefHat, Check, RefreshCw, Utensils } from 'lucide-react';
import { Macros, Recipe } from '../lib/types';

// Short stable id per generated plan, so checks from an old plan don't carry over.
const planIdOf = (plan: any) => {
  let h = 0;
  for (const c of buildPlanFingerprint(plan)) h = (h * 31 + c.charCodeAt(0)) | 0;
  return (h >>> 0).toString(36);
};

const mealMacros = (meal: any): Macros => ({
  calories: meal.calorias || 0, protein: meal.proteinas || 0, carbs: meal.carbohidratos || 0,
  fat: meal.grasas || 0, fiber: meal.fibra || 0, sugar: meal.azucar || 0,
});

export default function Planner() {
  const { profile, recipes, setCurrentMealPlan, currentMealPlan, eatLog, logMeal, unlogMeal } = useStore();
  const [plan, setPlan] = useState<any>(currentMealPlan); // puede ser array o objeto
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  
  const [numDays, setNumDays] = useState(1);
  const [currentDayIndex, setCurrentDayIndex] = useState(0);

  // Selecciones disponibles (con soporte para múltiples snacks)
  const mealOptions = [
    { id: 'desayuno', label: 'Desayuno', query: 'desayuno' },
    { id: 'almuerzo', label: 'Almuerzo', query: 'almuerzo' },
    { id: 'cena', label: 'Cena', query: 'cena' },
    { id: 'snack1', label: 'Snack 1', query: 'snack' },
    { id: 'snack2', label: 'Snack 2', query: 'snack' },
    { id: 'postre', label: 'Postre', query: 'postre' }
  ];

  const [selectedMealIds, setSelectedMealIds] = useState<string[]>(['desayuno', 'almuerzo', 'cena']);
  const [selectedRecipe, setSelectedRecipe] = useState<Recipe | null>(null);
  // Plan meal the open recipe / replacement picker belongs to ("<planId>:<day>:<meal>").
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [replaceKey, setReplaceKey] = useState<string | null>(null);
  const [replaceQuery, setReplaceQuery] = useState('');
  const [realScore, setRealScore] = useState<number | null>(null);

  const toggleMeal = (id: string) => {
    if (selectedMealIds.includes(id)) {
      setSelectedMealIds(selectedMealIds.filter(m => m !== id));
    } else {
      setSelectedMealIds([...selectedMealIds, id]);
    }
  };

  const generatePlan = async () => {
    if (selectedMealIds.length === 0) {
      alert("Please select at least one meal.");
      return;
    }
    
    // Mapear los IDs seleccionados al query que entiende el backend
    const mealsToSend = selectedMealIds.map(id => mealOptions.find(o => o.id === id)?.query || 'snack');

    setLoading(true);
    setShowModal(false);
    try {
      const res = await fetch('/api/mealplan/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dailyGoals: profile.dailyGoals,
          meals: mealsToSend,
          num_days: numDays,
          goal: profile.goal ?? 'maintain',
          is_pregnant: !!profile.isPregnant,
          restrictions: profile.dietaryRestrictions ?? [],
          avoid: profile.avoidFoods ?? [],
          likes: profile.favoriteFoods ?? []
        })
      });
      const data = await res.json();
      
      if (!res.ok) {
        alert(data.detail || data.error || "Failed to generate plan");
        setPlan(null);
        setCurrentMealPlan(null);
      } else {
        setPlan(data);
        setCurrentMealPlan(data);
        setCurrentDayIndex(0);
      }
    } catch (err) {
      console.error(err);
      alert("Failed to generate plan");
    } finally {
      setLoading(false);
    }
  };

  const printPdf = () => {
    window.print();
  };

  const openRecipeDetails = (meal: any, key: string) => {
    setSelectedKey(key);
    const recipeToOpen: Recipe = {
      id: String(meal.recipe_id),
      title: meal.nombre,
      thumbnail_url: meal.thumbnail_url,
      video_url: meal.video_url,
      ingredients: meal.ingredients || [],
      instructions: meal.instructions || [],
      macros: mealMacros(meal),
      servings: 1,
      categories: [],
      createdAt: Date.now()
    };
    setSelectedRecipe(recipeToOpen);
  };

  const isWeekly = Array.isArray(plan);
  const currentPlan = isWeekly ? plan[currentDayIndex] : plan;
  const planId = planIdOf(plan);
  const keyFor = (i: number) => `${planId}:${currentDayIndex}:${i}`;
  const entryFor = (key: string) => eatLog.find(e => e.planKey === key);
  const dayEntries = eatLog.filter(e => e.planKey?.startsWith(`${planId}:${currentDayIndex}:`));
  const dayDone = dayEntries.length;
  const dayMealCount = currentPlan?.meals?.length ?? 0;

  // Real score = same backend formula as the planned one, over what was actually eaten.
  // "Ate something else" entries have no macros, so they add no points.
  const eatenTotals = sumMacros(dayEntries);
  const eatenWithMacros = dayEntries.some(e => e.macros);
  useEffect(() => {
    if (!currentPlan?.targets || !eatenWithMacros) { setRealScore(null); return; }
    let cancelled = false;
    fetch('/api/intake-score', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        totals: {
          calorias: eatenTotals.calories, proteinas: eatenTotals.protein, carbohidratos: eatenTotals.carbs,
          grasas: eatenTotals.fat, fibra: eatenTotals.fiber, azucar: eatenTotals.sugar,
        },
        targets: currentPlan.targets,
        goal: profile.goal ?? 'maintain',
        is_pregnant: !!profile.isPregnant,
      }),
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (!cancelled) setRealScore(d ? d.total : null); })
      .catch(() => { if (!cancelled) setRealScore(null); });
    return () => { cancelled = true; };
  }, [JSON.stringify(eatenTotals), eatenWithMacros, planId, currentDayIndex]);

  const toggleEaten = (meal: any, key: string) => {
    const entry = entryFor(key);
    if (entry) unlogMeal(entry.id);
    else logMeal({ title: meal.nombre, recipeId: String(meal.recipe_id), planKey: key, macros: mealMacros(meal) });
  };

  const replaceWith = (recipe: Recipe | null) => {
    if (!replaceKey) return;
    const prev = entryFor(replaceKey);
    if (prev) unlogMeal(prev.id);
    // null = "ate something else" that isn't in the Cookbook: counts as eaten, no macros/points.
    logMeal(recipe
      ? { title: recipe.title, recipeId: recipe.id, planKey: replaceKey, macros: recipe.macros }
      : { title: 'Comí otra cosa', planKey: replaceKey });
    setReplaceKey(null);
    setReplaceQuery('');
  };

  // "Add 1 Serving" from a plan meal checks that meal; otherwise it's a plain log entry.
  const eatRecipe = (recipe: Recipe) => {
    if (selectedKey && !entryFor(selectedKey)) {
      logMeal({ title: recipe.title, recipeId: recipe.id, planKey: selectedKey, macros: recipe.macros });
    } else {
      logMeal({ title: recipe.title, recipeId: recipe.id, macros: recipe.macros });
    }
    setSelectedRecipe(null);
  };

  const replaceOptions = recipes
    .filter(r => r.title.toLowerCase().includes(replaceQuery.toLowerCase()))
    .slice(0, 30);

  return (
    <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 print:pt-0 pb-20 print:pb-0 relative">
      <header className="mb-8 print:hidden">
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Meal Planner</h1>
        <p className="text-neutral-400 text-sm">AI generates your plan based on your cookbook and macros.</p>
      </header>

      {showModal && (
        <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4">
          <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl w-full max-w-sm space-y-6">
            <h2 className="text-xl font-bold">Generate Plan</h2>
            
            <div>
              <label className="text-xs font-bold text-neutral-400 block mb-2">¿Cuántos días quieres planear?</label>
              <input
                type="number"
                min={1}
                max={14}
                value={numDays}
                onChange={e => {
                  const v = parseInt(e.target.value, 10);
                  setNumDays(Number.isNaN(v) ? 1 : Math.max(1, Math.min(14, v)));
                }}
                className="w-full bg-black border border-neutral-800 rounded-lg px-3 py-3 text-sm text-white focus:border-orange-500 outline-none"
              />
            </div>

            <p className="text-sm text-neutral-400">Which meals do you want to include each day?</p>
            <div className="space-y-2 max-h-[40vh] overflow-y-auto">
              {mealOptions.map(option => (
                <label key={option.id} className="flex items-center gap-3 p-3 bg-black rounded-lg border border-neutral-800 cursor-pointer">
                  <input 
                    type="checkbox" 
                    checked={selectedMealIds.includes(option.id)}
                    onChange={() => toggleMeal(option.id)}
                    className="w-5 h-5 accent-orange-500"
                  />
                  <span className="capitalize text-white font-medium">{option.label}</span>
                </label>
              ))}
            </div>
            
            <div className="flex gap-3 pt-2">
              <button onClick={() => setShowModal(false)} className="flex-1 py-3 text-sm font-bold text-neutral-400">Cancel</button>
              <button onClick={generatePlan} className="flex-1 py-3 bg-orange-500 text-black rounded-xl font-bold text-sm">Generate</button>
            </div>
          </div>
        </div>
      )}

      {!plan ? (
        <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-8 text-center print:hidden">
          <CalIcon className="w-12 h-12 mx-auto text-orange-500 mb-4" />
          <h2 className="font-bold text-xl mb-2">Ready for the day?</h2>
          <p className="text-sm text-neutral-400 mb-6 pb-6 border-b border-neutral-800">Use your saved recipes to build a balanced, goal-oriented meal plan.</p>
          <button
            onClick={() => setShowModal(true)}
            disabled={loading}
            className="w-full bg-orange-500 text-black font-bold py-3 rounded-xl flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : "Generate New Plan"}
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="flex justify-between items-center print:hidden">
            <h2 className="font-bold text-xl">
              {isWeekly ? `Plan (${plan.length} días)` : `Today's Plan`}
            </h2>
            <div className="flex gap-2">
              <button onClick={printPdf} className="p-2 border border-neutral-800 rounded-lg hover:bg-neutral-900 text-neutral-400 hover:text-white"><FileDown className="w-4 h-4" /></button>
            </div>
          </div>
          
          {isWeekly && (
            <div className="flex items-center justify-between bg-black rounded-xl border border-neutral-800 p-2 print:hidden">
              <button 
                onClick={() => setCurrentDayIndex(prev => Math.max(0, prev - 1))}
                disabled={currentDayIndex === 0}
                className="p-2 rounded-lg text-neutral-400 hover:text-white hover:bg-neutral-900 disabled:opacity-30"
              >
                <ChevronLeft className="w-5 h-5" />
              </button>
              <span className="font-bold text-white uppercase tracking-wider text-sm">
                {["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][currentDayIndex] || `Day ${currentDayIndex + 1}`}
              </span>
              <button 
                onClick={() => setCurrentDayIndex(prev => Math.min(plan.length - 1, prev + 1))}
                disabled={currentDayIndex === plan.length - 1}
                className="p-2 rounded-lg text-neutral-400 hover:text-white hover:bg-neutral-900 disabled:opacity-30"
              >
                <ChevronRight className="w-5 h-5" />
              </button>
            </div>
          )}

          {currentPlan && (
            <>
              <div className="bg-neutral-900/50 p-4 rounded-xl border border-neutral-800/50">
                <div className="flex justify-between items-center mb-2">
                    <span className="text-neutral-400 text-sm">Intake Score (Day {currentPlan.day || 1})</span>
                    <span className="text-sm text-neutral-400">
                      Planeado <span className="text-orange-500 font-bold">{Math.round(currentPlan.score)}</span>
                      {realScore != null && <> · Real <span className="text-green-400 font-bold">{realScore}</span></>}
                      <span className="text-neutral-600 text-xs">/100</span>
                    </span>
                </div>
                <div className="text-xs text-neutral-500 mb-2">
                  <span className={dayDone === dayMealCount && dayMealCount > 0 ? 'text-green-400 font-bold' : 'text-white font-bold'}>{dayDone}/{dayMealCount}</span> comidas
                  {eatenWithMacros && <> · {Math.round(eatenTotals.calories)} kcal reales</>}
                </div>
                {currentPlan.score_breakdown && (
                  <div className="flex flex-wrap gap-x-3 gap-y-1 mb-3 text-[10px] text-neutral-500">
                    {([['calorias', 'Cal', 45], ['proteinas', 'Pro', 20], ['carbohidratos', 'Carb', 15], ['grasas', 'Fat', 10], ['fibra', 'Fib', 5], ['azucar', 'Azú', 5]] as const).map(([key, label, max]) => (
                      <span key={key}>{label} <span className={currentPlan.score_breakdown[key] >= max ? 'text-green-400' : 'text-white'}>{Math.round(currentPlan.score_breakdown[key])}</span>/{max}</span>
                    ))}
                  </div>
                )}
                <div className="flex gap-2 text-center text-xs">
                    <div className="w-1/3 shrink-0 bg-black p-3 rounded border border-neutral-800 flex flex-col items-center justify-center">
                      <div className="text-neutral-500 mb-1">Calorías</div>
                      <div className="text-3xl font-bold text-orange-400 leading-none">{Math.round(currentPlan.totals.calorias)}</div>
                      <div className="text-neutral-600 mt-1">{currentPlan.targets?.calorias != null ? `/ ${Math.round(currentPlan.targets.calorias)} kcal` : 'kcal'}</div>
                    </div>
                    <div className="flex-1 grid grid-cols-6 gap-2">
                      <div className="col-span-2 bg-black p-2 rounded border border-neutral-800"><div className="text-neutral-500">Pro</div><div className="font-bold text-white">{Math.round(currentPlan.totals.proteinas)}g</div></div>
                      <div className="col-span-2 bg-black p-2 rounded border border-neutral-800"><div className="text-neutral-500">Carb</div><div className="font-bold text-white">{Math.round(currentPlan.totals.carbohidratos)}g</div></div>
                      <div className="col-span-2 bg-black p-2 rounded border border-neutral-800"><div className="text-neutral-500">Fat</div><div className="font-bold text-white">{Math.round(currentPlan.totals.grasas)}g</div></div>
                      <div className="col-span-3 bg-black p-2 rounded border border-neutral-800">
                        <div className="text-neutral-500">Fibra</div>
                        <div className={`font-bold ${(currentPlan.totals.fibra ?? 0) >= (currentPlan.targets?.fibra ?? 0) ? 'text-green-400' : 'text-white'}`}>
                          {Math.round(currentPlan.totals.fibra ?? 0)}g
                        </div>
                        {currentPlan.targets?.fibra != null && <div className="text-neutral-600">/ {currentPlan.targets.fibra}g</div>}
                      </div>
                      <div className="col-span-3 bg-black p-2 rounded border border-neutral-800">
                        <div className="text-neutral-500">Azúcar</div>
                        <div className={`font-bold ${currentPlan.targets?.azucares != null && (currentPlan.totals.azucar ?? 0) > currentPlan.targets.azucares ? 'text-red-400' : 'text-white'}`}>
                          {Math.round(currentPlan.totals.azucar ?? 0)}g
                        </div>
                        {currentPlan.targets?.azucares != null && <div className="text-neutral-600">máx {currentPlan.targets.azucares}g</div>}
                      </div>
                    </div>
                </div>
              </div>

              <div className="space-y-4 print:text-black print:bg-white pb-4">
                <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 print:border-gray-300 print:bg-white print:-mx-4">
                  <div className="space-y-4">
                    {currentPlan.meals.map((meal: any, i: number) => {
                      const key = keyFor(i);
                      const entry = entryFor(key);
                      const replaced = entry && entry.recipeId !== String(meal.recipe_id);
                      return (
                        <div key={i} className="flex gap-3 text-sm p-2 rounded-lg hover:bg-neutral-800 transition-colors group">
                          <button
                            onClick={() => toggleEaten(meal, key)}
                            aria-pressed={!!entry}
                            aria-label={entry ? `Desmarcar ${meal.meal_type}` : `Marcar ${meal.meal_type} como comido`}
                            className={`w-6 h-6 mt-0.5 shrink-0 rounded-full border flex items-center justify-center print:hidden ${entry ? 'bg-green-500 border-green-500 text-black' : 'border-neutral-600 text-transparent hover:border-green-500'}`}
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <div className="w-20 shrink-0 text-orange-500 font-bold uppercase text-xs mt-1">{meal.meal_type}</div>
                          <div className="flex-1 min-w-0 cursor-pointer" onClick={() => openRecipeDetails(meal, key)}>
                            <div className={`group-hover:text-orange-400 transition-colors print:text-black font-medium ${replaced ? 'line-through text-neutral-500' : 'text-white'}`}>{meal.nombre}</div>
                            {replaced && <div className="text-green-400 text-xs mt-0.5">→ {entry!.title}</div>}
                            <div className="text-neutral-500 text-xs mt-1">{meal.calorias} kcal · {meal.proteinas}g pro</div>
                          </div>
                          <button
                            onClick={() => setReplaceKey(key)}
                            aria-label={`Cambiar ${meal.meal_type}: comí otra cosa`}
                            title="Comí otra cosa"
                            className="p-1.5 h-fit rounded-lg text-neutral-500 hover:text-white hover:bg-neutral-700 print:hidden"
                          >
                            <RefreshCw className="w-4 h-4" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </>
          )}

          <Link
            to="/mealprep"
            className="w-full bg-neutral-900 border border-orange-500/40 py-3 rounded-xl flex items-center justify-center gap-2 mt-4 text-xs font-bold text-orange-400 uppercase tracking-widest"
          >
            <ChefHat className="w-4 h-4" /> Mealprep
          </Link>

          <button
            onClick={() => setShowModal(true)}
            disabled={loading}
            className="w-full bg-neutral-900 border border-neutral-800 py-3 rounded-xl print:hidden flex items-center justify-center gap-2 mt-4 text-xs font-bold text-neutral-400 uppercase tracking-widest"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Regenerate Plan"}
          </button>
        </div>
      )}

      {/* MODAL: COMÍ OTRA COSA (reemplazo de una comida del plan) */}
      {replaceKey && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-end sm:items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="replace-title">
          <div className="bg-neutral-950 border border-neutral-800 w-full max-w-md rounded-3xl overflow-hidden shadow-2xl max-h-[80vh] flex flex-col">
            <div className="p-4 border-b border-neutral-800">
              <div className="flex justify-between items-center mb-3">
                <h2 id="replace-title" className="text-lg font-bold text-white">¿Qué comiste en vez?</h2>
                <button onClick={() => { setReplaceKey(null); setReplaceQuery(''); }} aria-label="Cerrar" className="text-neutral-500 hover:text-white p-2">✕</button>
              </div>
              <input
                type="search"
                autoFocus
                value={replaceQuery}
                onChange={e => setReplaceQuery(e.target.value)}
                placeholder="Buscar en el Cookbook..."
                aria-label="Buscar receta del Cookbook"
                className="w-full bg-neutral-900 border border-neutral-800 text-white rounded-xl py-2 px-3 text-sm focus:outline-none focus:border-orange-500"
              />
            </div>
            <ul className="overflow-y-auto flex-1 p-2">
              {replaceOptions.map(r => (
                <li key={r.id}>
                  <button onClick={() => replaceWith(r)} className="w-full text-left p-3 rounded-lg hover:bg-neutral-800 text-sm">
                    <div className="text-white">{r.title}</div>
                    <div className="text-neutral-500 text-xs">{Math.round(r.macros.calories)} kcal · {Math.round(r.macros.protein)}g pro</div>
                  </button>
                </li>
              ))}
              {replaceOptions.length === 0 && <li className="p-3 text-sm text-neutral-500">No hay recetas con ese nombre.</li>}
            </ul>
            <div className="p-4 border-t border-neutral-800">
              <button onClick={() => replaceWith(null)} className="w-full bg-neutral-900 border border-neutral-700 text-white py-3 rounded-xl text-sm font-bold flex items-center justify-center gap-2">
                <Utensils className="w-4 h-4" /> No está en el Cookbook (no suma puntos)
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL DE RECETA SELECCIONADA */}
      {selectedRecipe && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-end sm:items-center justify-center p-4">
          <div className="bg-neutral-950 border border-neutral-800 w-full max-w-md rounded-3xl overflow-hidden shadow-2xl max-h-[90vh] flex flex-col">
            <div className="p-6 overflow-y-auto">
              <div className="flex justify-between items-start mb-6">
                <h2 className="text-2xl font-bold text-white">{selectedRecipe.title}</h2>
                <button onClick={() => setSelectedRecipe(null)} className="text-neutral-500 hover:text-white p-2">✕</button>
              </div>

              {(selectedRecipe.imageUrl || selectedRecipe.thumbnail_url) && (
                <div className="w-full h-48 bg-neutral-900 rounded-xl mb-6 overflow-hidden relative">
                  <img 
                    src={selectedRecipe.imageUrl || selectedRecipe.thumbnail_url} 
                    alt={selectedRecipe.title} 
                    className="w-full h-full object-cover"
                    referrerPolicy="no-referrer"
                    onError={(e) => {
                      (e.target as HTMLImageElement).src = 'https://placehold.co/600x400/1a1a1a/4a4a4a?text=No+Image';
                    }}
                  />
                </div>
              )}

              <div className="grid grid-cols-4 gap-2 mb-8 bg-neutral-900 p-3 rounded-xl border border-neutral-800 text-center text-sm font-mono">
                <div><div className="text-orange-500 font-bold">{selectedRecipe.macros?.calories || 0}</div><div className="text-[10px] text-neutral-500">kCal</div></div>
                <div><div className="text-white font-bold">{selectedRecipe.macros?.protein || 0}g</div><div className="text-[10px] text-neutral-500">Pro</div></div>
                <div><div className="text-white font-bold">{selectedRecipe.macros?.carbs || 0}g</div><div className="text-[10px] text-neutral-500">Carb</div></div>
                <div><div className="text-white font-bold">{selectedRecipe.macros?.fat || 0}g</div><div className="text-[10px] text-neutral-500">Fat</div></div>
              </div>

              <h3 className="font-bold text-sm text-neutral-400 uppercase tracking-widest mb-3">Ingredients</h3>
              <ul className="mb-8 space-y-2">
                {selectedRecipe.ingredients?.map((ing, i) => (
                  <li key={i} className="text-sm flex justify-between border-b border-neutral-800/50 pb-2">
                    <span className="text-white">{ing.name}</span>
                    <span className="text-neutral-500">{ing.amount}</span>
                  </li>
                ))}
              </ul>

              <h3 className="font-bold text-sm text-neutral-400 uppercase tracking-widest mb-3">Instructions</h3>
              <ol className="space-y-4 mb-4">
                {selectedRecipe.instructions?.map((step, i) => (
                  <li key={i} className="text-sm text-neutral-300 flex gap-3">
                    <span className="text-orange-500 font-mono font-bold">{i + 1}.</span>
                    <span className="leading-relaxed">{step}</span>
                  </li>
                ))}
              </ol>
            </div>
            
            <div className="p-4 bg-neutral-900 border-t border-neutral-800 shrink-0">
               <button 
                onClick={() => eatRecipe(selectedRecipe)}
                className="w-full bg-orange-500 text-black font-bold py-4 rounded-xl flex items-center justify-center gap-2 shadow-lg shadow-orange-500/20"
              >
                <Plus className="w-5 h-5" />
                Add 1 Serving to Today
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
