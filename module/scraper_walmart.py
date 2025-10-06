# prices_walmart.py
"""
Fetch Walmart ingredient price using SerpAPI.
- Input: ingredient string
- Output: tuple (price, unit):
    - if priced by weight: (USD per gram, "g")
    - if priced by each: (USD per each, "each")
    - else: (0.0, "g")
"""

import re
import json, hashlib, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from functools import lru_cache   # <<< NEW

# API_KEY = "043b5ae44adbd3774c83f2d925e62080ab6eadceb3fa72cf626fb937b1b40f51"
API_KEY ="1088c206cc37fa9748c2f252f37f21b38cef9ab74aa81e1f2919cd1be9dee55b"
SEARCH_URL = "https://serpapi.com/search.json"


def serpapi_walmart_search(query_str, num=1, timeout=15):
    params = {"engine": "walmart", "query": query_str, "api_key": API_KEY, "num": num}
    r = requests.get(SEARCH_URL, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _to_float(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace("$", "")
    try:
        return float(s)
    except:
        return None


def extract_first_item(resp):
    items = resp.get("products") or resp.get("organic_results") or []
    if not items:
        return None
    it = items[0]

    price = None
    if isinstance(it.get("primary_offer"), dict):
        price = it["primary_offer"].get("offer_price")
    price = price if price is not None else it.get("price") or it.get("offer_price")

    return {
        "title": it.get("title") or "",
        "price": _to_float(price),
        "ppu_raw": it.get("price_per_unit"),
        "size_str": it.get("secondary_offer_text") or it.get("unit") or "",
    }


def _unit_to_g(amount: float, unit: str) -> float:
    unit = unit.replace(" ", "")
    if unit == "lb":
        return amount * 453.592
    if unit == "oz":
        return amount * 28.3495
    if unit == "kg":
        return amount * 1000.0
    if unit == "g":
        return amount
    if unit == "floz":
        return amount * 29.5735  # approx
    return 0.0


def parse_weight_to_g(text: str) -> float:
    if not text:
        return 0.0
    s = text.lower().replace("×", "x")
    total_g = 0.0

    # "2 x 16 oz"
    for qty, amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(oz|lb|kg|g|fl\s*oz)", s):
        total_g += _unit_to_g(float(amount), unit) * float(qty)

    # "1 lb 8 oz" accumulate segment by segment
    for num, unit in re.findall(r"([\d.]+)\s*(oz|lb|kg|g|fl\s*oz)", s):
        total_g += _unit_to_g(float(num), unit)

    if total_g > 0:
        return total_g

    # fallback: single segment
    m = re.search(r"([\d.]+)\s*(oz|lb|kg|g|fl\s*oz)", s)
    if m:
        return _unit_to_g(float(m.group(1)), m.group(2))

    return 0.0


def _normalize_ppu_to_string(ppu) -> str:
    """
    Normalize price_per_unit to a parseable string.
    Accepts:
      - str, e.g. '39.4 ¢/oz', '$0.87/oz', '$2.98/lb', '57.8 ¢/count'
      - dict, e.g. {'amount': '39.4 ¢/oz'} or {'amount': 2.98, 'unit': 'lb'}
    """
    if not ppu:
        return ""
    if isinstance(ppu, str):
        return ppu
    if isinstance(ppu, dict):
        # Prefer taking the complete string
        for k in ("amount", "display", "text", "string"):
            if k in ppu and ppu[k]:
                return str(ppu[k])
        # Assemble '$val/unit'
        val = ppu.get("amount") or ppu.get("price") or ppu.get("value")
        unit = ppu.get("unit") or ppu.get("uom")
        if val is not None and unit:
            return f"${val}/{unit}"
    return str(ppu)


def parse_ppu(ppu) -> tuple[float, str]:
    """
    Parse price per unit into (price, unit).
    Supports:
      - each/count: '57.8 ¢/count', '$0.58/count', '$0.58/ea', '$0.58/each'
      - weight: '¢/oz', '$/oz', '$/lb', '$/kg', '$/fl oz'
    """
    s = _normalize_ppu_to_string(ppu).lower().strip()
    if not s:
        return (0.0, "g")

    # each / count
    m = re.match(r"([\d.]+)\s*¢\s*/\s*(count|ea|each)", s)
    if m:
        return (float(m.group(1)) / 100.0, "each")
    m = re.match(r"\$?\s*([\d.]+)\s*/\s*(count|ea|each)", s)
    if m:
        return (float(m.group(1)), "each")

    # weight
    m = re.match(r"([\d.]+)\s*¢\s*/\s*oz", s)
    if m:
        return ((float(m.group(1)) / 100.0) / 28.3495, "g")
    m = re.match(r"\$?\s*([\d.]+)\s*/\s*oz", s)
    if m:
        return (float(m.group(1)) / 28.3495, "g")
    m = re.match(r"\$?\s*([\d.]+)\s*/\s*lb", s)
    if m:
        return (float(m.group(1)) / 453.592, "g")
    m = re.match(r"\$?\s*([\d.]+)\s*/\s*kg", s)
    if m:
        return (float(m.group(1)) / 1000.0, "g")
    m = re.match(r"\$?\s*([\d.]+)\s*/\s*fl\s*oz", s)
    if m:
        return (float(m.group(1)) / 29.5735, "g")

    return (0.0, "g")

_CACHE_LOCK = threading.Lock()
from pathlib import Path

# Locate current script’s directory (module folder)
MODULE_DIR = Path(__file__).resolve().parent
CACHE_DIR = MODULE_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)  # ensure folder exists

_CACHE_FILE = CACHE_DIR / ".cache_walmart.json"

def _cache_read() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text("utf-8"))
        except Exception:
            return {}
    return {}

