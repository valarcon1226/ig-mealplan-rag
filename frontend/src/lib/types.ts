export type Macros = {
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  fiber: number;
  sugar: number;
};

export type Ingredient = {
  name: string;
  amount: string;
};

export type Recipe = {
  id: string;
  title: string;
  ingredients: Ingredient[];
  instructions: string[];
  servings: number;
  macros: Macros;
  categories: string[];
  createdAt: number;
  imageUrl?: string;
  thumbnail_url?: string;
};

export type UserProfile = {
  dailyGoals: Macros;
  currentWeight?: number;
  goalWeight?: number;
  height?: number;
  age?: number;
  gender?: 'male' | 'female';
  activityLevel?: 'sedentary' | 'light' | 'moderate' | 'active' | 'very_active';
  goal?: 'lose' | 'maintain' | 'gain';
  menstrualCyclePhase?: 'menstrual' | 'follicular' | 'ovulation' | 'luteal' | 'none';
  lastPeriodStart?: string;
  n8nWebhookUrl?: string;
  igSyncWebhookUrl?: string;
  garminConnected?: boolean;
  garminCredentials?: { user: string; pass: string; displayName?: string };
  instagramApiKey?: string;
  igFolders?: { id?: string; collection_id?: string; name?: string; media_count?: number }[];
  streakDays: number;
  lastActiveDate: string; // YYYY-MM-DD
  geminiApiKey?: string;
  isPregnant?: boolean;
  prePregnancyWeight?: number;
  pregnancyDueDate?: string;
  igUsername?: string;
};
