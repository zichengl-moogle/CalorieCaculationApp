"""
===============================================================================
scraper_recipe.py — Recipe Scraping and Ingredient Parsing Module
===============================================================================

Author: Lanshun Yuan (lanshuny)
Team Name: Smart Bite
Course: Heinz College — Python Programming for Information Systems
Institution: Carnegie Mellon University
Semester: Fall 2025

-------------------------------------------------------------------------------
Purpose:
    This module handles all recipe-related data acquisition and preprocessing.
    It connects to the Allrecipes website, retrieves recipe pages, and extracts
    structured ingredient and metadata information for downstream use.

    Key responsibilities:
        • Perform query-based recipe search and result URL extraction
        • Parse recipe pages into structured `Recipe` and `Ingredient` objects
        • Normalize ingredient units and handle both weight- and count-based items
        • Estimate gram weights for various units and common ingredient types
        • Apply heuristic density conversions (e.g., oil, rice, sugar)
        • Support “each”-based measurements (e.g., eggs, cloves, slices)
        • Detect and skip optional or approximate ingredients
        • Provide per-ingredient meta information for caching and analysis

-------------------------------------------------------------------------------
Inputs / Outputs:
    Input  → Allrecipes.com search results and recipe detail pages
    Output → List[Recipe] objects, each containing a list of Ingredient objects
              (used later by price and nutrition modules)

-------------------------------------------------------------------------------
Dependencies:
    - requests, BeautifulSoup4
    - dataclasses, re, json, hashlib, time, random
    - Internal modules: none (stand-alone component)

-------------------------------------------------------------------------------
Notes:
    • All scraping is lightweight, respectful, and non-intrusive for educational use.
    • Includes fallback DOM parsers and regex-based normalization for robustness.
    • Designed to work fully offline once recipes are cached locally.
    • No absolute paths or auto-installation; all dependencies installed manually.

===============================================================================
"""
from __future__ import annotations
import re, json, time, random, hashlib
from typing import List, Optional, Dict, Tuple
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field

# ================== Data models ==================
@dataclass
class Ingredient:
    name: str                     # cleaned original name (lowercased)
    canonical_name: str           # canonical name (for search/nutrition/price)
    quantity_g: Optional[float]   # converted grams (0 allowed)
    optional: bool = False
    to_taste: bool = False
    approx: bool = False
    skip_for_kcal: bool = False
    prep: str = ""                # chopped/minced/... (prep info)
    meta: Dict[str, str] = field(default_factory=dict)  # meta includes each, why_zero, display_qty, etc.

@dataclass
class Recipe:
    id: str
    title: str
    url: str
    servings: Optional[int]
    ingredients: List[Ingredient]
    meta: Dict[str, object] = field(default_factory=dict)

# ================== HTTP session ==================
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CMU-MISM-RecipeBot/1.4 (+edu use; respectful crawling)"
})
BASE = "https://www.allrecipes.com"

def _get(url: str, tries: int = 2, sleep_base: float = 0.4) -> str:
    last = None
    for i in range(tries):
        try:
            resp = SESSION.get(url, timeout=15)
            if resp.status_code == 200:
                return resp.text
            last = f"HTTP {resp.status_code}"
        except Exception as e:
            last = str(e)
        time.sleep(sleep_base * (1.6 ** i) + random.uniform(0, 0.4))
    raise RuntimeError(f"GET failed for {url}: {last}")

# ================== Helpers ==================
def _unique(seq):
    seen = set(); out = []
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def search_allrecipes(query: str, top_k: int = 5) -> List[str]:
    url = f"{BASE}/search?q={quote_plus(query)}"
    html = _get(url)
    # lxml is faster; if your environment doesn't have lxml installed, change to "html.parser"
    soup = BeautifulSoup(html, "lxml")
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"^https?://www\.allrecipes\.com/recipe/\d+/", href):
            urls.append(href)
    return _unique(urls)[: max(1, min(top_k, len(urls)))]

def _extract_jsonld_recipe(soup: BeautifulSoup) -> Optional[dict]:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        candidates = []
        if isinstance(data, dict):
            candidates = [data] + data.get("@graph", [])
        elif isinstance(data, list):
            candidates = data
        for obj in candidates:
            if isinstance(obj, dict) and obj.get("@type") in ("Recipe", ["Recipe"]):
                return obj
    return None

