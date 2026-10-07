import { useEffect, useState } from 'react';
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

// Real score: the backend's own formula (same as the planned score) over what was eaten.
// "Ate something else" entries have no macros, so they add no points.
export function useRealScore(entries: EatEntry[], targets: any, profile: UserProfile): number | null {
  const [score, setScore] = useState<number | null>(null);
  const totals = sumMacros(entries);
  const hasMacros = entries.some(e => e.macros);
  const key = JSON.stringify([totals, targets]);
  useEffect(() => {
    if (!targets || !hasMacros) { setScore(null); return; }
    let cancelled = false;
    fetch('/api/intake-score', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        totals: {
          calorias: totals.calories, proteinas: totals.protein, carbohidratos: totals.carbs,
          grasas: totals.fat, fibra: totals.fiber, azucar: totals.sugar,
        },
        targets,
        goal: profile.goal ?? 'maintain',
        is_pregnant: !!profile.isPregnant,
      }),
    })
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (!cancelled) setScore(d ? d.total : null); })
      .catch(() => { if (!cancelled) setScore(null); });
    return () => { cancelled = true; };
  }, [key, hasMacros]);
  return score;
}
