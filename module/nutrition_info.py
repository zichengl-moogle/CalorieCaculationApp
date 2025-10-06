"""
Nutritionix client with disk caching and mode control.

Features:
- Disk cache (cross-run) + LRU cache (in-process).
- Modes:
    - "offline": use disk cache only, never hit API.
    - "auto":    use cache when valid; fetch missing/expired and write back.
    - "refresh": force API for provided keys and overwrite cache.
- Friendly alias normalization via knowledgebase.SYNONYMS (optional).
- Drop-in replacements for:
    - kcal_per_gram(name, mode="auto")
    - kcal_per_each(name, mode="auto")
    - grams_per_each(name, mode="auto")
    - batch_kcal_cached(names, prefer_each=None, mode="auto")

Dependencies: requests, python-dotenv (optional), functools.lru_cache
"""

from __future__ import annotations

import os
import re
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple, Literal

import requests

# --- Optional .env loading (safe even if dotenv not installed) ----------
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# --- Constants -----------------------------------------------------------
NUTRITIONIX_URL = "https://trackapi.nutritionix.com/v2/natural/nutrients"

WEIGHT_UNITS = {
    "g", "gram", "grams", "kg", "oz", "lb", "pound", "pounds", "ounce", "ounces"
}
EACH_LIKE_UNITS = {
    "each", "ea", "count", "piece", "slice",
    "small", "medium", "large", "xlarge", "extra large", "extra-large",
}

# Volume-to-gram fallback (very rough; used only when Nutritionix lacks serving_weight_grams)
VOLUME_G = {
    "tsp": 4.5, "teaspoon": 4.5,
    "tbsp": 13.5, "tablespoon": 13.5,
    "cup": 218.0,
    "fl oz": 26.9, "floz": 26.9, "fluid ounce": 26.9,
    "ml": 0.91,  # crude avg density ~0.91 g/ml for oils
}

Mode = Literal["auto", "offline", "refresh"]

# --- SYNONYMS (safe import) ---------------------------------------------
try:
    # If you have module.knowledgebase with a SYNONYMS dict, we use it.
    from module.knowledgebase import SYNONYMS  # type: ignore
except Exception:
    SYNONYMS = {}  # fallback: no alias mapping


# =============== Low-level HTTP helpers =================================
def _headers() -> dict:
    """Build Nutritionix headers from environment variables."""
    app_id = os.getenv("NUTRITIONIX_APP_ID")
    api_key = os.getenv("NUTRITIONIX_API_KEY")
    if not app_id or not api_key:
        raise RuntimeError("Missing NUTRITIONIX_APP_ID / NUTRITIONIX_API_KEY")
    return {"x-app-id": app_id, "x-app-key": api_key, "Content-Type": "application/json"}


def _first_food_from_nutritionix(query: str) -> dict | None:
    """Send a single 'natural language' query and return the first food item, if any."""
    resp = requests.post(
        NUTRITIONIX_URL,
        headers=_headers(),
        json={"query": query},
        timeout=20,
    )
    resp.raise_for_status()
    foods = resp.json().get("foods", [])
    return foods[0] if foods else None


# =============== Normalization helpers ==================================
def _normalize_alias(name: str) -> str:
    """
    Normalize only via alias dictionary; no fuzzy/typo correction.
    - Lowercase + trim
    - Map through SYNONYMS if present
    """
    s = (name or "").strip().lower()
    return SYNONYMS.get(s, s)


def _is_each_like_unit(unit: str) -> bool:
    return (unit or "").strip().lower() in EACH_LIKE_UNITS


def _is_weight_unit(unit: str) -> bool:
    return (unit or "").strip().lower() in WEIGHT_UNITS


# =============== Per-item extraction ====================================
def _kcal_per_gram_from_item(item: dict, original: str) -> float:
    """
    Compute kcal/g from a Nutritionix 'food' item.
    Uses serving_weight_grams if available; otherwise attempts a coarse volume->grams fallback.
    """
    kcal = float(item.get("nf_calories") or 0.0)
    swg = item.get("serving_weight_grams")
    su = (item.get("serving_unit") or "").strip().lower()
    sqty = float(item.get("serving_qty") or 0.0)

    if swg and swg > 0:
        return kcal / float(swg)

    # Last resort: derive grams from volume units (very approximate)
    u_key = su if su in VOLUME_G else su.replace(".", "").replace(" ", "")
    g_per_serv = VOLUME_G.get(u_key)
    if g_per_serv and sqty > 0:
        return kcal / (g_per_serv * sqty)

    raise ValueError(
        f"Cannot convert to grams for {original!r}; missing serving_weight_grams and no usable volume unit."
    )