def _parse_int(s: Optional[str]) -> Optional[int]:
    if not s: return None
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else None

def _parse_ingredients_from_dom(soup: BeautifulSoup) -> List[str]:
    items: List[str] = []
    sec = soup.select_one("section.ingredients-section")
    if sec:
        for span in sec.select("li.ingredients-item span.ingredients-item-name"):
            txt = span.get_text(" ", True)
            if txt:
                items.append(txt)
    if not items:
        sec2 = soup.select_one(
            "section[class*='structured-ingredients'], "
            "div[class*='structured-ingredients']"
        )
        if sec2:
            for li in sec2.select("li"):
                txt = li.get_text(" ", True)
                if txt:
                    items.append(txt)
    if not items:
        header = None
        for h in soup.select("h2, h3"):
            if "ingredient" in h.get_text().lower():
                header = h; break
        cur = header.next_sibling if header else None
        while cur and getattr(cur, "name", None) not in ("h2", "h3"):
            for li in getattr(cur, "find_all", lambda *a, **k: [])("li"):
                txt = li.get_text(" ", True)
                if txt:
                    items.append(txt)
            cur = getattr(cur, "next_sibling", None)

    bad_pat = re.compile(
        r"(keep\s*screen\s*awake|oops!|log\s*in|log\s*out|my\s*account|"
        r"account settings|help|view all|recipes\b|occasions|kitchen tips|"
        r"collections|saved|^1/2x$|^1x$|^2x$)",
        re.I
    )
    numeric_only_re = re.compile(r"^[\d\s¼½¾⅓⅔/.\-]+$")
    punct_only_re = re.compile(r"^[\s\-\u2013\u2014\u2022=\.]+$")
    clean: List[str] = []
    seen = set()
    for raw in items:
        t = re.sub(r"\s+", " ", raw).strip()
        if (not t or bad_pat.search(t) or numeric_only_re.match(t.lower()) or punct_only_re.match(t)):
            continue
        if len(t) > 140 or t.lower().startswith((
            "add ","stir ","pour ","heat ","cook ","reduce ","season ",
            "whisk ","drain ","bake ","serve "
        )):
            continue
        if t not in seen:
            seen.add(t); clean.append(t)
    return clean

def _parse_calories(cal_str: Optional[str], fallback_text: str, soup: BeautifulSoup) -> Optional[int]:
    if cal_str:
        m = re.search(r"(\d{2,4})", cal_str.replace(",", ""))
        if m:
            return int(m.group(1))
    for sel in ["section.nutrition-section", "[class*='nutrition']", "div#nutrition-section"]:
        node = soup.select_one(sel)
        if not node: continue
        t = node.get_text(separator=" ", strip=True)
        m = re.search(r"Calories\s+(\d{2,4})\b", t, flags=re.I)
        if m: return int(m.group(1))
    m = re.search(r"Nutrition Facts.*?Calories\s+(\d{2,4})\b", fallback_text, flags=re.I|re.S)
    return int(m.group(1)) if m else None

# ================== Units & knowledge ==================
_VULGAR = {
    "¼": 0.25, "½": 0.5, "¾": 0.75,
    "⅓": 1/3, "⅔": 2/3,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875
}

UNIT_SYNONYMS = {
    "pound": "lb", "pounds": "lb", "lb": "lb", "lbs": "lb",
    "ounce": "oz", "ounces": "oz", "oz": "oz",
    "gram": "g", "grams": "g", "g": "g",
    "kilogram": "kg", "kilograms": "kg", "kg": "kg",

    "cup": "cup", "cups": "cup",
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsp": "tbsp",
    "teaspoon": "tsp", "teaspoons": "tsp", "tsp": "tsp",
    "liter": "l", "liters": "l", "l": "l",
    "milliliter": "ml", "milliliters": "ml", "ml": "ml",

    # Count/per-piece → each (also includes common pieces / clove / slice, etc.)
    "each": "each", "ea": "each", "count": "each",
    "piece": "each", "pieces": "each",
    "clove": "each", "cloves": "each",
    "leaf": "each", "leaves": "each",
    "sprig": "each", "sprigs": "each",
    "slice": "each", "slices": "each",
}

