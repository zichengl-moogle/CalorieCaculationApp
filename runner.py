# runner.py
"""
End-to-end pipeline that glues all modules:
1) fetch recipes (≥3 sources with ≥1 real web-scraped, to be implemented by A)
2) fetch Walmart prices ($/g) for relevant ingredients (to be implemented by B)
3) enrich recipes with price_per_g
4) compute calories & cost using nutrition API (C)
5) save results to data/results_<query>.json

Run:
  python runner.py "chicken"
"""
import json
import os
import re
from typing import Dict, List

from module.datasets import Recipe
from module.scraper_recipe import scrape_recipes
from module.scraper_walmart import get_walmart_price_per_g
from module.nutrition import get_canonical_and_kcal_per_100g


def enrich_recipe_prices(recipe: Recipe, price_map: Dict[str, float]) -> Recipe:
    """
    Fill Ingredient.price_per_g using price_map.
    Matching here is simple (lowercase key). In real life, reuse nutrition
    matcher to improve hit rate.
    """
    for ing in recipe.ingredients:
        key = ing.name.lower()
        ing.price_per_g = float(price_map.get(key, 0.0))
    return recipe


def compute_recipe_energy_and_cost(recipe: Recipe) -> Dict:
    """
    RETURN FORMAT:
    {
      "recipe_id": str,
      "title": str,
      "url": str,
      "servings": int,
      "total_kcal": float,
      "per_serving_kcal": float,
      "total_cost_usd": float,
      "per_serving_cost_usd": float,
      "breakdown": [
        {"name": str, "quantity_g": float, "kcal": float, "kcal_per_100g": float,
         "price_per_g": float, "cost_usd": float}
      ]
    }
    """
    total_kcal = 0.0
    total_cost = 0.0
    breakdown = []

    for ing in recipe.ingredients:
        canonical, kcal_per_100g = get_canonical_and_kcal_per_100g(ing.name)
        kcal = (kcal_per_100g / 100.0) * ing.quantity_g
        cost = (ing.price_per_g or 0.0) * ing.quantity_g

        breakdown.append({
            "name": canonical,
            "quantity_g": ing.quantity_g,
            "kcal_per_100g": float(kcal_per_100g),
            "kcal": float(kcal),
            "price_per_g": float(ing.price_per_g or 0.0),
            "cost_usd": float(cost),
        })
        total_kcal += kcal
        total_cost += cost

    per_serv_kcal = total_kcal / max(1, recipe.servings)
    per_serv_cost = total_cost / max(1, recipe.servings)
    return {
        "recipe_id": recipe.id,
        "title": recipe.title,
        "url": recipe.url,
        "servings": recipe.servings,
        "total_kcal": float(total_kcal),
        "per_serving_kcal": float(per_serv_kcal),
        "total_cost_usd": float(total_cost),
        "per_serving_cost_usd": float(per_serv_cost),
        "breakdown": breakdown,
    }


def run_once(query: str, top_k: int = 5, use_cache: bool = True) -> str:
    recipes = scrape_recipes(query, top_k=top_k, use_cache=use_cache)
    price_map = get_walmart_price_per_g(query, use_cache=use_cache)

    results: List[Dict] = []
    for r in recipes:
        r = enrich_recipe_prices(r, price_map)
        results.append(compute_recipe_energy_and_cost(r))

    os.makedirs("data", exist_ok=True)
    out_path = os.path.join("data", f"results_{re.sub(r'\\s+', '_', query.strip())}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return out_path


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "chicken"
    path = run_once(q, top_k=5, use_cache=True)
    print(f"[OK] Results saved to: {path}")