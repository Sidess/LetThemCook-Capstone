"""LetThemCook FastAPI backend.

This backend is connected to the React/Vite frontend in ../frontend.
It works immediately with the bundled recipes.json file, and it can also use
Ollama if llama3.2 is running locally.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal
import pandas as pd
import ast  

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
RECIPES_PATH = BASE_DIR / "LetThemCook_Cleaned.csv"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
USE_OLLAMA = os.getenv("USE_OLLAMA", "true").lower() in {"1", "true", "yes", "y"}

app = FastAPI(title="LetThemCook Backend API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RecipeSearchRequest(BaseModel):
    pantry: list[str] = Field(default_factory=list)
    mealFilter: Literal["All", "Breakfast", "Lunch", "Dinner"] = "All"
    nameQuery: str = ""


class ChatRequest(BaseModel):
    user_message: str


class RecipeQuery(BaseModel):
    user_ingredients: str
    max_time_minutes: int = 60


def load_recipes() -> list[dict[str, Any]]:
    if not RECIPES_PATH.exists():
        raise RuntimeError(f"Missing recipe database: {RECIPES_PATH}")
    
    # Read the CSV instead of JSON
    df = pd.read_csv(RECIPES_PATH)
    recipes = []
    
    for _, row in df.iterrows():
        # Helper to safely turn CSV text back into Python lists for the frontend
        def parse_list(val: Any) -> list[str]:
            if pd.isna(val): return []
            val_str = str(val)
            # If the CSV saved the list as a string like "['garlic', 'onion']"
            if val_str.startswith('[') and val_str.endswith(']'):
                try:
                    return ast.literal_eval(val_str)
                except Exception:
                    pass
            # Otherwise, just split it by commas
            return [x.strip() for x in val_str.split(',')]

        # Map the CSV columns to the exact keys Shancel's frontend expects.
        # (Note: Adjust the "row.get" strings if your CSV column names are slightly different, e.g. "Recipe_Name")
        recipes.append({
            "name": str(row.get("name", row.get("Recipe_Name", ""))),
            "mealType": str(row.get("mealType", row.get("Meal_Type", "All"))),
            "totalTime": str(row.get("totalTime", row.get("Total_Time", "60"))),
            "coreIngredients": parse_list(row.get("coreIngredients", row.get("Core_Ingredients", ""))),
            "allIngredients": parse_list(row.get("allIngredients", row.get("All_Ingredients", ""))),
            "instructions": parse_list(row.get("instructions", row.get("Instructions", ""))),
        })
        
    return recipes
    


RECIPES = load_recipes()


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def parse_minutes(value: str) -> int:
    match = re.search(r"(\d+)", str(value))
    return int(match.group(1)) if match else 999


def recipe_matches(recipe: dict[str, Any], pantry: list[str]) -> dict[str, Any]:
    normalised_pantry = [normalize(item) for item in pantry if item.strip()]
    core = [normalize(item) for item in recipe.get("coreIngredients", [])]

    def has_match(keyword: str) -> bool:
        return any(keyword in item or item in keyword for item in normalised_pantry)

    matched = [original for original in recipe.get("coreIngredients", []) if has_match(normalize(original))]
    missing = [original for original in recipe.get("coreIngredients", []) if not has_match(normalize(original))]

    total = len(core) or 1
    score = len(matched) / total
    tier = 1 if not missing else 2 if len(missing) <= 1 else 3

    all_ingredients = recipe.get("allIngredients", [])
    avail_lines = [
        line
        for line in all_ingredients
        if any(normalize(keyword) in normalize(line) for keyword in matched)
    ]
    missing_lines = [line for line in all_ingredients if line not in avail_lines]

    return {
        **recipe,
        "matched": matched,
        "missing": missing,
        "score": score,
        "tier": tier,
        "availLines": avail_lines,
        "missingLines": missing_lines,
    }


def search_recipe_database(
    pantry: list[str],
    meal_filter: str = "All",
    name_query: str = "",
    max_time_minutes: int | None = None,
) -> list[dict[str, Any]]:
    recipes = RECIPES

    if meal_filter != "All":
        recipes = [recipe for recipe in recipes if recipe.get("mealType") == meal_filter]

    trimmed_query = normalize(name_query)
    if trimmed_query:
        recipes = [recipe for recipe in recipes if trimmed_query in normalize(recipe.get("name", ""))]

    if max_time_minutes is not None:
        recipes = [
            recipe
            for recipe in recipes
            if parse_minutes(recipe.get("totalTime", recipe.get("time_minutes", "999"))) <= max_time_minutes
        ]

    ranked = [recipe_matches(recipe, pantry) for recipe in recipes]
    ranked.sort(key=lambda item: (-item["score"], len(item["missing"]), item.get("name", "")))
    return ranked


def extract_pantry_from_message(message: str) -> list[str]:
    """Simple ingredient parser for chat messages.

    It keeps the backend useful even when Ollama/ChromaDB is not available.
    """
    message = message.lower()
    for prefix in ["with", "using", "i have", "ingredients are", "ingredients:"]:
        if prefix in message:
            message = message.split(prefix, 1)[1]
            break

    pieces = re.split(r",| and |\+|/|\n", message)
    cleaned = []
    ignored = {"what can i make", "can i make", "make", "cook", "recipe", "recipes", "food"}
    for piece in pieces:
        item = normalize(piece)
        item = re.sub(r"\b(what|can|i|make|cook|with|using|have|please|recipe|recipes|food)\b", "", item)
        item = re.sub(r"\s+", " ", item).strip()
        if item and item not in ignored:
            cleaned.append(item)
    return cleaned


def call_ollama(user_message: str, recipes: list[dict[str, Any]]) -> str | None:
    if not USE_OLLAMA:
        return None

    context = []
    for recipe in recipes[:3]:
        context.append(
            {
                "name": recipe.get("name"),
                "mealType": recipe.get("mealType"),
                "totalTime": recipe.get("totalTime"),
                "coreIngredients": recipe.get("coreIngredients"),
                "missing": recipe.get("missing"),
                "instructions": recipe.get("instructions", [])[:3],
            }
        )

    prompt = f"""
