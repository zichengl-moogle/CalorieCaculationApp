"""
===============================================================================
main.py — Primary entry point for Final Project
===============================================================================

Author: Zicheng Liu (zichengl)
Team Name: Smart Bite
Course: Heinz College — Data Focused Python
Institution: Carnegie Mellon University
Semester: Fall 2025

-------------------------------------------------------------------------------
Purpose:
    This file serves as the single executable entry point for the project.
    It satisfies the course rubric by providing ONE main file that can be run
    directly in IDLE / Spyder / VSCode / terminal without modification.

    When executed, the program can:
        (1) Launch the Streamlit interface for user interaction, or
        (2) Run the data pipeline that:
             • Fetches recipes via `scraper_recipe.scrape_recipes`
             • Retrieves Walmart ingredient prices via `scraper_walmart.search_walmart`
             • Obtains calorie data from Nutritionix via `nutrition_info`
             • Computes total & per-serving cost and energy
             • Saves output to `data/results_<query>.json`

-------------------------------------------------------------------------------
Notes:
    • No absolute paths; all directories are relative to the project root.
    • Cached data (Walmart/Nutritionix) enables offline evaluation.
    • No packages are auto-installed; dependencies installed manually via:
          pip install -r requirements.txt
    • All source code and data reside in one folder per rubric.

===============================================================================
"""
from __future__ import annotations
import json
import os
import re
from typing import Dict, List, Tuple
import sys
from pathlib import Path
from module.scraper_recipe import scrape_recipes, Recipe, Ingredient
from module.scraper_walmart import search_walmart  # -> (price, unit{"g","each"})
from module.nutrition_info import kcal_per_gram, kcal_per_each

_price_cache: Dict[str, Tuple[float, str]] = {}
_kcalg_cache: Dict[str, float] = {}
_kcale_cache: Dict[str, float] = {}
_gpe_cache: Dict[str, float] = {}  # grams per each


def _price_for(name: str) -> Tuple[float, str]:
    key = name.strip().lower()
    if key not in _price_cache:
        try:
            _price_cache[key] = search_walmart(key)  # (price, unit)
        except Exception:
            _price_cache[key] = (0.0, "g")
    return _price_cache[key]


def _kcal_per_g(name: str) -> float:
    key = name.strip().lower()
    if key not in _kcalg_cache:
        try:
            val = float(kcal_per_gram(key))
            print(f"[runner] kcal_per_gram({key}) = {val:.4f} kcal/g")
            _kcalg_cache[key] = val
        except Exception as e:
            print(f"[runner][WARN] kcal_per_gram({key}) failed: {e}")
            _kcalg_cache[key] = 0.0
    return _kcalg_cache[key]


def _kcal_per_each(name: str) -> float:
    key = name.strip().lower()
    if key not in _kcale_cache:
        try:
            val = float(kcal_per_each(key))
            print(f"[runner] kcal_per_each({key}) = {val:.1f} kcal/each")
            _kcale_cache[key] = val
        except Exception as e:
            print(f"[runner][WARN] kcal_per_each({key}) failed: {e}")
            _kcale_cache[key] = 0.0
    return _kcale_cache[key]


def _grams_per_each(name: str) -> float:
    key = name.strip().lower()
    if key in _gpe_cache:
        return _gpe_cache[key]
    g = 0.0
    try:
        kpe = _kcal_per_each(key)
        kpg = _kcal_per_g(key)
        if kpe > 0 and kpg > 0:
            g = kpe / kpg
    except Exception:
        g = 0.0
    _gpe_cache[key] = g
    return g


def _cost_for_grams(name: str, grams: float) -> Tuple[float, float, str, str, str]:
    """
    return (cost_usd, unit_price, unit_price_unit, quantity_display, notes)
    """
    price, unit = _price_for(name)
    notes = ""
    if grams <= 0:
        return 0.0, price, unit, "0 g", notes

    if unit == "g":
        return grams * price, price, "g", f"{grams:.2f} g", notes
    elif unit == "each":
        gpe = _grams_per_each(name)
        if gpe > 0:
            price_per_g = price / gpe
            return grams * price_per_g, price_per_g, "g", f"{grams:.2f} g", "price unit mismatch: api=each, needed=g"
        else:
            return 0.0, price, "each", f"{grams:.2f} g", "cannot bridge each->g"
    else:
        return 0.0, price, unit, f"{grams:.2f} g", "unknown price unit"


def _cost_for_each(name: str, count: float) -> Tuple[float, float, str, str, str]:
    """
    return (cost_usd, unit_price, unit_price_unit, quantity_display, notes)
    - if API gives $/g, convert to $/each using grams_per_each.
    """
    price, unit = _price_for(name)
    notes = ""
    if count <= 0:
        return 0.0, price, unit, "0 each", notes

    if unit == "each":
        return count * price, price, "each", f"{count:g} each", notes
    elif unit == "g":
        gpe = _grams_per_each(name)
        if gpe > 0:
            price_per_each = price * gpe
            return count * price_per_each, price_per_each, "each", f"{count:g} each", "price unit mismatch: api=g, needed=each"
        else:
            return 0.0, price, "g", f"{count:g} each", "cannot bridge g->each"
    else:
        return 0.0, price, unit, f"{count:g} each", "unknown price unit"


