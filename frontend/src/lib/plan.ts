import { differenceInCalendarDays } from 'date-fns';
import { buildPlanFingerprint } from './mealprepStorage';
import { EatEntry, Macros, UserProfile } from './types';
import { sumMacros } from './store';

// Shared by the Planner (checking meals) and the Dashboard (today's summary).

// Short stable id per generated plan, so checks from an old plan don't carry over.
export const planIdOf = (plan: any) => {
  let h = 0;
  for (const c of buildPlanFingerprint(plan)) h = (h * 31 + c.charCodeAt(0)) | 0;
  return (h >>> 0).toString(36);
};

export const planDays = (plan: any): any[] => (!plan ? [] : Array.isArray(plan) ? plan : [plan]);

// Plan day for today: day 1 is the day it was generated; past the end, the last day.
export const todayPlanIndex = (plan: any, planStart: string | null) => {
  const days = planDays(plan).length;
  if (!days || !planStart) return 0;
  const n = differenceInCalendarDays(new Date(), new Date(`${planStart}T00:00`));
  return Math.min(Math.max(n, 0), days - 1);
};

export const mealMacros = (meal: any): Macros => ({
  calories: meal.calorias || 0, protein: meal.proteinas || 0, carbs: meal.carbohidratos || 0,
  fat: meal.grasas || 0, fiber: meal.fibra || 0, sugar: meal.azucar || 0,
});

export const dayEntries = (eatLog: EatEntry[], planId: string, dayIndex: number) =>
  eatLog.filter(e => e.planKey?.startsWith(`${planId}:${dayIndex}:`));

// Real score of what was eaten: same formula as the backend's planned score (rag_planner.intake_score),
// computed here so it shows instantly and without the server. Keep both in sync if the formula changes.
const SCORE_POINTS = { calorias: 45, proteinas: 20, carbohidratos: 15, grasas: 10, fibra: 5, azucar: 5 };
// (start of full score, end of full score, 0 points below, 0 points above) as a fraction of the target
const GOAL_BANDS: Record<string, [number, number, number, number]> = {
  lose: [0.8, 1.0, 0.6, 1.2], gain: [0.9, 1.1, 0.7, 1.3], maintain: [0.95, 1.05, 0.75, 1.25],
};

function band(value: number, target: number | null | undefined, lo: number, hi: number, zeroLo: number, zeroHi: number) {
  if (!target) return 1;
  const r = value / target;
  if (r < lo) return Math.max(0, (r - zeroLo) / (lo - zeroLo));
  if (r > hi) return Math.max(0, (zeroHi - r) / (zeroHi - hi));
  return 1;
}

export function realScore(entries: EatEntry[], targets: any, profile: UserProfile): number | null {
  if (!targets || !entries.some(e => e.macros)) return null; // "ate something else" adds no points
  const t = sumMacros(entries);
  const b = GOAL_BANDS[profile.isPregnant ? 'maintain' : profile.goal ?? 'maintain'] ?? GOAL_BANDS.maintain;
  const fractions = {
    calorias: band(t.calories, targets.calorias, ...b),
    carbohidratos: band(t.carbs, targets.carbohidratos, ...b),
    grasas: band(t.fat, targets.grasas, ...b),
    proteinas: band(t.protein, targets.proteinas, 1.0, 1.3, 0, 2.3),
    fibra: band(t.fiber, targets.fibra, 1.0, Infinity, 0, Infinity),
    azucar: band(t.sugar, targets.azucares, 0, 1.0, -1, 1.5),
  };
  return Math.round(Object.entries(fractions).reduce(
    (sum, [k, f]) => sum + Math.round(SCORE_POINTS[k as keyof typeof SCORE_POINTS] * f * 10) / 10, 0));
}
