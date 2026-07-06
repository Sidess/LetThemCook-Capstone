/**
 * RECIPE SERVICE
 * ==============
 * This frontend service now talks to the FastAPI backend.
 * If the backend is not running, it safely falls back to the local recipe data
 * so the UI still works while developing.
 */

import { RECIPE_DATABASE } from "../data/recipes.js";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

/**
 * Search and rank recipes using the backend first, then local fallback.
 * @param {string[]} pantry
 * @param {"All" | "Breakfast" | "Lunch" | "Dinner"} mealFilter
 * @param {string} nameQuery
 * @returns {Promise<Array>}
 */
export async function searchRecipes(pantry, mealFilter, nameQuery) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/recipes/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pantry, mealFilter, nameQuery }),
    });

    if (!response.ok) {
      throw new Error(`Backend search failed: ${response.status}`);
    }

    const data = await response.json();
    return Array.isArray(data) ? data : data.results || [];
  } catch (error) {
    console.warn("Using local recipe fallback because backend is unavailable:", error);

    const byMeal =
      mealFilter === "All"
        ? RECIPE_DATABASE
        : RECIPE_DATABASE.filter((r) => r.mealType === mealFilter);

    const trimmedQuery = nameQuery.trim().toLowerCase();
    const byName = trimmedQuery
      ? byMeal.filter((r) => r.name.toLowerCase().includes(trimmedQuery))
      : byMeal;

    return _mockSearch(pantry, byName);
  }
}

/**
 * Send a message to Chef Llama through the FastAPI backend.
 * @param {string} userMessage
 * @returns {Promise<string>}
 */
export async function chatWithChef(userMessage) {
  const response = await fetch(`${API_BASE_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_message: userMessage }),
  });

  if (!response.ok) {
    throw new Error(`Backend chat failed: ${response.status}`);
  }

  const data = await response.json();
  return data.chef_reply || data.message || "Chef Llama did not return a reply.";
}

function _mockSearch(pantry, recipes) {
  const normalisedPantry = pantry.map((p) => p.toLowerCase().trim());

  const results = recipes.map((recipe) => {
    const matched = recipe.coreIngredients.filter((keyword) =>
      normalisedPantry.some(
        (pantryItem) =>
          keyword.includes(pantryItem) || pantryItem.includes(keyword)
      )
    );

    const missing = recipe.coreIngredients.filter(
      (keyword) =>
        !normalisedPantry.some(
          (pantryItem) =>
            keyword.includes(pantryItem) || pantryItem.includes(keyword)
        )
    );

    const total = recipe.coreIngredients.length || 1;
    const score = matched.length / total;
    const tier = missing.length === 0 ? 1 : missing.length <= 1 ? 2 : 3;

    const availLines = recipe.allIngredients.filter((line) =>
      matched.some((keyword) => line.toLowerCase().includes(keyword))
    );
    const missingLines = recipe.allIngredients.filter(
      (line) => !availLines.includes(line)
    );

    return {
      ...recipe,
      matched,
      missing,
      score,
      tier,
      availLines,
      missingLines,
    };
  });

  return results.sort(
    (a, b) => b.score - a.score || a.missing.length - b.missing.length
  );
}

export const getAllRecipes = async () => {
  try {
    const response = await fetch('http://127.0.0.1:8000/api/recipes/all');
    if (!response.ok) throw new Error('Backend failed');
    const data = await response.json();
    return data.results || [];
  } catch (error) {
    console.error("Service Error:", error);
    return [];
  }
};