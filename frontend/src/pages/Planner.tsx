import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useStore } from '../lib/store';
import { planIdOf, mealMacros, dayEntries, todayPlanIndex } from '../lib/plan';
import { Calendar as CalIcon, ShoppingBag, Send, FileDown, Loader2, Plus, ChevronLeft, ChevronRight, ChefHat, Check, RefreshCw, Utensils } from 'lucide-react';
import { Recipe } from '../lib/types';
import { addDays, differenceInCalendarDays, format } from 'date-fns';
import { es } from 'date-fns/locale';
import RecipeImage from '../lib/RecipeImage';

export default function Planner() {
  const { profile, recipes, setCurrentMealPlan, currentMealPlan, eatLog, logMeal, unlogMeal, planStart } = useStore();
  const [plan, setPlan] = useState<any>(currentMealPlan); // puede ser array o objeto
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);

  const [numDays, setNumDays] = useState(1);
  const [fromPantry, setFromPantry] = useState(false);
  const [planNote, setPlanNote] = useState<string | null>(null);
  // Both buttons open the same modal; the pantry one comes with "use only my pantry" checked.
  const openGenerate = (pantry: boolean) => { setFromPantry(pantry); setShowModal(true); };
  // Opens on today's plan day.
  const [currentDayIndex, setCurrentDayIndex] = useState(() => todayPlanIndex(currentMealPlan, planStart));

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
    setPlanNote(null);
    try {
      const res = await fetch(fromPantry ? '/api/mealplan/from-pantry' : '/api/mealplan/generate', {
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
      } else if (fromPantry) {
        // Days that fit the pantry, plus "con lo que tienes alcanza para N días…".
        setPlanNote(data.message);
        if (data.plan.length) {
          setPlan(data.plan);
          setCurrentMealPlan(data.plan);
          setCurrentDayIndex(0);
        }
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
    // The Cookbook copy has the current photo and category (the plan keeps what it had when generated).
    const saved = recipes.find(r => r.id === String(meal.recipe_id));
    const recipeToOpen: Recipe = {
      id: String(meal.recipe_id),
      title: meal.nombre,
      thumbnail_url: saved?.thumbnail_url || meal.thumbnail_url,
      category: saved?.category,
      video_url: meal.video_url,
      ingredients: meal.ingredients || [],
      instructions: meal.instructions || [],
      macros: mealMacros(meal),
      servings: 1,
      categories: saved?.categories ?? [],
      createdAt: Date.now()
    };
    setSelectedRecipe(recipeToOpen);
  };

  const isWeekly = Array.isArray(plan);
  const currentPlan = isWeekly ? plan[currentDayIndex] : plan;
  const planId = planIdOf(plan);
  const keyFor = (i: number) => `${planId}:${currentDayIndex}:${i}`;
  const entryFor = (key: string) => eatLog.find(e => e.planKey === key);
  const dayDone = dayEntries(eatLog, planId, currentDayIndex).length;
  const dayMealCount = currentPlan?.meals?.length ?? 0;

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

            <label className="flex items-start gap-3 p-3 bg-black rounded-lg border border-neutral-800 cursor-pointer">
              <input type="checkbox" checked={fromPantry} onChange={e => setFromPantry(e.target.checked)}
                className="w-5 h-5 mt-0.5 accent-orange-500" />
              <span>
                <span className="text-white font-medium block">Usar solo lo que tengo en la despensa</span>
                <span className="text-xs text-neutral-500">Arma los días que alcancen con tu despensa (puede faltar algo chico) y te dice cuántos días te dura.</span>
              </span>
            </label>

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

      {/* Pantry plan result: "con lo que tienes alcanza para N días…" (also when it's 0 and no plan shows) */}
      {planNote && (
        <div role="status" className="bg-orange-500/10 border border-orange-500/30 text-orange-200 rounded-xl p-3 text-sm flex items-start justify-between gap-3 print:hidden">
          <span>{planNote}</span>
          <Link to="/pantry" className="shrink-0 text-orange-400 font-bold hover:text-orange-300">Ir a mercado →</Link>
        </div>
      )}

      {!plan ? (
        <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-8 text-center print:hidden">
          <CalIcon className="w-12 h-12 mx-auto text-orange-500 mb-4" />
          <h2 className="font-bold text-xl mb-2">Ready for the day?</h2>
          <p className="text-sm text-neutral-400 mb-6 pb-6 border-b border-neutral-800">Use your saved recipes to build a balanced, goal-oriented meal plan.</p>
          <button
            onClick={() => openGenerate(false)}
            disabled={loading}
            className="w-full bg-orange-500 text-black font-bold py-3 rounded-xl flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : "Generate New Plan"}
          </button>
          <button
            onClick={() => openGenerate(true)}
            disabled={loading}
            className="w-full mt-3 bg-neutral-950 border border-orange-500/40 text-orange-400 font-bold py-3 rounded-xl flex items-center justify-center gap-2"
          >
            <ShoppingBag className="w-4 h-4" aria-hidden="true" /> Planear con mi despensa
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
                {dayLabel(planStart, currentDayIndex)}
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
              {/* Detailed stats (real score, macros vs targets) live on the Dashboard ("Today"). */}
              <div className="flex items-center justify-between text-xs text-neutral-500 px-1">
                <span>
                  <span className={dayDone === dayMealCount && dayMealCount > 0 ? 'text-green-400 font-bold' : 'text-white font-bold'}>{dayDone}/{dayMealCount}</span> comidas
                  {' · '}{Math.round(currentPlan.totals.calorias)} kcal
                </span>
                <Link to="/" className="text-orange-400 hover:text-orange-300 print:hidden">Ver resumen →</Link>
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
                            <div className="text-neutral-500 text-xs mt-1">{Math.round(meal.calorias)} kcal · {Math.round(meal.proteinas)}g pro</div>
                            {meal.faltantes?.length > 0 && (
                              <div className="text-yellow-500 text-xs mt-0.5">Te falta: {meal.faltantes.join(', ')}</div>
                            )}
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

          <div className="grid grid-cols-2 gap-2 mt-4 print:hidden">
            <button
              onClick={() => openGenerate(false)}
              disabled={loading}
              className="bg-neutral-900 border border-neutral-800 py-3 rounded-xl flex items-center justify-center gap-2 text-xs font-bold text-neutral-400 uppercase tracking-widest"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Regenerate Plan"}
            </button>
            <button
              onClick={() => openGenerate(true)}
              disabled={loading}
              className="bg-neutral-900 border border-orange-500/40 py-3 rounded-xl flex items-center justify-center gap-2 text-xs font-bold text-orange-400 uppercase tracking-widest"
            >
              <ShoppingBag className="w-4 h-4" aria-hidden="true" /> Con mi despensa
            </button>
          </div>
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

              <RecipeImage key={selectedRecipe.id} recipe={selectedRecipe} className="h-48 mb-6" />

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

// Real date of a plan day (day 1 = the day the plan was generated), e.g. "Hoy · miércoles 7 oct".
function dayLabel(planStart: string | null, index: number): string {
  if (!planStart) return `Día ${index + 1}`;
  const date = addDays(new Date(`${planStart}T00:00`), index);
  const name = format(date, "EEEE d MMM", { locale: es });
  const rel = differenceInCalendarDays(date, new Date());
  return rel === 0 ? `Hoy · ${name}` : rel === 1 ? `Mañana · ${name}` : rel === -1 ? `Ayer · ${name}` : name;
}