def compute_recipe_energy_and_cost(recipe: Recipe) -> Dict:
    total_kcal = 0.0
    total_cost = 0.0
    breakdown = []

    for ing in recipe.ingredients:
        name = ing.canonical_name or ing.name
        name = (name or "").strip().lower()

        is_each = ing.meta.get("unit_canonical") == "each" or bool(ing.meta.get("each_count"))
        qty_each = float(ing.meta.get("each_count", "0") or 0)
        qty_g = float(ing.quantity_g or 0.0)

        kcal = 0.0
        kcal_per_100g = 0.0
        unit_price = 0.0
        unit_price_unit = ""
        notes = ""
        quantity_display = ""

        if is_each:
            kpe = _kcal_per_each(name)
            # --- 兜底：kcal/each 失败时，用 kcal/g × grams_per_each ---
            if kpe <= 0:
                kpg_fallback = _kcal_per_g(name)
                gpe_true = _grams_per_each(name)
                if kpg_fallback > 0 and gpe_true > 0:
                    kpe = kpg_fallback * gpe_true
                    print(f"[runner] fallback kcal_per_each({name}) = {kpe:.1f} (kcal/g * g/each)")
            kcal = qty_each * kpe

            cost, unit_price, unit_price_unit, quantity_display, notes = _cost_for_each(name, qty_each)
        else:
            kpg = _kcal_per_g(name)
            kcal = qty_g * kpg
            kcal_per_100g = kpg * 100.0 if kpg > 0 else 0.0
            cost, unit_price, unit_price_unit, quantity_display, notes = _cost_for_grams(name, qty_g)

        total_kcal += kcal
        total_cost += cost

        price_per_g_for_compat = unit_price if unit_price_unit == "g" else 0.0
        quantity_g_for_compat = qty_g if not is_each else 0.0
        print(
            f"[runner] {name} -> unit={'each' if is_each else 'g'}, qty={qty_each if is_each else qty_g}, kcal={kcal:.1f}")
        breakdown.append({
            "name": name,
            "quantity_g": quantity_g_for_compat,
            "kcal_per_100g": float(kcal_per_100g),
            "kcal": float(kcal),
            "price_per_g": float(price_per_g_for_compat),
            "cost_usd": float(cost),
            "quantity_display": quantity_display,
            "unit_price": float(unit_price),
            "unit_price_unit": unit_price_unit,
            "notes": notes,
        })

    per_serv_kcal = total_kcal / max(1, recipe.servings or 1)
    per_serv_cost = total_cost / max(1, recipe.servings or 1)
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
    recipes = scrape_recipes(query, top_k=top_k, _use_cache=use_cache)

    results: List[Dict] = []
    for r in recipes:
        results.append(compute_recipe_energy_and_cost(r))

    os.makedirs("data", exist_ok=True)

    safe_query = re.sub(r'\s+', '_', query.strip())
    out_path = os.path.join("data", f"results_{safe_query}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return out_path


ROOT = Path(__file__).resolve().parent
APP_PATH = ROOT / "streamlit_app.py"  # your Streamlit app entry


def _launch_streamlit():
    """
    Launches 'streamlit run app.py' programmatically without spawning a shell.
    Works in IDLE/Spyder/VSCode where graders just press 'Run'.
    """
    try:
        # Prefer the official CLI module hook so this works cross-platform
        import runpy
        import streamlit  # noqa: F401  # just to check availability

        # Build argv exactly as if the user typed: streamlit run app.py
        sys.argv = [
            "streamlit", "run", str(APP_PATH),
            "--server.headless=true"  # safe default for CI/VM grading
        ]
        # Newer Streamlit uses 'streamlit.web.cli' as the CLI entry
        try:
            runpy.run_module("streamlit.web.cli", run_name="__main__")
        except ModuleNotFoundError:
            # Fallback for older Streamlit versions
            runpy.run_module("streamlit.cli", run_name="__main__")

    except ImportError as e:
        # Streamlit not installed — comply with rubric (no auto-install),
        # and tell the grader how to install manually.
        print(
            "[ERROR] Streamlit is not installed.\n"
            "Please install dependencies manually (per README):\n"
            "  pip install -r requirements.txt\n\n"
            "Then launch either:\n"
            f"  streamlit run {APP_PATH}\n"
            "or just re-run:\n"
            "  python main.py\n"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    if not APP_PATH.exists():
        print(f"[ERROR] Cannot find app file: {APP_PATH}")
        raise SystemExit(1)
    _launch_streamlit()