def _cache_write(data: dict):
    tmp = _CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_CACHE_FILE)

def get_prices_parallel(names: list[str], max_workers: int = 8) -> dict[str, tuple[float,str]]:
    """
    Fetch prices concurrently with a minimal disk cache.
    Return {name_lower: (price, unit)}
    """
    cache = _cache_read()
    todo = []
    results: dict[str, tuple[float,str]] = {}

    # Cache hit
    for n in names:
        k = n.strip().lower()
        if not k:
            continue
        if k in cache:
            results[k] = tuple(cache[k])  # (price, unit)
        else:
            todo.append(k)

    if todo:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(search_walmart, n): n for n in todo}
            for fut in as_completed(futs):
                n = futs[fut]
                try:
                    price, unit = fut.result()
                except Exception:
                    price, unit = 0.0, "g"
                results[n] = (price, unit)

        # Write back to cache
        with _CACHE_LOCK:
            cache.update({k: list(v) for k, v in results.items()})
            _cache_write(cache)

    return results

@lru_cache(maxsize=256)
def search_walmart(ingredient: str):
    k = (ingredient or "").strip().lower()

    # ① Read disk cache first
    try:
        cache = _cache_read()
        hit = cache.get(k)
        if hit:
            return (float(hit[0]), str(hit[1]))
    except Exception:
        pass

    # ② Live fetch with better unit preference
    try:
        print("Start Walmart search for:", ingredient)
        resp = serpapi_walmart_search(k, num=1)
        item = extract_first_item(resp)
        if not item:
            result = (0.0, "g")
        else:
            price = item["price"]                # total $ for the product (if present)
            title = item["title"] or ""
            size_str = item["size_str"] or ""
            text = f"{title} {size_str}".lower()

            # Parse PPU ($/unit) first
            ppu_val, ppu_unit = parse_ppu(item["ppu_raw"])  # e.g. ($0.58, "each") or ($/g)

            # A) If PPU clearly says "each", prefer that.
            if ppu_unit == "each" and ppu_val and ppu_val > 0:
                result = (float(ppu_val), "each")

            # B) Else if title/spec implies per-each and we have a total price → treat as each.
            elif price is not None and re.search(r"\b(ea|each|count)\b", text):
                result = (float(price), "each")

            else:
                # Try weight-based: if we know total price and we can parse total grams.
                weight_g = parse_weight_to_g(size_str or title)
                if price is not None and weight_g > 0:
                    result = (float(price) / float(weight_g), "g")
                elif ppu_val and ppu_val > 0:
                    # Fallback to whatever PPU gave us (could be g via oz/lb, etc.)
                    result = (float(ppu_val), str(ppu_unit))
                else:
                    result = (0.0, "g")
    except Exception:
        result = (0.0, "g")

    # ③ Write back to disk cache
    try:
        cache = _cache_read()
        cache[k] = [float(result[0]), str(result[1])]
        _cache_write(cache)
    except Exception:
        pass

    return result



if __name__ == "__main__":
    """
    Run this file directly to pre-fill Walmart cache with common ingredients.
    This will:
      - Load or create .cache_walmart.json
      - Query Walmart (via SerpAPI) for each ingredient if not cached
      - Save results to disk
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Common ingredients list — feel free to modify or expand
    common_items = [
        # Proteins
        "egg", "chicken breast", "ground beef", "bacon", "salmon",
        "shrimp", "pork loin", "tofu",
        # Dairy
        "milk", "butter", "cheddar cheese", "yogurt", "cream cheese",
        "parmesan cheese",
        # Oils & condiments
        "olive oil", "vegetable oil", "soy sauce", "ketchup", "mayonnaise",
        # Vegetables
        "onion", "garlic", "carrot", "potato", "tomato", "bell pepper",
        "broccoli", "spinach", "lettuce", "cucumber",
        # Fruits
        "apple", "banana", "orange", "lemon", "lime", "strawberry",
        # Grains
        "rice", "flour", "bread", "spaghetti", "oats",
        # Canned / packaged
        "canned tomatoes", "black beans", "chicken broth", "coconut milk",
        # Spices
        "salt", "black pepper", "cumin", "paprika", "oregano", "cinnamon",
    ]

    # Read existing cache from disk
    cache = _cache_read()
    to_fetch = [i for i in common_items if i.lower() not in cache]
    print(f"[INIT] Walmart cache path: {_CACHE_FILE.resolve()}")
    print(f"[INIT] Existing entries: {len(cache)} | Need to fetch: {len(to_fetch)}")

    if not to_fetch:
        print("[INFO] All common items already cached ✅")
    else:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(search_walmart, item): item for item in to_fetch}
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    price, unit = fut.result()
                    print(f"[OK] {name:20s} -> {price:.6f} USD/{unit}")
                    cache[name.lower()] = [price, unit]
                except Exception as e:
                    print(f"[FAIL] {name:20s} -> {e}")

        _cache_write(cache)
        print(f"[DONE] Cache updated. Total entries: {len(cache)} ✅")


