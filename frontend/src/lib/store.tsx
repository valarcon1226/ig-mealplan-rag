import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { get, set } from 'idb-keyval';
import { EatEntry, Macros, Recipe, UserProfile } from './types';
import { format, subDays } from 'date-fns';

type StoreContextType = {
  recipes: Recipe[];
  setAllRecipes: (recipes: Recipe[]) => void;
  addRecipe: (recipe: Recipe) => void;
  deleteRecipe: (id: string) => void;
  updateRecipe: (id: string, updates: Partial<Recipe>) => void;
  markEaten: (id: string) => void;
  eatLog: EatEntry[];
  logMeal: (entry: Omit<EatEntry, 'id' | 'date' | 'at'>) => void;
  unlogMeal: (id: string) => void;
  streakDays: number;
  profile: UserProfile;
  updateProfile: (updates: Partial<UserProfile>) => void;
  dailyConsumption: { date: string; macros: typeof defaultProfile.dailyGoals; caloriesBurned: number };
  updateDailyConsumption: (updates: Partial<StoreContextType['dailyConsumption']>) => void;
  folderPosts: any[];
  setFolderPosts: (posts: any[]) => void;
  isLoading: boolean;
  loadFromCloud: (username: string) => Promise<void>;
  syncToCloud: () => Promise<void>;
  currentMealPlan: any | null;
  setCurrentMealPlan: (plan: any | null) => void;
};

const defaultProfile: UserProfile = {
  dailyGoals: { calories: 2000, protein: 150, carbs: 200, fat: 65, fiber: 25, sugar: 30 },
  streakDays: 0,
  lastActiveDate: '',
  menstrualCyclePhase: 'none',
};

// Recipes saved by older versions may lack fields the UI now relies on.
const normalizeRecipes = (list: any[]): Recipe[] => list.map(r => ({
  ...r,
  title: r.title ?? '',
  ingredients: r.ingredients ?? [],
  instructions: r.instructions ?? [],
  categories: r.categories ?? [],
  macros: { calories: 0, protein: 0, carbs: 0, fat: 0, ...r.macros },
}));

const today = () => format(new Date(), 'yyyy-MM-dd');
const ZERO_MACROS: Macros = { calories: 0, protein: 0, carbs: 0, fat: 0, fiber: 0, sugar: 0 };

export const sumMacros = (entries: EatEntry[]): Macros =>
  entries.reduce((acc, e) => {
    const m = e.macros;
    if (!m) return acc;
    return {
      calories: acc.calories + (m.calories ?? 0), protein: acc.protein + (m.protein ?? 0),
      carbs: acc.carbs + (m.carbs ?? 0), fat: acc.fat + (m.fat ?? 0),
      fiber: acc.fiber + (m.fiber ?? 0), sugar: acc.sugar + (m.sugar ?? 0),
    };
  }, ZERO_MACROS);

// Consecutive days with at least one eaten meal. Today counts once something is
// logged; until then the streak runs through yesterday so it doesn't reset in the morning.
function computeStreak(log: EatEntry[]): number {
  const days = new Set(log.map(e => e.date));
  let d = new Date();
  if (!days.has(format(d, 'yyyy-MM-dd'))) d = subDays(d, 1);
  let n = 0;
  while (days.has(format(d, 'yyyy-MM-dd'))) { n++; d = subDays(d, 1); }
  return n;
}

const StoreContext = createContext<StoreContextType | null>(null);