You are Chef Llama, the friendly Filipino cooking assistant for LetThemCook.
Answer naturally and briefly. Ground your answer only in these recipe records.

Database in use: LetThemCook_Core_Database.csv

User message: {user_message}

Recipe records:
{json.dumps(context, ensure_ascii=False, indent=2)}

Rules:
- Recommend the best matching recipe if it makes sense.
- Mention missing ingredients clearly.
- Do not invent recipes outside the records.
- Use plain text, not JSON.
- When asked what kind of database do you use, you answer truthfully on what database or csv you are using.
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response")
    except Exception:
        return None


def fallback_chat_reply(user_message: str, recipes: list[dict[str, Any]]) -> str:
    if not recipes:
        return (
            "I could not find a matching recipe yet. Try adding simple ingredients like "
            "eggs, rice, chicken, garlic, onion, or butter. 🍳"
        )

    best = recipes[0]
    missing = best.get("missing", [])
    instructions = best.get("instructions", [])[:3]

    if best.get("score", 0) == 0:
        return (
            "I found recipes in the database, but none clearly match those ingredients yet. "
            "Try listing your ingredients with commas, like: eggs, butter, rice. 😊"
        )

    if missing:
        missing_text = ", ".join(missing[:4])
        return (
            f"A good match is **{best['name']}**. You already match "
            f"{len(best.get('matched', []))}/{len(best.get('coreIngredients', []))} key ingredients. "
            f"You may still need: {missing_text}. 🍳\n\n"
            f"First steps:\n- " + "\n- ".join(instructions)
        )

    return (
        f"You can make **{best['name']}** with what you have! ✅ "
        f"It takes about {best.get('totalTime', 'a short time')}.\n\n"
        f"Steps:\n- " + "\n- ".join(instructions)
    )


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "LetThemCook backend is running"}


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "recipes_loaded": len(RECIPES), "ollama_enabled": USE_OLLAMA}


@app.post("/api/recipes/search")
def search_recipes(request: RecipeSearchRequest) -> dict[str, Any]:
    results = search_recipe_database(request.pantry, request.mealFilter, request.nameQuery)
    return {"results": results}


@app.post("/api/chat")
def chat_with_chef_llama(request: ChatRequest) -> dict[str, str]:
    pantry = extract_pantry_from_message(request.user_message)
    recipes = search_recipe_database(pantry) if pantry else search_recipe_database([], name_query="")[:5]

    ollama_reply = call_ollama(request.user_message, recipes)
    if ollama_reply:
        return {"chef_reply": ollama_reply}

    return {"chef_reply": fallback_chat_reply(request.user_message, recipes)}


@app.post("/api/generate-recipe")
def generate_rag_recipe(query: RecipeQuery) -> dict[str, Any]:
    pantry = [item.strip() for item in re.split(r",| and |\+|/|\n", query.user_ingredients) if item.strip()]
    results = search_recipe_database(pantry, max_time_minutes=query.max_time_minutes)
    reply = call_ollama(query.user_ingredients, results) or fallback_chat_reply(query.user_ingredients, results)

    return {
        "status": "success",
        "backend_process": "LocalRecipeSearch_Complete",
        "chef_reply": reply,
        "results": results[:3],
    }

@app.get("/api/recipes/all")
def get_all_recipes():
    """Returns all recipes for the dashboard."""
    return {"results": RECIPES}