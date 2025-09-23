import re
from typing import Any, Dict
from scraper_recipe import scrape_recipes

MIN_ALPHA = 3  # 至少要有3个字母（中文等非拉丁字符也算“字母”见下面逻辑）

def _count_letters(s: str) -> int:
    # 统计“看起来像字母/文字”的字符：包含中文、日文等
    return sum(ch.isalpha() for ch in s)

def _count_digits(s: str) -> int:
    return sum(ch.isdigit() for ch in s)

def is_likely_recipe_query(user_input: str) -> bool:
    if not user_input:
        return False
    s = user_input.strip()
    # 太短、只有空格/标点
    if _count_letters(s) < MIN_ALPHA:
        return False
    # 明显是纯数字或以数字为主
    if _count_digits(s) > _count_letters(s):
        return False
    # 明显是URL
    if re.search(r"https?://", s, flags=re.I):
        return False
    # 过长的一大段句子也判为不合格（MVP 先限制）
    if len(s) > 60:
        return False
    return True

def handle_user_query(user_input: str, top_k: int = 5) -> Dict[str, Any]:
    """
    返回：
      - 成功: {"ok": True, "recipes": [ {...}, ... ]}
      - 失败: {"ok": False, "message": "...", "examples": [...]}
    """
    q = (user_input or "").strip()
    if not is_likely_recipe_query(q):
        return {
            "ok": False,
            "message": "Please enter a dish name or a main ingredient, such as 'chicken salad'、'beef noodles'、'scrambled eggs'。",
            "examples": ["chicken salad", "beef noodle soup", "egg fried rice", "scrambled eggs"]
        }

    recipes = scrape_recipes(q, top_k=top_k)  # 调用我们已有的Allrecipes爬虫
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
                getattr(ing, "meta", {}).get("alias_raw") or getattr(ing, "name", None)
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
            print("Ingredients:")
            for it in r["ingredients"]:
                print("  -", it)
            print("=" * 60)