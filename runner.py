# runner.py
"""
End-to-end pipeline:
1) fetch recipes (scraper_recipe.scrape_recipes)
2) fetch Walmart price for each ingredient (prices_walmart.search_walmart)
3) compute calories & cost using nutritionix_client (kcal/g, kcal/each)
4) save to data/results_<query>.json

Run:
  python runner.py "chicken"
"""
from __future__ import annotations
import json
import os
import re
from typing import Dict, List, Tuple

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
        print(f"[runner] {name} -> unit={'each' if is_each else 'g'}, qty={qty_each if is_each else qty_g}, kcal={kcal:.1f}")
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

def diagnose_cache(test_terms=None):
    """
    诊断两层缓存是否工作：
    1) 磁盘缓存文件是否存在、包含多少条
    2) search_walmart 的 LRU 缓存命中情况（cache_info）
    3) 同一查询调用两次的耗时对比（第二次应明显更快）
    4) 指定词是否已落在磁盘缓存中
    """
    import time
    from pathlib import Path
    try:
        # 这些名字按你的模块名改；下面假设文件叫 module.scraper_walmart
        import module.scraper_walmart as W
    except Exception as e:
        print("[DIAG][ERROR] 无法导入 module.scraper_walmart：", e)
        return

    # 1) 磁盘缓存文件存在性 + 条数
    cache_path = getattr(W, "_CACHE_FILE", None)
    print("\n[DIAG] ----- Walmart Cache Diagnose -----")
    if isinstance(cache_path, Path):
        print("[DIAG] 磁盘缓存路径：", cache_path.resolve())
        exists = cache_path.exists()
        print("[DIAG] 磁盘缓存是否存在：", exists)
        if exists:
            try:
                cache_data = W._cache_read() if hasattr(W, "_cache_read") else {}
                # 兼容你可能的两种结构：{k:[price,unit]} 或 {"data": {...}}
                if "data" in cache_data and isinstance(cache_data["data"], dict):
                    nkeys = len(cache_data["data"])
                    some_keys = list(cache_data["data"].keys())[:5]
                else:
                    nkeys = len(cache_data)
                    some_keys = list(cache_data.keys())[:5]
                print(f"[DIAG] 磁盘缓存条数：{nkeys}（示例键：{some_keys}）")
            except Exception as e:
                print("[DIAG][WARN] 读取磁盘缓存失败：", e)
    else:
        print("[DIAG][WARN] 未找到 _CACHE_FILE 变量；可能磁盘缓存未启用或变量名不同。")

    # 2) LRU 缓存命中信息
    search_fn = getattr(W, "search_walmart", None)
    if not callable(search_fn):
        print("[DIAG][ERROR] 未找到 search_walmart() 函数。")
        return
    cache_info_before = getattr(search_fn, "cache_info", lambda: "N/A")()
    print("[DIAG] LRU cache_info（调用前）：", cache_info_before)

    # 3) 调用两次同一术语，看第二次是否更快 + LRU hits 是否增加
    terms = test_terms or ["egg", "chicken breast", "olive oil"]
    print(f"[DIAG] 测试术语：{terms}")

    def time_once(term: str):
        t0 = time.time()
        try:
            price, unit = search_fn(term)  # 你的 _price_for 里也是调它
        except Exception as e:
            price, unit = 0.0, "g"
            print(f"[DIAG][WARN] 调用失败：{term} -> {e}")
        dt = (time.time() - t0) * 1000
        return dt, price, unit

    # 第一次（可能触发联网）
    for term in terms:
        dt1, p1, u1 = time_once(term)
        print(f"[DIAG] 1st {term!r}: {dt1:.1f} ms -> {p1} USD/{u1}")

    cache_info_mid = getattr(search_fn, "cache_info", lambda: "N/A")()
    print("[DIAG] LRU cache_info（第一次调用后）：", cache_info_mid)

    # 第二次（应命中 LRU，显著更快）
    for term in terms:
        dt2, p2, u2 = time_once(term)
        print(f"[DIAG] 2nd {term!r}: {dt2:.1f} ms -> {p2} USD/{u2}")

    cache_info_after = getattr(search_fn, "cache_info", lambda: "N/A")()
    print("[DIAG] LRU cache_info（第二次调用后）：", cache_info_after)

    # 4) 检查这些 term 是否已写入磁盘缓存（如果你的 search_walmart 会落盘）
    try:
        cache_data2 = W._cache_read() if hasattr(W, "_cache_read") else {}
        def in_disk(k):
            if "data" in cache_data2 and isinstance(cache_data2["data"], dict):
                return (k in cache_data2["data"])
            return (k in cache_data2)
        for term in terms:
            k = term.strip().lower()
            print(f"[DIAG] 磁盘缓存包含 {k!r}：", in_disk(k))
    except Exception as e:
        print("[DIAG][WARN] 二次读取磁盘缓存失败：", e)

    print("[DIAG] 结论指引：\n"
          " - 若第二次耗时显著更短且 LRU hits 增加 → 内存缓存（lru_cache）生效\n"
          " - 若磁盘缓存存在且包含术语键 → 磁盘缓存生效\n"
          " - 若两者都不变，通常是：工作目录不一致/键名不匹配/未落盘/函数绕开了带缓存的封装")

# if __name__ == "__main__":
#     import sys
#     q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "chicken"
#     path = run_once(q, top_k=5, use_cache=True)
#     print(f"[OK] Results saved to: {path}")

if __name__ == "__main__":
    from module.nutrition_info import diagnose_nutri_cache
    diagnose_nutri_cache(["egg", "onion", "olive oil"], mode="auto")

