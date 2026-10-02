import { Recipe, UserProfile } from './types';

// Must match DIET_LABELS in backend/diet.py (the backend tags each recipe with these).
export const DIET_LABELS = ['Vegetariano', 'Vegano', 'Sin Gluten', 'Sin Lácteos', 'Sin Frutos Secos', 'Sin Mariscos', 'Apto Diabético'];

const recipeText = (r: Recipe) =>
  [r.title, ...r.ingredients.map(i => i.name)].join(' ').toLowerCase();

const mentions = (text: string, word: string) =>
  new RegExp(`\\b${word.trim().toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'u').test(text);

// Hard filter: the recipe meets every restriction and has nothing the user avoids.
// A recipe without `diet` (not from the backend) can't be verified, so it doesn't pass.
export function fitsProfile(r: Recipe, p: UserProfile): boolean {
  const restrictions = p.dietaryRestrictions ?? [];
  if (restrictions.length && !restrictions.every(d => r.diet?.includes(d))) return false;
  const text = recipeText(r);
  return !(p.avoidFoods ?? []).some(a => a.trim() && mentions(text, a));
}

// Soft preference: how many of the user's favorite foods the recipe mentions.
export function likeScore(r: Recipe, p: UserProfile): number {
  const text = [recipeText(r), ...r.categories].join(' ').toLowerCase();
  return (p.favoriteFoods ?? []).filter(f => f.trim() && mentions(text, f)).length;
}

export const splitList = (s: string) => s.split(',').map(x => x.trim()).filter(Boolean);