MASS_PER_UNIT = {
    "lb": 453.59237,
    "oz": 28.349523125,
    "kg": 1000.0,
    "g": 1.0,
    "cup": 240.0, "tbsp": 15.0, "tsp": 5.0,
    "l": 1000.0, "ml": 1.0,
}

# Volume → grams: cover typical densities; if not covered, fall back to water density
DENSITY_RULES = [
    (re.compile(r"\b((glutinous|sweet|sticky)\s+rice|rice(?!\s+vinegar))\b", re.I),
        {"cup": 185.0, "tbsp": 185.0/16.0, "tsp": 185.0/48.0}),
    (re.compile(r"\b(olive|vegetable|canola|peanut|sesame)\s+oil\b|\boil\b", re.I),
        {"cup": 218.0, "tbsp": 218.0/16.0, "tsp": 218.0/48.0}),
    (re.compile(r"\b(broth|stock)\b", re.I),
        {"cup": 240.0, "tbsp": 15.0, "tsp": 5.0}),
    (re.compile(r"\b(light\s+)?brown\s+sugar\b", re.I),
        {"cup": 220.0, "tbsp": 220.0/16.0, "tsp": 220.0/48.0}),
    (re.compile(r"\b(granulated)?\s*sugar\b", re.I),
        {"cup": 200.0, "tbsp": 200.0/16.0, "tsp": 200.0/48.0}),
]

SIZE_MULTIPLIER = {"small": 0.7, "large": 1.3, "extra large": 1.5}
GINGER_G_PER_INCH = 5.5
PREP_WORDS = {
    "chopped","diced","minced","sliced","crushed","ground","grated","shredded",
    "beaten","peeled","seeded","deveined","rinsed","drained","softened","melted",
    "cubed","halved","julienned","thinly","thickly","coarsely","finely"
}
OPTIONAL_PATTERNS = [
    ("optional", "optional"),
    ("to taste", "to_taste"),
    ("as needed", "to_taste"),
    ("as required", "to_taste"),
    ("for garnish", "approx"),
    ("for serving", "approx"),
    ("for sprinkling", "approx"),
    ("for frying", "approx"),
    ("for brushing", "approx"),
]
SYNONYM_CANONICAL = {
    "scallions": "green onion",
    "scallion": "green onion",
    "spring onions": "green onion",
    "spring onion": "green onion",
    "green onions": "green onion",
    "extra-virgin olive oil": "olive oil",
    "extra virgin olive oil": "olive oil",
    "brown sugar": "brown sugar",
}

def _vulgar_to_float(token: str) -> Optional[float]:
    t = token.strip()
    if t in _VULGAR: return _VULGAR[t]
    if re.fullmatch(r"\d+\s*/\s*\d+", t):
        n,d = re.split(r"\s*/\s*", t)
        try: return float(n)/float(d)
        except ZeroDivisionError: return None
    try: return float(t)
    except ValueError: return None

# ---------- New: pre-scan weight (parentheses / multiply sign / hyphen) ----------
_WEIGHT_UNITS = r"(?:pounds?|lbs?|oz|ounces?|kg|g|fl\s*oz)"
_PACK_RE  = re.compile(r"(?P<count>\d+(?:\.\d+)?)\s*[x×]\s*(?P<amt>\d+(?:\.\d+)?)\s*(?P<u>%s)" % _WEIGHT_UNITS, re.I)
_PAREN_RE = re.compile(r"\(\s*(?P<amt>\d+(?:\.\d+)?)\s*(?P<u>%s)\s*\)" % _WEIGHT_UNITS, re.I)
_HYPHEN_RE= re.compile(r"(?P<amt>\d+(?:\.\d+)?)\s*-\s*(?P<u>%s)\b" % _WEIGHT_UNITS, re.I)