def _try_per_each_from_item(item: dict) -> tuple[float | None, float | None]:
    """
    If the item represents an 'each-like' portion, return (kcal_per_each, grams_per_each).
    Otherwise, try alt_measures; else return (None, None).
    """
    qty = item.get("serving_qty") or 1
    unit = (item.get("serving_unit") or "").lower()
    wt = item.get("serving_weight_grams")
    kcal = item.get("nf_calories")

    # Direct each-like serving (e.g., "1 large egg")
    if qty and kcal is not None and wt is not None and not _is_weight_unit(unit) and _is_each_like_unit(unit):
        return float(kcal) / float(qty), float(wt) / float(qty)

    # alt_measures path
    alt = item.get("alt_measures") or []
    # Example element: {'measure': 'large', 'qty': 1, 'serving_weight': 50.0}
    for m in alt:
        measure = (m.get("measure") or "").lower()
        q = m.get("qty") or 1
        sw = m.get("serving_weight")
        if q and sw and _is_each_like_unit(measure):
            try:
                per_g = _kcal_per_gram_from_item(item, item.get("food_name") or "item")
                return per_g * float(sw), float(sw)
            except Exception:
                continue

    return None, None


# =============== Disk cache (cross-run) =================================
MODULE_DIR = Path(__file__).resolve().parent
NUTRI_CACHE_FILE = MODULE_DIR / "cache" / ".cache_nutritionix.json"
NUTRI_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

_NUTRI_CACHE_TTL = 14 * 24 * 3600  # 14 days
_NUTRI_CACHE_VERSION = 1

def _now() -> int:
    return int(time.time())


def _nutri_normalize_key(name: str) -> str:
    return _normalize_alias(name)


def _nutri_cache_read() -> dict:
    if NUTRI_CACHE_FILE.exists():
        try:
            return json.loads(NUTRI_CACHE_FILE.read_text("utf-8"))
        except Exception:
            return {}
    return {}


def _nutri_cache_write(data: dict):
    tmp = NUTRI_CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(NUTRI_CACHE_FILE)


def _nutri_cache_get_many(keys: list[str], offline_only: bool=False) -> Dict[str, dict]:
    """
    Return {key: {"per_g": float|None, "per_each": float|None, "g_each": float|None, "ts": int}}
    from disk cache if valid (TTL ok or offline_only).
    """
    raw = _nutri_cache_read()
    data = raw.get("data", raw)  # backward compatibility
    out: Dict[str, dict] = {}
    now = _now()
    for k in keys:
        v = data.get(k)
        if not v:
            continue
        if isinstance(v, dict):
            ts = int(v.get("ts", 0))
            if offline_only or (now - ts) <= _NUTRI_CACHE_TTL:
                out[k] = v
    return out


def _nutri_cache_set_many(pairs: Dict[str, dict]):
    raw = _nutri_cache_read()
    if "data" not in raw or not isinstance(raw.get("data"), dict):
        raw = {"version": _NUTRI_CACHE_VERSION, "data": {}}
    for k, v in pairs.items():
        raw["data"][k] = {
            "per_g": v.get("per_g"),
            "per_each": v.get("per_each"),
            "g_each": v.get("g_each"),
            "ts": _now(),
        }
    _nutri_cache_write(raw)


# =============== Core batch logic (API parsing) =========================
def _score(inp: str, cand: str) -> int:
    """A tiny lexical overlap score to choose best candidate."""
    a = set(inp.split())
    b = set(cand.split())
    return len(a & b) * 2 + int(inp in cand) + int(cand in inp)


