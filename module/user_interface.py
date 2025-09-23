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

    def _to_public_dict(r) -> Dict[str, Any]:
        return {
            "id": getattr(r, "id", None),
            "title": getattr(r, "title", None),
            "url": getattr(r, "url", None),
            "servings": getattr(r, "servings", None),
            "calories_kcal_per_serving": (getattr(r, "meta", {}) or {}).get("calories_kcal_per_serving"),
            "ingredients": [
                {
                    "name": getattr(ing, "name", None),
                    "quantity_g": getattr(ing, "quantity_g", None)
                }
                for ing in getattr(r, "ingredients", []) or []
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
                q_str = f"{q:.2f} g" if isinstance(q, (int,float)) else "N/A"
                print(f"  - {it['name']}  [{q_str}]")
            print("=" * 60)
