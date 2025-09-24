# user_interface.py
import re
from typing import Any, Dict
from scraper_recipe import scrape_recipes

MIN_ALPHA = 3

def _count_letters(s: str) -> int:
    return sum(ch.isalpha() for ch in s)

def _count_digits(s: str) -> int:
    return sum(ch.isdigit() for ch in s)

def is_likely_recipe_query(user_input: str) -> bool:
    if not user_input:
        return False
    s = user_input.strip()
    if _count_letters(s) < MIN_ALPHA:
        return False
    if _count_digits(s) > _count_letters(s):
        return False
    if re.search(r"https?://", s, flags=re.I):
        return False
    if len(s) > 60:
        return False
    return True

def handle_user_query(user_input: str, top_k: int = 5) -> Dict[str, Any]:
    q = (user_input or "").strip()
    if not is_likely_recipe_query(q):
        return {
            "ok": False,
            "message": "Please enter a dish name or a main ingredient, such as 'chicken salad'、'beef noodles'、'scrambled eggs'。",
            "examples": ["chicken salad", "beef noodle soup", "egg fried rice", "scrambled eggs"]
        }

    recipes = scrape_recipes(q, top_k=top_k)
    if not recipes:
        return {
            "ok": False,
            "message": f"No recipes were found for “{q}”. Please try more general or shorter keywords (e.g., just the main ingredient).",
            "examples": [q.split()[0] if q.split() else "chicken", "salad", "noodles"]
        }

    def _to_public_dict(r):
        return {
            "id": r.id,
            "title": r.title,
            "url": r.url,
            "servings": r.servings,
            "calories_kcal_per_serving": r.meta.get("calories_kcal_per_serving"),
            "ingredients": [
                {
                    "name": ing.name,
                    "canonical_name": ing.canonical_name,
                    "quantity_g": ing.quantity_g,
                    "optional": ing.optional,
                    "to_taste": ing.to_taste,
                    "approx": ing.approx,
                    "skip_for_kcal": ing.skip_for_kcal,
                    "prep": ing.prep,
                }
                for ing in r.ingredients
            ]
        }

    return {"ok": True, "recipes": [_to_public_dict(r) for r in recipes]}

if __name__ == "__main__":
    while True:
        try:
            user_in = input("Please enter a dish name or a main ingredient（Enter q to exit）： ").strip()
        except EOFError:
            break
        if user_in.lower() in {"q", "quit", "exit"}:
            break

        result = handle_user_query(user_in, top_k=5)
        if not result["ok"]:
            print("⚠️", result["message"])
            if "examples" in result:
                print("examples：", " / ".join(result["examples"]))
            print("-" * 60)
            continue

        for r in result["recipes"]:
            print(f"Title: {r['title']}")
            print(f"Calories: {r['calories_kcal_per_serving']} kcal")
            print(f"Servings: {r['servings']}")
            print(f"Link: {r['url']}")
            print("Ingredients (normalized):")
            for it in r["ingredients"]:
                q = it["quantity_g"]
                q_str = f"{q:.2f} g" if isinstance(q, (int,float)) else "0.00 g"
                opt = " (optional)" if it.get("optional") else ""
                tt  = " (to taste)" if it.get("to_taste") else ""
                approx = " (approx)" if it.get("approx") else ""
                print(f"  - {it['canonical_name']}  [{q_str}]{opt}{tt}{approx}")
            print("=" * 60)

