# scraper_recipe.py
"""
This part implements real scraping/collection here.
REQUIREMENTS:
- Input: dish name (e.g., "Chicken").
- Return: multiple recipes (list[Recipe]).
- Use Requests+BS4/Selenium.
- Normalize ingredient names to lowercase English; convert quantities to GRAMS.
"""
from typing import List
from module.datasets import Recipe, Ingredient

# ---- DEMO implementation (replace with real logic later) ----
# This returns static examples so the app runs today.

def scrape_recipes(query: str, top_k: int = 5, use_cache: bool = True) -> List[Recipe]:
    """
    INPUT:
      - query: str (e.g., "Chicken")
      - top_k: cap number of recipes to return
      - use_cache: allow using cached results (optional in real impl)

    OUTPUT (exact type): List[Recipe]
    Example element:
      Recipe(
        id="demo:chicken-salad-1",
        title="Chicken Salad (Demo)",
        url="https://example.com/chicken-salad",
        servings=2,
        ingredients=[Ingredient(name="chicken breast", quantity_g=200.0), ...]
      )
    """
    demo = [
        Recipe(
            id="demo:chicken-salad-1",
            title="Chicken Salad (Demo)",
            url="https://example.com/chicken-salad",
            servings=2,
            ingredients=[
                Ingredient(name="chicken breast", quantity_g=200.0, meta={"alias_raw": "Chicken breast"}),
                Ingredient(name="green pepper", quantity_g=80.0, meta={"alias_raw": "Green bell pepper"}),
                Ingredient(name="olive oil", quantity_g=15.0),
            ],
        ),
        Recipe(
            id="demo:spicy-green-chili-1",
            title="Spicy Green Chili (Demo)",
            url="https://example.com/green-chili",
            servings=3,
            ingredients=[
                Ingredient(name="green chili pepper", quantity_g=150.0, meta={"alias_raw": "樟树港辣椒"}),
                Ingredient(name="garlic", quantity_g=15.0),
                Ingredient(name="chicken breast", quantity_g=180.0),
            ],
        ),
    ]
    return demo[: max(1, min(top_k, len(demo)))]

if __name__ == "__main__":
    # Self-test for scraper_recipe.py
    import json
    from pprint import pprint

    query = "chicken"
    recipes = scrape_recipes(query, top_k=3, use_cache=True)

    # Print brief summary
    print(f"[SCRAPER OK] got {len(recipes)} recipe(s) for query='{query}'")
    for r in recipes:
        print(f"- {r.title} | servings={r.servings} | url={r.url} | ingredients={len(r.ingredients)}")

    # Optional: dump to a preview JSON for debugging
    preview = [r.to_dict() for r in recipes]
    print(json.dumps(preview, ensure_ascii=False, indent=2))