def batch_kcal(names: list[str], prefer_each: set[str] | None = None) -> dict[str, dict]:
    """
    Call Nutritionix once with a comma-joined query and extract per_g / per_each for each input.
    Output:
        {name_lower: {"per_g": float|None, "per_each": float|None, "raw": dict|None}}
    Notes:
        - Uses very light heuristic to pick best matching returned food for each input.
        - per_g tries serving_weight_grams; falls back to crude volume->grams mapping.
        - per_each is taken when serving unit is each-like; otherwise from alt_measures if possible.
    """
    prefer_each = set(n.lower() for n in (prefer_each or set()))
    q_items = [n.strip() for n in names if n and n.strip()]
    if not q_items:
        return {}

    payload = {"query": ", ".join(q_items)}
    resp = requests.post(NUTRITIONIX_URL, headers=_headers(), json=payload, timeout=20)
    resp.raise_for_status()
    foods = resp.json().get("foods", [])

    out = {n.lower(): {"per_g": None, "per_each": None, "raw": None} for n in q_items}
    used = set()

    for inp in q_items:
        key = inp.lower()
        best_i, best_s = -1, -1
        for i, it in enumerate(foods):
            if i in used:
                continue
            cand = (it.get("food_name") or "").lower()
            s = _score(key, cand)
            if s > best_s:
                best_s, best_i = s, i
        if best_i == -1:
            continue

        used.add(best_i)
        it = foods[best_i]
        # derive per_g
        per_g: float | None
        per_each: float | None
        try:
            per_g = _kcal_per_gram_from_item(it, inp)
        except Exception:
            # attempt volume fallback inside _kcal_per_gram_from_item already done; give up if failed
            per_g = None

        # derive per_each
        pe, g_each = _try_per_each_from_item(it)
        per_each = pe

        # If caller prefers each but we couldn't find it, consider using "1 X" serving when not grams.
        if key in prefer_each and per_each is None:
            qty = float(it.get("serving_qty") or 0.0)
            unit = (it.get("serving_unit") or "").lower()
            kcal = float(it.get("nf_calories") or 0.0)
            if qty > 0 and kcal > 0 and not _is_weight_unit(unit):
                per_each = kcal / qty

        out[key] = {"per_g": per_g, "per_each": per_each, "raw": it}

    return out


# =============== Cached batch wrapper ===================================
def batch_kcal_cached(
    names: list[str],
    prefer_each: set[str] | None = None,
    mode: Mode = "auto",
) -> dict[str, dict]:
    """
    Unified entry with disk caching.
    Returns {name_lower: {"per_g": float|None, "per_each": float|None, "raw": dict|None, "g_each": float|None}}
    """
    prefer_each = set(n.lower() for n in (prefer_each or set()))
    q_raw = [n for n in names if n and n.strip()]
    if not q_raw:
        return {}

    # Normalized keys for cache
    keys = [_nutri_normalize_key(n) for n in q_raw]

    # Stage 1: disk cache hits
    results: dict[str, dict] = {}
    cache_hits = _nutri_cache_get_many(keys, offline_only=(mode == "offline"))
    for k in keys:
        if k in cache_hits and mode != "refresh":
            v = cache_hits[k]
            results[k] = {"per_g": v.get("per_g"), "per_each": v.get("per_each"), "g_each": v.get("g_each"), "raw": None}

    # Stage 2: decide which need API
    todo = keys if mode == "refresh" else [k for k in keys if k not in results]

    if not todo or mode == "offline":
        # Return results mapped to original inputs
        return {
            n.lower(): results.get(_nutri_normalize_key(n), {"per_g": None, "per_each": None, "raw": None, "g_each": None})
            for n in q_raw
        }

    # Stage 3: call plain batch_kcal() once with original raw names (preserves your matching heuristic)
    api_out = batch_kcal(q_raw, prefer_each=prefer_each)

    # Stage 4: combine + write back
    to_write: Dict[str, dict] = {}
    for n in q_raw:
        k = _nutri_normalize_key(n)
        info = api_out.get(n.lower()) or {}
        per_g = info.get("per_g")
        per_each = info.get("per_each")
        raw = info.get("raw")

        # Try to extract g_each from 'raw' (if available)
        g_each_val = None
        try:
            if raw:
                pe_tmp, ge_tmp = _try_per_each_from_item(raw)
                g_each_val = ge_tmp
        except Exception:
            pass

        results[k] = {"per_g": per_g, "per_each": per_each, "raw": raw, "g_each": g_each_val}
        to_write[k] = {"per_g": per_g, "per_each": per_each, "g_each": g_each_val}

    _nutri_cache_set_many(to_write)

    return {
        n.lower(): results.get(_nutri_normalize_key(n), {"per_g": None, "per_each": None, "raw": None, "g_each": None})
        for n in q_raw
    }


# =============== Public API (with LRU + mode) ===========================
@lru_cache(maxsize=512)
def kcal_per_gram(name: str, mode: Mode = "auto") -> float:
    """
    Return kcal per gram for 'name'.
    Uses disk cache based on 'mode', plus LRU for in-process speed.
    """
    data = batch_kcal_cached([name], mode=mode)
    info = data.get(name.lower()) or {}
    per_g = info.get("per_g")
    if per_g in (None, 0, 0.0):
        raise ValueError(f"no per_g for {name}")
    return float(per_g)


@lru_cache(maxsize=512)
def grams_per_each(name: str, mode: Mode = "auto") -> float:
    """
    Return grams per 'each' (piece) if derivable; otherwise 0.0.
    """
    data = batch_kcal_cached([name], mode=mode)
    info = data.get(name.lower()) or {}
    g_each = info.get("g_each")
    return float(g_each) if (g_each and g_each > 0) else 0.0


