import os
import requests
from functools import lru_cache
from dotenv import load_dotenv

from module.knowledgebase import SYNONYMS  # <-- import the alias mapping

load_dotenv()

NUTRITIONIX_URL = "https://trackapi.nutritionix.com/v2/natural/nutrients"

WEIGHT_UNITS = {"g", "gram", "grams", "kg", "oz", "lb", "pound", "pounds", "ounce", "ounces"}
EACH_LIKE_UNITS = {
    "each", "ea", "count", "piece", "slice",
    "small", "medium", "large", "xlarge", "extra large", "extra-large",
}

def _headers():
    app_id = os.getenv("NUTRITIONIX_APP_ID")
    api_key = os.getenv("NUTRITIONIX_API_KEY")
    if not app_id or not api_key:
        raise RuntimeError("Missing NUTRITIONIX_APP_ID / NUTRITIONIX_API_KEY")
    return {"x-app-id": app_id, "x-app-key": api_key, "Content-Type": "application/json"}

@lru_cache(maxsize=512)
def kcal_per_gram(name: str) -> float:
    data = batch_kcal([name])
    info = data.get(name.lower())
    if not info or not info.get("per_g"):
        raise ValueError(f"no per_g for {name}")
    return info["per_g"]

@lru_cache(maxsize=512)
def kcal_per_each(name: str) -> float:
    data = batch_kcal([name], prefer_each={name.lower()})
    info = data.get(name.lower())
    if not info or not info.get("per_each"):
        raise ValueError(f"no per_each for {name}")
    return info["per_each"]

# nutritionix_client.py —— only replace batch_kcal
def batch_kcal(names: list[str], prefer_each: set[str] | None = None) -> dict[str, dict]:
    prefer_each = set(n.lower() for n in (prefer_each or set()))
    q_items = [n.strip() for n in names if n and n.strip()]
    if not q_items:
        return {}
    payload = {"query": ", ".join(q_items)}
    resp = requests.post(NUTRITIONIX_URL, headers=_headers(), json=payload, timeout=20)
    resp.raise_for_status()
    foods = resp.json().get("foods", [])

    # Volume → grams (nutrition fallback): especially for oils/liquids
    VOLUME_G = {
        "tsp": 4.5, "teaspoon": 4.5,
        "tbsp": 13.5, "tablespoon": 13.5,
        "cup": 218.0,
        "fl oz": 26.9, "floz": 26.9, "fluid ounce": 26.9,
        "ml": 0.91,  # 1 ml*0.91 g/ml
    }

    def _per_g_from_item(it: dict) -> tuple[float|None, float|None]:
        kcal = float(it.get("nf_calories") or 0.0)
        swg  = float(it.get("serving_weight_grams") or 0.0)
        su   = (it.get("serving_unit") or "").strip().lower()
        sqty = float(it.get("serving_qty") or 0.0)
        per_g, per_each = (None, None)
        if swg > 0:
            per_g = kcal / swg
        else:
            # Volume-unit fallback
            u = su.replace(".", "").replace(" ", "")
            key = su if su in VOLUME_G else u
            g_per_serv = VOLUME_G.get(key)
            if g_per_serv and sqty > 0:
                per_g = kcal / (g_per_serv * sqty)
        # each determination
        if su in {"each","count","piece","egg","pepper","clove","slice"} and abs(sqty - 1.0) < 1e-6:
            per_each = kcal
        return per_g, per_each

    # Pick the most similar entry for each input
    def _score(inp: str, cand: str) -> int:
        a = set(inp.split())
        b = set(cand.split())
        return len(a & b) * 2 + int(inp in cand) + int(cand in inp)

    out = {n.lower(): {"per_g": None, "per_each": None, "raw": None} for n in q_items}
    used = set()
    for inp in q_items:
        key = inp.lower()
        # Find the food with the highest score
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
        per_g, per_each = _per_g_from_item(it)
        # Enhance each when prefer_each
        if key in prefer_each and per_each is None:
            sqty = float(it.get("serving_qty") or 0.0)
            kcal = float(it.get("nf_calories") or 0.0)
            su   = (it.get("serving_unit") or "").strip().lower()
            if abs(sqty - 1.0) < 1e-6 and kcal > 0 and su not in {"g","gram","grams"}:
                per_each = kcal
        out[key] = {"per_g": per_g, "per_each": per_each, "raw": it}
    return out



def _get_headers() -> dict:
    app_id = os.getenv("NUTRITIONIX_APP_ID")
    api_key = os.getenv("NUTRITIONIX_API_KEY")
    if not app_id or not api_key:
        raise RuntimeError("Missing NUTRITIONIX_APP_ID or NUTRITIONIX_API_KEY in environment")
    return {
        "x-app-id": app_id,
        "x-app-key": api_key,
        "Content-Type": "application/json",
    }


def _normalize_alias(name: str) -> str:
    """
    Only alias normalization (no typo correction, no fuzzy).
    - Lowercases input
    - Maps through SYNONYMS if present
    """
    s = (name or "").strip().lower()
    if not s:
        return s
    return SYNONYMS.get(s, s)