export const StoreProvider = ({ children }: { children: ReactNode }) => {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [profile, setProfile] = useState<UserProfile>(defaultProfile);
  const [dailyConsumption, setDailyConsumption] = useState({ 
    date: format(new Date(), 'yyyy-MM-dd'),
    macros: { calories: 0, protein: 0, carbs: 0, fat: 0, fiber: 0, sugar: 0 },
    caloriesBurned: 0 
  });
  const [eatLog, setEatLog] = useState<EatEntry[]>([]);
  const [folderPosts, setFolderPosts] = useState<any[]>([]);
  const [currentMealPlan, setCurrentMealPlanState] = useState<any | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const setCurrentMealPlan = (plan: any | null) => {
    setCurrentMealPlanState(plan);
    set('app_mealplan', plan);
  };

  const triggerSync = (currentProfile: UserProfile, currentRecipes: Recipe[]) => {
    if (!currentProfile.igUsername) return;
    fetch('/api/sync-user-data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: currentProfile.igUsername,
        profile: currentProfile,
        recipes: currentRecipes
      })
    }).catch(err => console.error('Cloud sync failed:', err));
  };

  const loadFromCloud = async (username: string) => {
    setIsLoading(true);
    try {
      const res = await fetch(`/api/get-user-data/${username}`);
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'success' && data.data) {
          const loadedProfile = { ...data.data.profile, igUsername: username };
          setProfile(loadedProfile);
          set('app_profile', loadedProfile);
          
          setRecipes(normalizeRecipes(data.data.recipes || []));
          set('app_recipes', data.data.recipes || []);
        }
      }
    } catch (e) {
      console.error('Failed to load from cloud', e);
    }
    setIsLoading(false);
  };

  const syncToCloud = async () => {
    triggerSync(profile, recipes);
  };

  useEffect(() => {
    const loadData = async () => {
      const storedRecipes = await get('app_recipes');
      if (storedRecipes) setRecipes(normalizeRecipes(storedRecipes));

      const storedProfile = await get('app_profile');
      // Older versions stored the Instagram password; keep only the username.
      try { localStorage.removeItem('ig_password'); } catch { /* storage blocked */ }
      if (storedProfile?.instagramApiKey) {
        try {
          const { username } = JSON.parse(storedProfile.instagramApiKey);
          storedProfile.instagramApiKey = JSON.stringify({ username });
          set('app_profile', storedProfile);
        } catch { /* not JSON: leave as is */ }
      }
      if (storedProfile) setProfile(storedProfile);

      const storedLog = await get('app_eat_log');
      if (storedLog) setEatLog(storedLog);

      const storedDaily = await get('app_daily');
      if (storedDaily && storedDaily.date === today()) {
        setDailyConsumption(storedDaily);
      }
      
      const storedPlan = await get('app_mealplan');
      if (storedPlan) {
        setCurrentMealPlanState(storedPlan);
      }
      
      setIsLoading(false);
    };
    loadData();
  }, []);


  const setAllRecipes = (newRecipes: Recipe[]) => {
    setRecipes(newRecipes);
    set('app_recipes', newRecipes);
    triggerSync(profile, newRecipes);
  };

  const addRecipe = (recipe: Recipe) => {
    const newRecipes = [...recipes, recipe];
    setRecipes(newRecipes);
    set('app_recipes', newRecipes);
    triggerSync(profile, newRecipes);
  };

  const deleteRecipe = (id: string) => {
    const newRecipes = recipes.filter(r => r.id !== id);
    setRecipes(newRecipes);
    set('app_recipes', newRecipes);
    triggerSync(profile, newRecipes);
  };

  // Functional form so several updates in one handler (e.g. replace = unlog + log) don't overwrite each other.
  const updateRecipeWith = (id: string, fn: (r: Recipe) => Partial<Recipe>) => {
    setRecipes(prev => {
      const newRecipes = prev.map(r => r.id === id ? { ...r, ...fn(r) } : r);
      set('app_recipes', newRecipes);
      triggerSync(profile, newRecipes);
      return newRecipes;
    });
  };

  const updateRecipe = (id: string, updates: Partial<Recipe>) => updateRecipeWith(id, () => updates);

  // Count a serving eaten (Cookbook or Planner) for the "Most eaten" tab.
  const markEaten = (id: string) =>
    updateRecipeWith(id, r => ({ timesEaten: (r.timesEaten ?? 0) + 1, lastEatenAt: Date.now() }));

  const saveLog = (fn: (log: EatEntry[]) => EatEntry[]) =>
    setEatLog(prev => {
      const next = fn(prev);
      set('app_eat_log', next);
      return next;
    });

  // Every eaten serving (Planner check, replacement, Cookbook "Add 1 Serving") goes through here.
  const logMeal = (entry: Omit<EatEntry, 'id' | 'date' | 'at'>) => {
    saveLog(log => [...log, { ...entry, id: crypto.randomUUID(), date: today(), at: Date.now() }]);
    if (entry.recipeId) markEaten(entry.recipeId);
  };

  const unlogMeal = (id: string) => {
    const entry = eatLog.find(e => e.id === id);
    if (!entry) return;
    saveLog(log => log.filter(e => e.id !== id));
    if (entry.recipeId) updateRecipeWith(entry.recipeId, r => ({ timesEaten: Math.max(0, (r.timesEaten ?? 1) - 1) }));
  };

  const updateProfile = (updates: Partial<UserProfile>) => {
    const newProfile = { ...profile, ...updates };
    setProfile(newProfile);
    set('app_profile', newProfile);
    triggerSync(newProfile, recipes);
  };

  const updateDailyConsumption = (updates: Partial<StoreContextType['dailyConsumption']>) => {
    const newDaily = { ...dailyConsumption, ...updates };
    setDailyConsumption(newDaily);
    set('app_daily', newDaily);
  };

  // Today's macros are derived from the log, so un-checking a meal subtracts it.
  const todaysConsumption = { ...dailyConsumption, macros: sumMacros(eatLog.filter(e => e.date === today())) };
  const streakDays = computeStreak(eatLog);

  return (
    <StoreContext.Provider value={{ recipes, setAllRecipes, addRecipe, deleteRecipe, updateRecipe, markEaten, eatLog, logMeal, unlogMeal, streakDays, profile, updateProfile, dailyConsumption: todaysConsumption, updateDailyConsumption, folderPosts, setFolderPosts, isLoading, loadFromCloud, syncToCloud, currentMealPlan, setCurrentMealPlan }}>
      {children}
    </StoreContext.Provider>
  );
};

export const useStore = () => {
  const context = useContext(StoreContext);
  if (!context) throw new Error("useStore must be used within StoreProvider");
  return context;
};
