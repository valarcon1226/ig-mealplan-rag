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
  video_url?: string;
  media_id?: string; // id del post de IG; `id` es el id interno de SQLite
  diet?: string[]; // dietas que cumple (backend diet.py), ej. "Vegano", "Apto Diabético"
  cuisine?: string | null; // italiana, asiatica, mexicana, mediterranea...
  category?: string | null; // categoría de contenido del backend (ensaladas, postres...): elige la imagen por defecto
  favorite?: boolean;
  rating?: number;      // 1-5 estrellas
  timesEaten?: number;  // veces registradas con "Add 1 Serving"
  lastEatenAt?: number;
};

// One eaten serving. planKey ties it to a meal of a plan ("<planId>:<day>:<mealIndex>").
// No macros = "ate something else" (not in the Cookbook): counts as eaten, adds no points.
export type EatEntry = {
  id: string;
  date: string; // YYYY-MM-DD
  at: number;
  title: string;
  recipeId?: string;
  planKey?: string;
  macros?: Macros;
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
  dietaryRestrictions?: string[]; // DIET_LABELS: filtro duro en Cookbook y planner
  avoidFoods?: string[];          // no me gusta / alergias: filtro duro
  favoriteFoods?: string[];       // le gusta: se priorizan
};

export type MealprepTaskResult = {
  id: string;
  text: string;
  estimated_minutes: number;
  recipe_ids: number[];
};

export type MealprepPhaseResult = {
  phase_name: string;
  tasks: MealprepTaskResult[];
};

export type MealprepSessionResult = {
  session_id: number;
  estimated_total_minutes: number;
  warning: string | null;
  phases: MealprepPhaseResult[];
};

export type MealprepGenerateResponse = {
  sessions: MealprepSessionResult[];
};

export type MealprepCache = {
  planFingerprint: string;
  sessions: MealprepSessionResult[];
  completedTaskIds: string[];
};
