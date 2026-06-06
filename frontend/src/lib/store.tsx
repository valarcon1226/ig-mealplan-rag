import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { get, set } from 'idb-keyval';
import { Recipe, UserProfile } from './types';
import { format } from 'date-fns';

type StoreContextType = {
  recipes: Recipe[];
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
  const [isLoading, setIsLoading] = useState(true);

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
      setIsLoading(false);
    };
    loadData();
  }, []);

  const addRecipe = (recipe: Recipe) => {
    const newRecipes = [...recipes, recipe];
    setRecipes(newRecipes);
    set('app_recipes', newRecipes);
  };

  const deleteRecipe = (id: string) => {
    const newRecipes = recipes.filter(r => r.id !== id);
    setRecipes(newRecipes);
    set('app_recipes', newRecipes);
  };

  const updateRecipe = (id: string, updates: Partial<Recipe>) => {
    const newRecipes = recipes.map(r => r.id === id ? { ...r, ...updates } : r);
    setRecipes(newRecipes);
    set('app_recipes', newRecipes);
  };

  const updateProfile = (updates: Partial<UserProfile>) => {
    const newProfile = { ...profile, ...updates };
    setProfile(newProfile);
    set('app_profile', newProfile);
  };

  const updateDailyConsumption = (updates: Partial<StoreContextType['dailyConsumption']>) => {
    const newDaily = { ...dailyConsumption, ...updates };
    setDailyConsumption(newDaily);
    set('app_daily', newDaily);
  };

  return (
    <StoreContext.Provider value={{ recipes, addRecipe, deleteRecipe, updateRecipe, profile, updateProfile, dailyConsumption, updateDailyConsumption, folderPosts, setFolderPosts, isLoading }}>
      {children}
    </StoreContext.Provider>
  );
};

export const useStore = () => {
  const context = useContext(StoreContext);
  if (!context) throw new Error("useStore must be used within StoreProvider");
  return context;
};