def _unit_to_g_simple(amount: float, unit: str) -> float:
    u = unit.lower().replace(" ", "")
    if   u in ("lb","lbs","pound","pounds"): return amount * 453.59237
    elif u in ("oz","ounce","ounces"):       return amount * 28.349523125
    elif u == "kg":                           return amount * 1000.0
    elif u == "g":                            return amount
    elif u in ("floz","floz"):                return amount * 29.5735  # volume approximation: water/oil
    return 0.0

def _preextract_weight_grams(line: str) -> float:
    """Pre-check total grams for the whole line: 2x16 oz / (8 pound) / 8-pound, etc. Return >0 if hit, else 0."""
    s = line.lower()

    # 2 x 16 oz
    m = _PACK_RE.search(s)
    if m:
        cnt = float(m.group("count")); amt = float(m.group("amt")); u = m.group("u")
        g = _unit_to_g_simple(amt, u) * cnt
        if g > 0: return g

    # (8 pound)
    m = _PAREN_RE.search(s)
    if m:
        amt = float(m.group("amt")); u = m.group("u")
        g = _unit_to_g_simple(amt, u)
        lead = re.match(r"^\s*(\d+(?:\.\d+)?)\b", s)  # leading count like "1 (8 pound)"
        if lead: g *= float(lead.group(1))
        if g > 0: return g

    # 8-pound / 8-oz
    m = _HYPHEN_RE.search(s)
    if m:
        amt = float(m.group("amt")); u = m.group("u")
        g = _unit_to_g_simple(amt, u)
        lead = re.match(r"^\s*(\d+(?:\.\d+)?)\b", s)
        if lead: g *= float(lead.group(1))
        if g > 0: return g

    return 0.0
# ---------- Pre-scan END ----------

def _parse_quantity(text: str):
    """
    Return (qty, unit, remainder, paren_qty, paren_unit)
    """
    s = text.strip()
    s = s.split(",", 1)[0].strip()

    qty = None; unit = None; paren_qty = None; paren_unit = None

    # (10.5 ounce) / (4 pound) / (2 inch)
    lead_paren = re.match(
        r"^[\s\-\u2013\u2014\u2022]*\(\s*(\d+(?:\.\d+)?|\d+\s*/\s*\d+|[¼½¾⅓⅔⅛⅜⅝⅞])\s*"
        r"(ounce|ounces|oz|pound|pounds|lb|lbs|g|kg|cup|cups|tbsp|tablespoon|tsp|teaspoon|inch|in|cm)\s*\)",
        s, flags=re.I
    )
    if lead_paren:
        q_raw = lead_paren.group(1); u_raw = lead_paren.group(2).lower()
        paren_qty = _vulgar_to_float(q_raw); paren_unit = u_raw
        s = s[lead_paren.end():].lstrip()
    else:
        any_paren = re.search(
            r"\(\s*(\d+(?:\.\d+)?|\d+\s*/\s*\d+|[¼½¾⅓⅔⅛⅜⅝⅞])\s*"
            r"(ounce|ounces|oz|pound|pounds|lb|lbs|g|kg|cup|cups|tbsp|tablespoon|tsp|teaspoon|inch|in|cm)\s*\)",
            s, flags=re.I
        )
        if any_paren:
            q_raw = any_paren.group(1); u_raw = any_paren.group(2).lower()
            paren_qty = _vulgar_to_float(q_raw); paren_unit = u_raw
            s = (s[:any_paren.start()] + " " + s[any_paren.end():]).strip()

    # quantity: mixed number / single
    m_mix_numeric = re.match(r"^(\d+(?:\.\d+)?)\s+(\d+\s*/\s*\d+)\b", s)
    end = 0
    if m_mix_numeric:
        qty = float(m_mix_numeric.group(1)) + (_vulgar_to_float(m_mix_numeric.group(2)) or 0.0)
        end = m_mix_numeric.end()
    else:
        m_mix_vulgar = re.match(r"^(\d+(?:\.\d+)?)\s*([¼½¾⅓⅔⅛⅜⅝⅞])", s)
        if m_mix_vulgar:
            qty = float(m_mix_vulgar.group(1)) + (_vulgar_to_float(m_mix_vulgar.group(2)) or 0.0)
            end = m_mix_vulgar.end()
        else:
            m_single = re.match(r"^([¼½¾⅓⅔⅛⅜⅝⅞]|\d+(?:\.\d+)?)", s)  # supports concatenations like ½teaspoon
            if m_single:
                qty = _vulgar_to_float(m_single.group(1))
                end = m_single.end()
    s = s[end:].lstrip() if end else s

    # unit (including each/ea/count)
    unit_candidate = None
    parts = s.split()
    if parts:
        unit_candidate = UNIT_SYNONYMS.get(parts[0].lower())
        if unit_candidate is None and len(parts) >= 2:
            unit_candidate = UNIT_SYNONYMS.get(parts[1].lower())
            if unit_candidate is not None:
                s = " ".join(parts[2:]).strip()
        elif unit_candidate is not None:
            s = " ".join(parts[1:]).strip()
    if unit_candidate:
        unit = unit_candidate

    remainder = s.strip()
    return qty, unit, remainder, paren_qty, paren_unit

