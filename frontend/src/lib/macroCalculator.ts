import { UserProfile, Macros } from './types';

const ACTIVITY_MULTIPLIERS = {
  sedentary: 1.2,
  light: 1.375,
  moderate: 1.55,
  active: 1.725,
  very_active: 1.9
};

export function getCyclePhase(lastPeriodStart: string | undefined): { phase: string, day: number, isLate: boolean } | null {
  if (!lastPeriodStart) return null;
  // Parse as UTC to avoid timezone offsets causing +/- 1 day errors
  const start = new Date(lastPeriodStart + 'T00:00:00Z');
  const now = new Date();
  const utcNow = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  
  const diffTime = utcNow.getTime() - start.getTime();
  const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
  
  if (diffDays < 0) return null;
  
  // Do NOT use modulo 28. If it goes past 28, it's a delay (retraso), she stays in Luteal phase.
  const currentDay = diffDays + 1;
  
  let phase = '';
  if (currentDay >= 1 && currentDay <= 5) phase = 'Menstrual';
  else if (currentDay >= 6 && currentDay <= 14) phase = 'Folicular';
  else if (currentDay >= 15 && currentDay <= 17) phase = 'Ovulación';
  else phase = 'Lútea'; // 18 onwards

  return { phase, day: currentDay, isLate: currentDay > 28 };
}

export function calculateMacros(profile: UserProfile): Macros {
  // If we don't have enough data, return the current dailyGoals as fallback
  if (!profile.currentWeight || !profile.goalWeight || !profile.height || !profile.age || !profile.gender) {
    return profile.dailyGoals;
  }

  // 1. Calculate BMR (Mifflin-St Jeor)
  let bmr = 10 * profile.currentWeight + 6.25 * profile.height - 5 * profile.age;
  bmr += (profile.gender === 'male' ? 5 : -161);

  // 2. Calculate TDEE
  const multiplier = ACTIVITY_MULTIPLIERS[profile.activityLevel || 'moderate'];
  let tdee = bmr * multiplier;

  // 3. Caloric Adjustment based on goal
  let targetCalories = tdee;
  if (profile.goal === 'lose') {
    targetCalories -= 500;
  } else if (profile.goal === 'gain') {
    targetCalories += 300;
  }

  // Cycle Syncing Adjustments
  let fatMultiplier = 1.0;
  if (profile.gender === 'female' && profile.lastPeriodStart) {
    const cycle = getCyclePhase(profile.lastPeriodStart);
    if (cycle) {
      if (cycle.phase === 'Folicular') {
        fatMultiplier = 0.8;
      } else if (cycle.phase === 'Lútea') {
        targetCalories += 150;
        fatMultiplier = 1.2;
      }
    }
  }

  // 4. Calculate Macros
  // Protein: 2.0g per kg of target weight
  const protein = 2.0 * profile.goalWeight;
  
  // Fat: Adjusted by cycle phase for hormonal health
  const fat = fatMultiplier * profile.currentWeight;

  // Carbs: Remaining calories
  const proteinCals = protein * 4;
  const fatCals = fat * 9;
  let carbCals = targetCalories - proteinCals - fatCals;
  
  // Safety check, don't let carbs go negative if the deficit is too large
  if (carbCals < 0) carbCals = 0;
  const carbs = carbCals / 4;

  return {
    calories: Math.round(targetCalories),
    protein: Math.round(protein),
    fat: Math.round(fat),
    carbs: Math.round(carbs),
    fiber: 30, // average ideal fiber
    sugar: Math.round(targetCalories * 0.05 / 4) // target 5% of calories from sugar
  };
}
