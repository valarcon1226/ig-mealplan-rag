import { get, set, del } from 'idb-keyval';
import { MealprepCache, MealprepGenerateResponse } from './types';

const CACHE_KEY = 'app_mealprep';

export function buildPlanFingerprint(plan: any): string {
  if (!plan) return '';
  const days = Array.isArray(plan) ? plan : [plan];
  const shape = days.map((d: any) => ({
    day: d.day,
    meals: (d.meals || []).map((m: any) => ({ meal_type: m.meal_type, recipe_id: m.recipe_id })),
  }));
  return JSON.stringify(shape);
}

export async function loadMealprepCache(currentFingerprint: string): Promise<MealprepCache | null> {
  const cached = (await get(CACHE_KEY)) as MealprepCache | undefined;
  if (!cached) return null;
  if (cached.planFingerprint !== currentFingerprint) {
    await del(CACHE_KEY);
    return null;
  }
  return cached;
}

export async function saveMealprepCache(cache: MealprepCache): Promise<void> {
  await set(CACHE_KEY, cache);
}

export async function clearMealprepCache(): Promise<void> {
  await del(CACHE_KEY);
}

export function newMealprepCache(fingerprint: string, response: MealprepGenerateResponse): MealprepCache {
  return { planFingerprint: fingerprint, sessions: response.sessions, completedTaskIds: [] };
}