def _density_for(name: str, unit: str) -> Optional[float]:
    for pat, grams_map in DENSITY_RULES:
        if pat.search(name):
            return grams_map.get(unit)
    return None

def _canonicalize_name(name: str) -> Tuple[str, str, Dict[str, bool], str]:
    n = name.lower().strip()
    n = re.sub(r"\([^)]*\)", " ", n)
    flags = {"optional": False, "to_taste": False, "approx": False, "skip_for_kcal": False}
    for phrase, key in OPTIONAL_PATTERNS:
        if phrase in n:
            flags[key] = True
            if key in ("optional", "to_taste"):
                flags["skip_for_kcal"] = True
            n = n.replace(phrase, " ")
    n = re.sub(r"\b(extra\s+large|large|small|medium|fresh|prepared|unsalted|salted)\b", " ", n)
    n = re.sub(r"\bpieces?\b", " ", n)

    preps = []
    tokens = [t for t in re.split(r"\s+", n) if t]
    kept = []
    for t in tokens:
        if t in PREP_WORDS:
            preps.append(t)
        else:
            kept.append(t)
    n2 = " ".join(kept).strip()
    n2 = re.sub(r"\s+", " ", n2)

    canonical = SYNONYM_CANONICAL.get(n2, n2)
    return canonical, n2, flags, " ".join(preps)

def _inch_to_g_for_item(name: str, inches: float) -> Optional[float]:
    if "ginger" in name:
        return inches * GINGER_G_PER_INCH
    return None

def _convert_to_grams(qty: Optional[float], unit: Optional[str], name: str,
                      pqty: Optional[float]=None, punit: Optional[str]=None) -> Optional[float]:
    # each: do not convert (handled by the each flow)
    if unit == "each":
        return None

    # parentheses inch/cm (e.g., ginger)
    if pqty is not None and punit:
        if punit in ("inch","in","cm"):
            inches = pqty * (0.3937007874 if punit=="cm" else 1.0)
            per = _inch_to_g_for_item(name, inches)
            if per is not None:
                count = qty if qty is not None else 1.0
                return count * per

    # mass units
    if qty is not None and unit in ("lb","oz","kg","g"):
        return qty * MASS_PER_UNIT[unit]

    # volume units (covered by density table, otherwise water density)
    if qty is not None and unit in ("cup","tbsp","tsp","l","ml"):
        dens = _density_for(name, unit)
        if dens is None:
            dens = MASS_PER_UNIT[unit]
        return qty * dens

    # other cases: no weight estimation (handled by each or 0)
    return None

