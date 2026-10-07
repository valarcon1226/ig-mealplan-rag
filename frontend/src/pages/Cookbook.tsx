import { useState, useMemo, useEffect } from 'react';
import { useStore } from '../lib/store';
import { Search, Plus, Minus, ShoppingCart, Heart, Sparkles, Loader2, SlidersHorizontal } from 'lucide-react';
import toast from 'react-hot-toast';
import { Recipe } from '../lib/types';
import RecipeImport from './RecipeImport';
import { GroceryList } from './Pantry';
import ExportButtons from '../lib/ExportButtons';
import RecipeImage from '../lib/RecipeImage';
import { fitsProfile, likeScore } from '../lib/diet';

export default function Cookbook() {
  const { recipes, setAllRecipes } = useStore();
  const [activeTab, setActiveTab] = useState<'recipes' | 'add'>('recipes');
  
  return (
    <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 pb-24">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight text-white mb-4">Cookbook</h1>
        <div className="flex bg-neutral-900 rounded-xl p-1 mb-6 border border-neutral-800">
          <button 
            onClick={() => setActiveTab('recipes')}
            className={`flex-1 py-2 text-sm font-bold rounded-lg transition-colors ${activeTab === 'recipes' ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
          >
            Recipes
          </button>
          <button 
            onClick={() => setActiveTab('add')}
            className={`flex-1 py-2 text-sm font-bold rounded-lg transition-colors ${activeTab === 'add' ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
          >
            Add Recipe
          </button>
        </div>
      </header>

      {activeTab === 'recipes' && <RecipesTab recipes={recipes} setAllRecipes={setAllRecipes} />}
      {activeTab === 'add' && <RecipeImport />}
    </div>
  );
}

function RecipesTab({ recipes, setAllRecipes }: any) {
  const { profile, updateRecipe, logMeal } = useStore();
  const [search, setSearch] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [view, setView] = useState<View>('all');
  const [presets, setPresets] = useState<string[]>([]);
  const [showFilters, setShowFilters] = useState(false);
  // AI search: the backend turns the query into filters + vector ranking.
  const [ai, setAi] = useState<{ query: string; ids: string[]; filters: Record<string, any> } | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
// Keep the id, not a snapshot, so favorite/rating changes show up while it's open.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedRecipe = recipes.find((r: Recipe) => r.id === selectedId) ?? null;
  const setSelectedRecipe = (r: Recipe | null) => setSelectedId(r?.id ?? null);
  const [loadingBackend, setLoadingBackend] = useState(false);

  useEffect(() => {
    const fetchRecipes = async () => {
      setLoadingBackend(true);
      try {
        const res = await fetch("/api/recipes", { method: "GET" });
        if (res.ok) {
          const data = await res.json();
          const backendRecipes = Array.isArray(data) ? data : data.recipes || [];
          const localRecipes = [...recipes];
          const currentIds = new Set(localRecipes.map(r => String(r.id)));
          
          for (const newRecipe of backendRecipes) {
            newRecipe.id = String(newRecipe.id);
            if (newRecipe.macros) {
              if (!currentIds.has(newRecipe.id)) {
                localRecipes.push({ ...newRecipe, id: newRecipe.id || crypto.randomUUID() });
              } else {
                const index = localRecipes.findIndex(r => String(r.id) === newRecipe.id);
                localRecipes[index] = { ...localRecipes[index], ...newRecipe };
              }
            }
          }
          setAllRecipes(localRecipes);
        }
      } catch (err) {
        console.error("Error fetching recipes:", err);
      } finally {
        setLoadingBackend(false);
      }
    };
    fetchRecipes();
  }, []);

  // Diet & preferences from the profile: hide what doesn't fit, favorites first.
  const hasDietFilter = !!(profile.dietaryRestrictions?.length || profile.avoidFoods?.length);
  const { filteredRecipes, hiddenCount } = useMemo(() => {
    const q = search.toLowerCase();
    const byId = new Map(recipes.map((r: Recipe) => [r.id, r]));
    // AI results come ranked by relevance; otherwise plain text match on title/tags.
    const matching: Recipe[] = ai
      ? ai.ids.map(id => byId.get(id)).filter(Boolean) as Recipe[]
      : recipes.filter((r: Recipe) =>
          r.title.toLowerCase().includes(q) || r.categories.some((c: string) => c.toLowerCase().includes(q)));
    const fitting = showAll ? matching : matching.filter((r: Recipe) => fitsProfile(r, profile));
    const active = PRESETS.filter(f => presets.includes(f.label));
    const byView = fitting.filter(r => VIEWS[view].keep(r) && active.every(f => f.test(r)));
    const sorted = ai && view === 'all' ? byView : [...byView].sort((a: Recipe, b: Recipe) =>
      VIEWS[view].order(a, b) || likeScore(b, profile) - likeScore(a, profile) || (b.createdAt || 0) - (a.createdAt || 0));
    return { filteredRecipes: sorted, hiddenCount: matching.length - fitting.length };
  }, [recipes, search, profile, showAll, view, presets, ai]);

  const runAiSearch = async () => {
    const q = search.trim();
    if (!q) return;
    setAiLoading(true);
    try {
      const res = await fetch('/api/recipes/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ q })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || 'Search failed');
      setAi({ query: q, ids: data.ids, filters: data.filters });
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setAiLoading(false);
    }
  };

  const togglePreset = (label: string) =>
    setPresets(prev => prev.includes(label) ? prev.filter(p => p !== label) : [...prev, label]);

  const toggleFavorite = (r: Recipe) => updateRecipe(r.id, { favorite: !r.favorite });
  // Tapping the current rating again clears it.
  const rate = (r: Recipe, stars: number) => updateRecipe(r.id, { rating: r.rating === stars ? undefined : stars });

  // Recipe macros are already PER SERVING (nutricion_por_porcion in the backend).
  const eatRecipe = (recipe: Recipe) => {
    logMeal({ title: recipe.title, recipeId: recipe.id, macros: recipe.macros });
    setSelectedRecipe(null);
  };

  return (
    <>
      <form className="relative mb-2" role="search" onSubmit={e => { e.preventDefault(); runAiSearch(); }}>
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" aria-hidden="true" />
        <input
          type="search"
          value={search}
          onChange={e => { setSearch(e.target.value); setAi(null); }}
          placeholder="Try: postre sin azúcar, cena rápida con pollo..."
          aria-label="Search recipes"
          className="w-full bg-neutral-900 border border-neutral-800 text-white rounded-xl py-3 pl-10 pr-12 text-sm focus:outline-none focus:border-orange-500 transition-colors"
        />
        <button type="submit" disabled={aiLoading || !search.trim()} aria-label="Search with AI"
          className="absolute right-2 top-1/2 -translate-y-1/2 p-2 rounded-lg text-orange-500 hover:bg-neutral-800 disabled:opacity-40">
          {aiLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
        </button>
      </form>
      <p className="text-[11px] mb-6 text-neutral-500" aria-live="polite">
        {ai ? (
          <>
            <Sparkles className="w-3 h-3 inline -mt-0.5 text-orange-500" aria-hidden="true" /> {describeFilters(ai.filters) || 'Semantic match'} · {filteredRecipes.length} results{' '}
            <button onClick={() => setAi(null)} className="text-orange-500 font-bold hover:underline">Clear</button>
          </>
        ) : 'Typing filters by name. Press Enter or ✨ to search by meaning with AI.'}
      </p>

      {hasDietFilter && (
        <div className="flex items-center justify-between gap-3 -mt-3 mb-6 text-xs text-neutral-500">
          <span className="min-w-0">
            Filtered by your profile: {[...(profile.dietaryRestrictions ?? []), ...(profile.avoidFoods ?? []).map(a => `sin ${a}`)].join(' · ')}
            {!showAll && hiddenCount > 0 && ` (${hiddenCount} hidden)`}
          </span>
          <button onClick={() => setShowAll(v => !v)} aria-pressed={showAll} className="shrink-0 text-orange-500 font-bold hover:underline">
            {showAll ? 'Apply filter' : 'Show all'}
          </button>
        </div>
      )}

      <div className={`flex items-center gap-2 ${showFilters ? 'mb-3' : 'mb-6'}`}>
        <div className="flex gap-2 flex-1 min-w-0 overflow-x-auto -mx-1 px-1" role="tablist" aria-label="Recipe views">
          {(Object.keys(VIEWS) as View[]).map(v => (
            <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)}
              className={`shrink-0 px-3 py-1.5 rounded-full text-xs font-bold border transition-colors ${view === v ? 'bg-orange-500 border-orange-500 text-black' : 'bg-neutral-900 border-neutral-800 text-neutral-400 hover:text-white'}`}>
              {VIEWS[v].label}
            </button>
          ))}
        </div>
        <button
          onClick={() => setShowFilters(s => !s)}
          aria-expanded={showFilters}
          aria-controls="cookbook-filters"
          className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold border transition-colors ${showFilters || presets.length ? 'bg-neutral-100 border-neutral-100 text-black' : 'bg-neutral-900 border-neutral-800 text-neutral-400 hover:text-white'}`}
        >
          <SlidersHorizontal className="w-3.5 h-3.5" aria-hidden="true" />
          Filtros{presets.length > 0 && ` (${presets.length})`}
        </button>
      </div>

      {showFilters && (
        <div id="cookbook-filters" role="group" aria-label="Filtros rápidos" className="bg-neutral-900 border border-neutral-800 rounded-2xl p-3 mb-6">
          <div className="flex flex-wrap gap-2">
            {PRESETS.map(f => {
              const on = presets.includes(f.label);
              return (
                <button key={f.label} onClick={() => togglePreset(f.label)} aria-pressed={on}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-colors ${on ? 'bg-orange-500 border-orange-500 text-black' : 'bg-neutral-950 border-neutral-800 text-neutral-400 hover:text-white'}`}>
                  {f.label}
                </button>
              );
            })}
          </div>
          {presets.length > 0 && (
            <button onClick={() => setPresets([])} className="mt-3 text-xs text-neutral-400 hover:text-white underline">
              Limpiar filtros
            </button>
          )}
        </div>
      )}

      {filteredRecipes.length === 0 ? (
        <div className="text-center py-20 text-neutral-500">
          <BookOpenIcon className="w-12 h-12 mx-auto mb-4 opacity-20" />
          <p>{presets.length || ai ? 'No recipes match these filters.' : VIEWS[view].empty}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {filteredRecipes.map((recipe: Recipe) => (
            <div 
              key={recipe.id} 
              onClick={() => setSelectedRecipe(recipe)}
              className="bg-neutral-900 border border-neutral-800 rounded-2xl p-4 cursor-pointer hover:border-orange-500/50 transition-colors flex flex-col overflow-hidden relative"
            >
              <RecipeImage recipe={recipe} className="h-32 mb-3" />

              <button
                onClick={e => { e.stopPropagation(); toggleFavorite(recipe); }}
                aria-label={recipe.favorite ? `Remove ${recipe.title} from favorites` : `Add ${recipe.title} to favorites`}
                aria-pressed={!!recipe.favorite}
                className="absolute top-6 right-6 z-10 p-1.5 rounded-full bg-black/60 backdrop-blur-sm text-white hover:text-orange-400">
                <Heart className={`w-4 h-4 ${recipe.favorite ? 'fill-orange-500 text-orange-500' : ''}`} />
              </button>
              <h3 className="font-bold text-sm leading-tight mb-2 pr-6">{recipe.title}</h3>
              {(!!recipe.rating || !!recipe.timesEaten) && (
                <div className="flex items-center gap-2 text-[11px] text-neutral-500 mb-2">
                  {!!recipe.rating && <Stars value={recipe.rating} />}
                  {!!recipe.timesEaten && <span>eaten {recipe.timesEaten}×</span>}
                </div>
              )}

              <div className="flex justify-between items-end mt-auto pt-2 border-t border-neutral-800">
                <div className="text-xs font-mono text-neutral-500">
                  <span className="text-orange-400 font-bold">{recipe.macros.calories}</span> kcal
                </div>
                <div className="text-xs text-neutral-600 bg-neutral-950 px-2 py-1 rounded-md">
                  {recipe.servings} svg
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedRecipe && (
        <RecipeDetail
          key={selectedRecipe.id}
          recipe={selectedRecipe}
          onClose={() => setSelectedRecipe(null)}
          onEat={() => eatRecipe(selectedRecipe)}
          onToggleFavorite={() => toggleFavorite(selectedRecipe)}
          onRate={stars => rate(selectedRecipe, stars)}
        />
      )}
    </>
  );
}

// "200 g" x1.5 -> "300 g"; handles "1/2 taza" and "1 1/2 tazas". Non-numeric ("al gusto") stays as is.
function scaleAmount(amount: string, factor: number): string {
  if (factor === 1 || !amount) return amount;
  const m = amount.trim().match(/^(\d+\s+\d+\/\d+|\d+\/\d+|\d+(?:[.,]\d+)?)(.*)$/);
  if (!m) return amount;
  const qty = m[1].split(/\s+/).reduce((sum, part) => {
    const [a, b] = part.replace(',', '.').split('/');
    return sum + (b ? Number(a) / Number(b) : Number(a));
  }, 0);
  if (!Number.isFinite(qty)) return amount;
  return `${Number((qty * factor).toFixed(2))}${m[2]}`;
}

// Quick filters (all selected ones must match). Macros are per serving.
const PRESETS: { label: string; test: (r: Recipe) => boolean }[] = [
  { label: 'Bajo en azúcar', test: r => (r.macros.sugar ?? Infinity) <= 5 },
  { label: 'Alta proteína', test: r => r.macros.protein >= 25 },
  { label: 'Bajo en calorías', test: r => r.macros.calories > 0 && r.macros.calories <= 400 },
  { label: 'Vegano', test: r => !!r.diet?.includes('Vegano') },
  { label: 'Vegetariano', test: r => !!r.diet?.includes('Vegetariano') },
  { label: 'Sin gluten', test: r => !!r.diet?.includes('Sin Gluten') },
  { label: 'Italiana', test: r => r.cuisine === 'italiana' },
  { label: 'Asiática', test: r => r.cuisine === 'asiatica' },
  { label: 'Mexicana', test: r => r.cuisine === 'mexicana' },
  { label: 'Mediterránea', test: r => r.cuisine === 'mediterranea' },
];

// Human-readable summary of what the AI understood, e.g. "postre · ≤5 g azúcar · sin cebolla".
function describeFilters(f: Record<string, any>): string {
  return [
    f.tipo_comida, f.cocina,
    f.max_calorias != null && `≤${f.max_calorias} kcal`,
    f.min_proteina != null && `≥${f.min_proteina} g proteína`,
    f.max_azucar != null && `≤${f.max_azucar} g azúcar`,
    f.max_tiempo_min != null && `≤${f.max_tiempo_min} min`,
    ...(f.dietas ?? []),
    ...(f.incluir_ingredientes ?? []).map((i: string) => `con ${i.split('/')[0]}`),
    ...(f.excluir_ingredientes ?? []).map((i: string) => `sin ${i.split('/')[0]}`),
    f.texto_semantico && `"${f.texto_semantico}"`,
  ].filter(Boolean).join(' · ');
}

type View = 'all' | 'favorites' | 'eaten' | 'rated';
const VIEWS: Record<View, { label: string; keep: (r: Recipe) => boolean; order: (a: Recipe, b: Recipe) => number; empty: string }> = {
  all: { label: 'All', keep: () => true, order: () => 0, empty: 'No recipes found.' },
  favorites: { label: '♥ Favorites', keep: r => !!r.favorite, order: () => 0, empty: 'No favorites yet. Tap the heart on a recipe.' },
  eaten: { label: 'Most eaten', keep: r => !!r.timesEaten, order: (a, b) => (b.timesEaten ?? 0) - (a.timesEaten ?? 0), empty: 'Nothing logged yet. Use "Add 1 Serving to Today".' },
  rated: { label: 'Top rated', keep: r => !!r.rating, order: (a, b) => (b.rating ?? 0) - (a.rating ?? 0), empty: 'No ratings yet. Open a recipe and give it stars.' },
};

function Stars({ value }: { value: number }) {
  return (
    <span className="text-orange-400" aria-label={`${value} of 5 stars`}>
      {'★'.repeat(value)}<span className="text-neutral-700">{'★'.repeat(5 - value)}</span>
    </span>
  );
}

function RecipeDetail({ recipe, onClose, onEat, onToggleFavorite, onRate }: {
  recipe: Recipe; onClose: () => void; onEat: () => void; onToggleFavorite: () => void; onRate: (stars: number) => void;
}) {
  const baseServings = recipe.servings > 0 ? recipe.servings : 1;
  const [servings, setServings] = useState(baseServings);
  const [showShopping, setShowShopping] = useState(false);
  const factor = servings / baseServings;
  const ingredients = recipe.ingredients.map(ing => ({ ...ing, amount: scaleAmount(ing.amount, factor) }));
  const m = recipe.macros;

  const exportText = () => [
    recipe.title,
    `${servings} porciones · por porción: ${m.calories} kcal, ${m.protein} g proteína, ${m.carbs} g carbs, ${m.fat} g grasa`,
    '',
    'Ingredientes:',
    ...ingredients.map(i => `- ${i.name}${i.amount ? `: ${i.amount}` : ''}`),
    ...(recipe.instructions.length ? ['', 'Preparación:', ...recipe.instructions.map((s, i) => `${i + 1}. ${s}`)] : []),
    ...(recipe.video_url ? ['', recipe.video_url] : []),
  ].join('\n');

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-end sm:items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={recipe.title}>
      <div className="bg-neutral-950 border border-neutral-800 w-full max-w-md rounded-3xl overflow-hidden shadow-2xl max-h-[90vh] flex flex-col">
        <div className="p-6 overflow-y-auto">
          <div className="flex justify-between items-start mb-3">
            <h2 className="text-2xl font-bold">{recipe.title}</h2>
            <div className="flex shrink-0">
              <button onClick={onToggleFavorite} aria-pressed={!!recipe.favorite}
                aria-label={recipe.favorite ? 'Remove from favorites' : 'Add to favorites'}
                className="p-2 text-neutral-500 hover:text-orange-400">
                <Heart className={`w-5 h-5 ${recipe.favorite ? 'fill-orange-500 text-orange-500' : ''}`} />
              </button>
              <button onClick={onClose} aria-label="Close" className="text-neutral-500 hover:text-white p-2">✕</button>
            </div>
          </div>
          <div className="flex items-center justify-between mb-6">
            <div className="flex" role="group" aria-label="Your rating">
              {[1, 2, 3, 4, 5].map(n => (
                <button key={n} onClick={() => onRate(n)} aria-label={`Rate ${n} of 5`} aria-pressed={recipe.rating === n}
                  className={`text-xl px-0.5 transition-colors ${(recipe.rating ?? 0) >= n ? 'text-orange-500' : 'text-neutral-700 hover:text-neutral-500'}`}>
                  ★
                </button>
              ))}
            </div>
            <span className="text-xs text-neutral-500">
              {recipe.timesEaten ? `Eaten ${recipe.timesEaten}×` : 'Not eaten yet'}
            </span>
          </div>

          <RecipeImage recipe={recipe} className="h-48 mb-6" />

          <div className="grid grid-cols-4 gap-2 mb-1 bg-neutral-900 p-3 rounded-xl border border-neutral-800 text-center text-sm font-mono">
            <div><div className="text-orange-500 font-bold">{m.calories}</div><div className="text-[10px] text-neutral-500">kCal</div></div>
            <div><div className="text-white font-bold">{m.protein}g</div><div className="text-[10px] text-neutral-500">Pro</div></div>
            <div><div className="text-white font-bold">{m.carbs}g</div><div className="text-[10px] text-neutral-500">Carb</div></div>
            <div><div className="text-white font-bold">{m.fat}g</div><div className="text-[10px] text-neutral-500">Fat</div></div>
          </div>
          <p className="text-[10px] text-neutral-500 text-center mb-4">per serving</p>
          {!!recipe.diet?.length && (
            <ul className="flex flex-wrap gap-1.5 mb-6" aria-label="Fits these diets">
              {recipe.diet.map(d => (
                <li key={d} className="text-[10px] font-bold text-green-400 bg-green-400/10 px-2 py-0.5 rounded-full">{d}</li>
              ))}
            </ul>
          )}

          <div className="mb-8">
            <ExportButtons title={recipe.title} getText={exportText} />
          </div>

          <div className="flex items-center justify-between mb-3">
            <h3 className="font-bold text-sm text-neutral-400 uppercase tracking-widest">Ingredients</h3>
            <div className="flex items-center gap-2 bg-neutral-900 border border-neutral-800 rounded-lg p-1">
              <button onClick={() => setServings(s => Math.max(1, s - 1))} disabled={servings <= 1} aria-label="Fewer servings"
                className="p-1 text-neutral-400 hover:text-white disabled:opacity-30"><Minus className="w-3.5 h-3.5" /></button>
              <span className="text-xs font-mono text-white min-w-[4.5rem] text-center" aria-live="polite">{servings} serving{servings === 1 ? '' : 's'}</span>
              <button onClick={() => setServings(s => Math.min(50, s + 1))} disabled={servings >= 50} aria-label="More servings"
                className="p-1 text-neutral-400 hover:text-white disabled:opacity-30"><Plus className="w-3.5 h-3.5" /></button>
            </div>
          </div>
          <ul className="mb-4 space-y-2">
            {ingredients.map((ing, i) => (
              <li key={i} className="text-sm flex justify-between gap-3 border-b border-neutral-800/50 pb-2">
                <span className="text-white">{ing.name}</span>
                <span className="text-neutral-500 shrink-0">{ing.amount}</span>
              </li>
            ))}
          </ul>

          <button onClick={() => setShowShopping(v => !v)} aria-expanded={showShopping}
            className="w-full mb-8 border border-dashed border-neutral-700 rounded-xl py-3 text-sm font-bold text-neutral-300 flex items-center justify-center gap-2 hover:border-orange-500 transition-colors">
            <ShoppingCart className="w-4 h-4" aria-hidden="true" />
            {showShopping ? 'Hide shopping list' : 'Shopping list for this recipe'}
          </button>
          {showShopping && (
            <div className="mb-8">
              <GroceryList meals={[{ ingredients }]} title={`Compras: ${recipe.title}`} />
            </div>
          )}

          <h3 className="font-bold text-sm text-neutral-400 uppercase tracking-widest mb-3">Instructions</h3>
          <ol className="space-y-4 mb-4">
            {recipe.instructions.map((step, i) => (
              <li key={i} className="text-sm text-neutral-300 flex gap-3">
                <span className="text-orange-500 font-mono font-bold">{i + 1}.</span>
                <span className="leading-relaxed">{step}</span>
              </li>
            ))}
          </ol>
        </div>

        <div className="p-4 bg-neutral-900 border-t border-neutral-800 shrink-0">
          <button
            onClick={onEat}
            className="w-full bg-orange-500 text-black font-bold py-4 rounded-xl flex items-center justify-center gap-2 shadow-lg shadow-orange-500/20"
          >
            <Plus className="w-5 h-5" />
            Add 1 Serving to Today
          </button>
        </div>
      </div>
    </div>
  );
}

function BookOpenIcon(props: any) {
  return (
    <svg {...props} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
    </svg>
  );
}
