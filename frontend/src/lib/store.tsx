import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { get, set } from 'idb-keyval';
import { Recipe, UserProfile } from './types';
import { format } from 'date-fns';

type StoreContextType = {
  recipes: Recipe[];
  setAllRecipes: (recipes: Recipe[]) => void;
  setRecipes: (recipes: Recipe[]) => void;
  addRecipe: (recipe: Recipe) => void;
  deleteRecipe: (id: string) => void;
  updateRecipe: (id: string, updates: Partial<Recipe>) => void;
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

const StoreContext = createContext<StoreContextType | null>(null);

export const StoreProvider = ({ children }: { children: ReactNode }) => {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [profile, setProfile] = useState<UserProfile>(defaultProfile);
  const [dailyConsumption, setDailyConsumption] = useState({ 
    date: format(new Date(), 'yyyy-MM-dd'),
    macros: { calories: 0, protein: 0, carbs: 0, fat: 0, fiber: 0, sugar: 0 },
    caloriesBurned: 0 
  });
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
          
          setRecipes(data.data.recipes || []);
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
      if (storedRecipes) setRecipes(storedRecipes);

      const storedProfile = await get('app_profile');
      if (storedProfile) {
        const today = format(new Date(), 'yyyy-MM-dd');
        let newStreak = storedProfile.streakDays;
        
        if (storedProfile.lastActiveDate) {
          const lastDate = new Date(storedProfile.lastActiveDate);
          const diffDiff = Math.floor((new Date().getTime() - lastDate.getTime()) / (1000 * 3600 * 24));
          if (diffDiff === 1) {
            newStreak += 1;
          } else if (diffDiff > 1) {
            newStreak = 0;
          }
        } else {
          newStreak = 1;
        }

        const updatedProfile = { ...storedProfile, streakDays: newStreak, lastActiveDate: today };
        setProfile(updatedProfile);
        set('app_profile', updatedProfile);
      }

      const storedDaily = await get('app_daily');
      if (storedDaily && storedDaily.date === format(new Date(), 'yyyy-MM-dd')) {
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

  const updateRecipe = (id: string, updates: Partial<Recipe>) => {
    const newRecipes = recipes.map(r => r.id === id ? { ...r, ...updates } : r);
    setRecipes(newRecipes);
    set('app_recipes', newRecipes);
    triggerSync(profile, newRecipes);
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

  return (
    <StoreContext.Provider value={{ recipes, setAllRecipes, addRecipe, deleteRecipe, updateRecipe, profile, updateProfile, dailyConsumption, updateDailyConsumption, folderPosts, setFolderPosts, isLoading, loadFromCloud, syncToCloud, currentMealPlan, setCurrentMealPlan }}>
      {children}
    </StoreContext.Provider>
  );
};

export const useStore = () => {
  const context = useContext(StoreContext);
  if (!context) throw new Error("useStore must be used within StoreProvider");
  return context;
};