def _normalize_ingredient_line(raw: str) -> Optional[Ingredient]:
    original = raw.strip()
    before_comma = original.split(",", 1)[0].strip()
    if not before_comma:
        return None

    # ① pre-scan total weight for the whole line (handle 1 (8 pound) / 2x16 oz / 8-pound, etc.)
    pre_g = _preextract_weight_grams(before_comma)

    qty, unit, rem, pqty, punit = _parse_quantity(before_comma)

    canonical, cleaned_name, flags, prep = _canonicalize_name(rem)
    name_clean = cleaned_name.strip().lower()
    if not name_clean:
        return None

    grams = None
    why_zero = ""

    # ② if pre-scan already got grams, use it directly
    if pre_g > 0:
        grams = pre_g

    # package specs like (10.5 ounce): count × spec
    if grams is None and pqty is not None and punit and punit in UNIT_SYNONYMS:
        base = MASS_PER_UNIT.get(UNIT_SYNONYMS[punit], None)
        if base:
            count = qty if qty is not None else 1.0
            grams = count * pqty * base

    if grams is None:
        grams = _convert_to_grams(qty, unit, name_clean, pqty, punit)

    # each: do not convert to grams; record each_count
    if (unit == "each") or (grams is None and (qty is not None and unit is None)):
        piece_count = qty if qty is not None else 1.0
        meta = {
            "alias_raw": original,
            "kept_before_comma": before_comma,
            "quantity_parsed": "" if qty is None else str(qty),
            "unit_parsed": unit or "",
            "paren_quantity": "" if pqty is None else str(pqty),
            "paren_unit": punit or "",
            "name_parsed": name_clean,
            "prep": prep,
            "unit_canonical": "each",
            "each_count": str(piece_count),
            "display_qty": f"{piece_count} each",
            "why_zero": "unit=each (by design not converted to grams)",
        }
        return Ingredient(
            name=name_clean,
            canonical_name=canonical,
            quantity_g=0.0,
            optional=flags["optional"],
            to_taste=flags["to_taste"],
            approx=flags["approx"],
            skip_for_kcal=flags["skip_for_kcal"],
            prep=prep,
            meta=meta
        )

    # non-each: in grams
    out_qty_g = 0.0
    if grams is None:
        why_zero = "no conversion rule matched (qty/unit missing or unsupported)"
        out_qty_g = 0.0
    else:
        out_qty_g = float(grams)

    meta = {
        "alias_raw": original,
        "kept_before_comma": before_comma,
        "quantity_parsed": "" if qty is None else str(qty),
        "unit_parsed": unit or "",
        "paren_quantity": "" if pqty is None else str(pqty),
        "paren_unit": punit or "",
        "name_parsed": name_clean,
        "prep": prep,
        "display_qty": f"{out_qty_g:.2f} g" if out_qty_g > 0 else "0 g",
    }
    if out_qty_g == 0.0:
        meta["why_zero"] = why_zero or "grams computed as 0"

    return Ingredient(
        name=name_clean,
        canonical_name=canonical,
        quantity_g=round(out_qty_g, 2),
        optional=flags["optional"],
        to_taste=flags["to_taste"],
        approx=flags["approx"],
        skip_for_kcal=flags["skip_for_kcal"],
        prep=prep,
        meta=meta
    )

# ================== Page parsing ==================
def parse_recipe_page(url: str) -> Recipe:
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")
    text_all = soup.get_text(separator=" ", strip=True)
    data = _extract_jsonld_recipe(soup)

    title = None; servings = None; ingredients_raw = []; calories = None
    if data:
        title = data.get("name") or data.get("headline")
        servings = _parse_int(data.get("recipeYield"))
        lst = data.get("recipeIngredient")
        if isinstance(lst, list):
            ingredients_raw = [i for i in lst if isinstance(i, str) and i.strip()]
        nut = data.get("nutrition") or {}
        calories = _parse_calories(nut.get("calories"), text_all, soup)

    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else url
    if not servings:
        m = re.search(r"Servings:\s*(\d+)", text_all, flags=re.I)
        servings = int(m.group(1)) if m else None
    if not ingredients_raw:
        ingredients_raw = _parse_ingredients_from_dom(soup)
    if calories is None:
        calories = _parse_calories(None, text_all, soup)

    ing_objs = [ing for ing in (_normalize_ingredient_line(raw) for raw in ingredients_raw) if ing]

    rid = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
    return Recipe(
        id=rid, title=title or "unknown", url=url,
        servings=servings, ingredients=ing_objs,
        meta={"calories_kcal_per_serving": calories}
    )

def scrape_recipes(query: str, top_k: int = 5, _use_cache: bool = True) -> List[Recipe]:
    urls = search_allrecipes(query, top_k=top_k)
    out: List[Recipe] = []
    for u in urls:
        time.sleep(random.uniform(0.0, 0.3))
        try:
            r = parse_recipe_page(u); out.append(r)
        except Exception:
            continue
    return out