@lru_cache(maxsize=512)
def kcal_per_each(name: str, mode: Mode = "auto") -> float:
    """
    Return kcal per 'each' (piece). If direct each-like is not found,
    try per_g * grams_per_each as a fallback.
    """
    data = batch_kcal_cached([name], prefer_each={name.lower()}, mode=mode)
    info = data.get(name.lower()) or {}
    per_each = info.get("per_each")
    if per_each and per_each > 0:
        return float(per_each)

    per_g = info.get("per_g")
    g_each = info.get("g_each")
    if per_g and g_each and per_g > 0 and g_each > 0:
        return float(per_g) * float(g_each)

    raise ValueError(f"no per_each for {name}")


# =============== Diagnostics ============================================
def diagnose_nutri_cache(test_terms=None, mode: Mode = "auto"):
    """One-shot diagnostic to verify disk+LRU cache behavior."""
    print("\n[DIAG NUTRI] ----- Nutritionix Cache Diagnose -----")
    print("[DIAG NUTRI] Cache file:", NUTRI_CACHE_FILE.resolve())
    print("[DIAG NUTRI] Exists:", NUTRI_CACHE_FILE.exists())
    if NUTRI_CACHE_FILE.exists():
        raw = _nutri_cache_read()
        data = raw.get("data", raw)
        print("[DIAG NUTRI] Entries:", len(data))
        print("[DIAG NUTRI] Sample keys:", list(data.keys())[:5])

    terms = test_terms or ["egg", "onion", "olive oil"]

    # Round 1 (may fetch depending on mode)
    for t in terms:
        t0 = time.time()
        try:
            g = kcal_per_gram(t, mode=mode)
            e = None
            try:
                e = kcal_per_each(t, mode=mode)
            except Exception:
                pass
            dt = (time.time() - t0) * 1000
            print(f"[DIAG NUTRI] 1st {t!r}: {dt:.1f} ms -> per_g={g:.4f} kcal/g, per_each={e}")
        except Exception as ex:
            print(f"[DIAG NUTRI][WARN] {t!r} failed:", ex)

    # Round 2 (should be LRU-fast)
    for t in terms:
        t0 = time.time()
        g = kcal_per_gram(t, mode=mode)
        dt = (time.time() - t0) * 1000
        print(f"[DIAG NUTRI] 2nd {t!r}: {dt:.1f} ms -> per_g={g:.4f} kcal/g")


# =============== CLI hook ===============================================
if __name__ == "__main__":
    """
    Run this file directly to prefetch Nutritionix calorie data
    for common ingredients (both kcal/g and kcal/each).
    This helps populate local caches so later lookups are instant.
    """

    from concurrent.futures import ThreadPoolExecutor, as_completed

    common_items = [
        # Proteins
        "egg", "chicken breast", "chicken thigh", "beef", "pork loin",
        "salmon", "shrimp", "tofu",
        # Dairy
        "milk", "butter", "yogurt", "cheddar cheese", "parmesan", "cream cheese",
        "sour cream",
        # Grains
        "rice", "white rice", "brown rice", "bread", "flour", "oats",
        "spaghetti", "quinoa",
        # Vegetables
        "onion", "garlic", "carrot", "tomato", "potato", "bell pepper",
        "broccoli", "spinach", "lettuce", "cucumber", "mushroom",
        # Fruits
        "apple", "banana", "orange", "lemon", "lime", "strawberry",
        # Fats / oils
        "olive oil", "vegetable oil", "canola oil", "butter", "mayonnaise",
        "peanut butter",
        # Liquids / condiments
        "soy sauce", "ketchup", "honey", "vinegar",
        # Canned / packaged
        "canned tomatoes", "black beans", "chickpeas", "chicken broth",
        # Spices
        "salt", "black pepper", "paprika", "cumin", "oregano", "cinnamon",
    ]

    print(f"[INIT] Nutritionix prefetch started, total {len(common_items)} items...")
    success, fail = 0, 0

    # Parallel querying
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {}
        for item in common_items:
            futures[ex.submit(kcal_per_gram, item)] = (item, "per_g")
            futures[ex.submit(kcal_per_each, item)] = (item, "per_each")

        for fut in as_completed(futures):
            item, mode = futures[fut]
            try:
                val = fut.result()
                print(f"[OK] {item:20s} ({mode:7s}) -> {val:.4f}")
                success += 1
            except Exception as e:
                print(f"[FAIL] {item:20s} ({mode:7s}) -> {e}")
                fail += 1

    print(f"[DONE] Prefetch complete ✅ Success: {success} | Fail: {fail}")

