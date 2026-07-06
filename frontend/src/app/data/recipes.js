// =============================================================================
// RECIPE DATABASE - LOADED FROM CSV
// =============================================================================
// This file parses recipe data from recipes.csv and exports it as structured data

import csvData from './recipes.csv?raw';

/**
 * Parse CSV data (RFC 4180 compliant) and convert to recipe objects
 * Handles quoted fields, escaped quotes, and multi-value arrays
 */
function parseCSV(csvText) {
  const lines = csvText.trim().split('\n');
  if (lines.length < 2) return [];

  // Parse header and data rows
  const headerLine = lines[0];
  const headers = parseCSVLine(headerLine);
  
  const recipes = [];
  let i = 1;

  while (i < lines.length) {
    // Read a complete row (might span multiple lines if it contains newlines in quoted fields)
    let rowText = lines[i];
    let quoteCount = (rowText.match(/"/g) || []).length;
    
    // If quote count is odd, this line continues to the next line
    while (quoteCount % 2 !== 0 && i + 1 < lines.length) {
      i++;
      rowText += '\n' + lines[i];
      quoteCount = (rowText.match(/"/g) || []).length;
    }

    const values = parseCSVLine(rowText);
    if (values.length === 0 || !values[0]?.trim()) {
      i++;
      continue;
    }

    // Build recipe object
    const recipe = {};
    headers.forEach((header, idx) => {
      recipe[header] = values[idx] || '';
    });

    // Skip if missing critical fields
    if (!recipe.id || !recipe.name) {
      i++;
      continue;
    }

    // Convert and parse fields
    recipe.id = parseInt(recipe.id);
    recipe.coreIngredients = parseArrayField(recipe.coreIngredients);
    recipe.allIngredients = parseArrayField(recipe.allIngredients);
    recipe.instructions = parseArrayField(recipe.instructions);

    recipes.push(recipe);
    i++;
  }

  return recipes;
}

/**
 * Parse a CSV line following RFC 4180
 * Handles quoted fields containing commas and escaped quotes
 */
function parseCSVLine(line) {
  const values = [];
  let current = '';
  let insideQuotes = false;

  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    const nextChar = line[i + 1];

    if (char === '"') {
      if (insideQuotes && nextChar === '"') {
        // Escaped quote: "" becomes "
        current += '"';
        i++; // Skip next quote
      } else {
        // Toggle quote state
        insideQuotes = !insideQuotes;
      }
    } else if (char === ',' && !insideQuotes) {
      // Field separator
      values.push(current.trim());
      current = '';
    } else {
      current += char;
    }
  }

  // Add final field
  values.push(current.trim());
  return values;
}

/**
 * Parse array fields from CSV format
 * Handles quoted comma-separated values: "item1", "item2", "item3"
 * Or plain format: item1, item2, item3
 */
function parseArrayField(field) {
  if (!field || !field.trim()) return [];

  // Remove outer quotes if present
  let content = field.trim();
  if (content.startsWith('"') && content.endsWith('"')) {
    content = content.slice(1, -1);
  }

  if (!content) return [];

  // Split by comma, handling quoted items
  const items = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < content.length; i++) {
    const char = content[i];
    const nextChar = content[i + 1];

    if (char === '"') {
      if (inQuotes && nextChar === '"') {
        // Escaped quote
        current += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === ',' && !inQuotes) {
      // Item separator
      items.push(current.trim());
      current = '';
    } else {
      current += char;
    }
  }

  if (current.trim()) {
    items.push(current.trim());
  }

  return items.filter(item => item.length > 0);
}

/**
 * Meal category — maps to the filter buttons in the UI
 * @typedef {"Breakfast" | "Lunch" | "Dinner"} MealType
 */

/**
 * Shape of a single recipe
 * @typedef {Object} Recipe
 * @property {number} id - Unique identifier
 * @property {string} name - Recipe name
 * @property {MealType} mealType - Breakfast, Lunch, or Dinner
 * @property {string} prepTime - Time to prepare (e.g. "10 min")
 * @property {string} cookTime - Time to cook (e.g. "20 min")
 * @property {string} totalTime - Total time (e.g. "30 min")
 * @property {string} cookingMethod - How to cook (e.g. "Pan-fry")
 * @property {string[]} coreIngredients - Key ingredients for matching
 * @property {string[]} allIngredients - Complete ingredient list
 * @property {string[]} instructions - Step-by-step cooking instructions
 */

export const RECIPE_DATABASE = parseCSV(csvData);
