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

export function getPregnancyWeeks(dueDate: string | undefined): { week: number, trimester: number } | null {
  if (!dueDate) return null;
  // Embarazo = 40 semanas. Fecha probable de parto = Semana 40.
  const due = new Date(dueDate + 'T00:00:00Z');
  const utcNow = new Date(Date.UTC(new Date().getFullYear(), new Date().getMonth(), new Date().getDate()));
  
  const diffTime = due.getTime() - utcNow.getTime();
  const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
  
  if (diffDays < 0) return { week: 40, trimester: 3 }; // Ya pasó
  
  const daysPregnant = 280 - diffDays;
  if (daysPregnant < 0) return null; // Fecha muy lejana
  
  const week = Math.floor(daysPregnant / 7) + 1;
  let trimester = 1;
  if (week >= 14 && week <= 27) trimester = 2;
  else if (week >= 28) trimester = 3;
  
  return { week, trimester };
}

export function calculateMacros(profile: UserProfile): Macros {
  // If we don't have enough data, return the current dailyGoals as fallback
  if (!profile.currentWeight || !profile.goalWeight || !profile.height || !profile.age || !profile.gender) {
    return profile.dailyGoals;
  }

  // 1. Calculate BMR (Mifflin-St Jeor)
  // **REGLA EMBARAZO**: Usar peso pre-embarazo si existe.
  const baseWeight = (profile.isPregnant && profile.prePregnancyWeight) ? profile.prePregnancyWeight : profile.currentWeight;
  
  let bmr = 10 * baseWeight + 6.25 * profile.height - 5 * profile.age;
  bmr += (profile.gender === 'male' ? 5 : -161);

  // 2. Calculate TDEE
  const multiplier = ACTIVITY_MULTIPLIERS[profile.activityLevel || 'moderate'];
  let tdee = bmr * multiplier;

  // 3. Caloric Adjustment based on goal
  let targetCalories = tdee;
  
  if (profile.isPregnant) {
    const pregnancy = getPregnancyWeeks(profile.pregnancyDueDate);
    if (pregnancy) {
      if (pregnancy.trimester === 2) targetCalories += 340;
      else if (pregnancy.trimester === 3) targetCalories += 450;
    }
  }
  
  if (profile.goal === 'lose') {
    targetCalories -= 500;
  } else if (profile.goal === 'gain') {
    targetCalories += 300;
  }

  // Cycle Syncing Adjustments (only if NOT pregnant)
  let fatMultiplier = 1.0;
  if (profile.gender === 'female' && profile.lastPeriodStart && !profile.isPregnant) {
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
  
  let protein = 0;
  let fat = 0;
  
  if (profile.isPregnant) {
    // **REGLA EMBARAZO**: Proteína mantenimiento base + 25g extra en T2 y T3. Grasas al 30%.
    const maintenanceProtein = 1.5 * baseWeight; // 1.5g por kg de mantenimiento
    const pregnancy = getPregnancyWeeks(profile.pregnancyDueDate);
    const extraProtein = (pregnancy && pregnancy.trimester >= 2) ? 25 : 0;
    protein = maintenanceProtein + extraProtein;
    
    // Grasa = 30% de calorias totales
    fat = (targetCalories * 0.30) / 9;
  } else {
    // Normal protein
    protein = 2.0 * profile.goalWeight;
    fat = fatMultiplier * profile.currentWeight;
  }

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
    fiber: profile.isPregnant ? 30 : 25, // Un poco más estricto con fibra en embarazo
    sugar: Math.round(targetCalories * 0.05 / 4) // target 5% of calories from sugar
  };
}