def _first_food_from_nutritionix(query: str) -> dict | None:
    headers = _get_headers()
    payload = {"query": query}
    resp = requests.post(NUTRITIONIX_URL, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    foods = resp.json().get("foods", [])
    return foods[0] if foods else None


def _kcal_per_gram_from_item(item: dict, original: str) -> float:
    kcal = float(item.get("nf_calories") or 0.0)
    weight_g = item.get("serving_weight_grams")
    if not weight_g or weight_g <= 0:
        unit = (item.get("serving_unit") or "").lower()
        qty = item.get("serving_qty")
        if unit in ("g", "gram", "grams") and qty:
            weight_g = float(qty)
        else:
            raise ValueError(
                f"Cannot convert to grams: {original!r}, Nutritionix returned: {item.get('food_name')}"
            )
    return kcal / float(weight_g)


@lru_cache(maxsize=256)
def kcal_per_gram(ingredient: str) -> float:
    """
    Default: LRU cache enabled (maxsize=256).
    Resolution strategy:
      1) Normalize by alias (knowledgebase.SYNONYMS)
      2) Query Nutritionix with the normalized term
      3) If not found, query once with the raw input (some official names might not need alias)
    """
    print("Starting kcal_per_gram lookup for:", ingredient)
    if not ingredient or not ingredient.strip():
        raise ValueError("ingredient cannot be empty")

    normalized = _normalize_alias(ingredient)

    # Try normalized first
    item = _first_food_from_nutritionix(normalized)
    if not item:
        # Fallback once with raw (lowercased) input
        item = _first_food_from_nutritionix(ingredient.strip().lower())
        if not item:
            raise ValueError(
                f"Nutritionix could not find ingredient: {ingredient!r} (normalized={normalized!r})"
            )

    return _kcal_per_gram_from_item(item, ingredient)


# ---------- NEW: each support ----------
def _is_each_like_unit(unit: str) -> bool:
    u = (unit or "").strip().lower()
    return u in EACH_LIKE_UNITS


def _is_weight_unit(unit: str) -> bool:
    return (unit or "").strip().lower() in WEIGHT_UNITS


def _try_per_each_from_item(item: dict) -> tuple[float | None, float | None]:
    """
    Given a Nutritionix food item, if its serving unit is each-like,
    return (kcal_per_each, grams_per_each). Otherwise (None, None).
    """
    qty = item.get("serving_qty") or 1
    unit = (item.get("serving_unit") or "").lower()
    wt = item.get("serving_weight_grams")
    kcal = item.get("nf_calories")

    if qty and kcal is not None and wt is not None and not _is_weight_unit(unit) and _is_each_like_unit(unit):
        # Example: '1 large egg' -> qty=1, unit='large', wt≈50g, kcal≈72
        per_each_kcal = float(kcal) / float(qty)
        per_each_g = float(wt) / float(qty) if wt else None
        return per_each_kcal, per_each_g

    # alt_measures may also provide each-like
    alt = item.get("alt_measures") or []
    # alt_measures element typically contains: {'measure': 'large', 'qty': 1, 'serving_weight': 50.0}
    for m in alt:
        measure = (m.get("measure") or "").lower()
        q = m.get("qty") or 1
        sw = m.get("serving_weight")
        if q and sw and _is_each_like_unit(measure):
            # Use base per-gram calories to derive per-each calories
            try:
                per_g = _kcal_per_gram_from_item(item, item.get("food_name") or "item")
                return per_g * float(sw), float(sw)
            except Exception:
                continue

    return None, None


@lru_cache(maxsize=256)
def grams_per_each(ingredient: str) -> float:
    """
    Return the gram weight of “1 unit of this ingredient” (if determinable), otherwise 0.0.
    Strategy:
      1) Directly ask "1 {normalized}"; if the unit is each-like, return serving_weight_grams/qty
      2) Then try "1 each {normalized}"
      3) If alt_measures has each-like, use alt's serving_weight
      4) Finally return 0.0
    """
    if not ingredient or not ingredient.strip():
        return 0.0
    normalized = _normalize_alias(ingredient)

    for q in (f"1 {normalized}", f"1 each {normalized}"):
        item = _first_food_from_nutritionix(q)
        if item:
            kcal_each, g_each = _try_per_each_from_item(item)
            if g_each and g_each > 0:
                return float(g_each)

    # Try query without "1" then look for alt_measures
    item2 = _first_food_from_nutritionix(normalized)
    if item2:
        _, g_each = _try_per_each_from_item(item2)
        if g_each and g_each > 0:
            return float(g_each)

    return 0.0


@lru_cache(maxsize=256)
def kcal_per_each(ingredient: str) -> float:
    """
    Return the calories “per unit (piece)” (kcal/each).
    Priority: use Nutritionix result with each-like unit; if needed, derive by kcal/g * grams_per_each.
    """
    if not ingredient or not ingredient.strip():
        raise ValueError("ingredient cannot be empty")
    normalized = _normalize_alias(ingredient)

    # First try to obtain each-like portion directly
    for q in (f"1 {normalized}", f"1 each {normalized}", normalized):
        item = _first_food_from_nutritionix(q)
        if item:
            qty = item.get("serving_qty") or 1
            unit = (item.get("serving_unit") or "").lower()
            kcal = item.get("nf_calories")
            wt = item.get("serving_weight_grams")
            if qty and kcal is not None and wt is not None and not _is_weight_unit(unit) and _is_each_like_unit(unit):
                return float(kcal) / float(qty)

            # Try alt_measures (use per-gram calories * each gram weight)
            kcal_each, g_each = _try_per_each_from_item(item)
            if kcal_each is not None:
                return float(kcal_each)

    # Fallback: use per-gram calories * grams_per_each to estimate
    g_each2 = grams_per_each(normalized)
    if g_each2 > 0:
        return kcal_per_gram(normalized) * g_each2

    raise ValueError(f"Cannot determine kcal per each for: {ingredient!r}")
