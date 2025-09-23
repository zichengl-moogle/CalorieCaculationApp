# scraper_recipe.py
"""
Scrape Allrecipes and normalize ingredients:
- Keep only the part before the first comma in each ingredient line.
- Parse quantity (supports unicode/vulgar fractions, e.g., ½ ¼ ⅔; "2 1/2"; decimals).
- Convert supported units to grams (g).
- Handle parenthetical pack sizes like "(10.5 ounce) can" or "(4 pound)".
- Estimate grams for common count-based items when unit is missing (onion, carrot, egg, etc.),
  with size modifiers (small/large/extra large).
- Ingredient names are normalized to lowercase without quantity/unit words.
"""
from __future__ import annotations
import re
import json
import time
import random
import hashlib
from typing import List, Optional, Dict, Tuple
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field


# ================== Data models ==================
@dataclass
class Ingredient:
    name: str                     # normalized ingredient name, lowercase
    quantity_g: Optional[float]   # converted mass in grams if possible
    meta: Dict[str, str] = field(default_factory=dict)  # raw line, parsed fields

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
    "User-Agent": "CMU-MISM-RecipeBot/1.2 (+edu use; respectful crawling)"
})
BASE = "https://www.allrecipes.com"


def _get(url: str, tries: int = 3, sleep_base: float = 1.2) -> str:
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
    if not s:
        return None
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
    punct_only_re = re.compile(r"^[\s\-\u2013\u2014\u2022=\.]+$")  # ← 新增：只含分隔符/空白

    clean: List[str] = []
    seen = set()
    for raw in items:
        t = re.sub(r"\s+", " ", raw).strip()
        if (not t or bad_pat.search(t) or numeric_only_re.match(t.lower())
                or punct_only_re.match(t)):  # ← 新增
            continue
        if len(t) > 120 or t.lower().startswith((
                "add ", "stir ", "pour ", "heat ", "cook ", "reduce ", "season ",
                "whisk ", "drain ", "bake ", "serve "
        )):
            continue
        if t not in seen:
            seen.add(t);
            clean.append(t)
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


# ================== Unit normalization ==================
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

    "clove": "clove", "cloves": "clove",
    "leaf": "leaf", "leaves": "leaf",
    "sprig": "sprig", "sprigs": "sprig",
}
# 保证同义词里有单复数写法（某些运行环境不支持 .update 的顺序）
UNIT_SYNONYMS.update({
    "tablespoon": "tbsp", "teaspoon": "tsp",
    "tablespoons": "tbsp", "teaspoons": "tsp",
})

# mass per unit (grams) — generic approximations
MASS_PER_UNIT = {
    "lb": 453.59237,
    "oz": 28.349523125,
    "kg": 1000.0,
    "g": 1.0,
    # volume to grams using water density
    "cup": 240.0,   # US cup ~ 240 ml
    "tbsp": 15.0,
    "tsp": 5.0,
    "l": 1000.0,
    "ml": 1.0,
}

# piece-based heuristics for a few common items with explicit piece unit
PIECE_HEURISTICS = [
    (("garlic",), "clove", 3.0),
    (("bay", "leaf"), "leaf", 0.2),
    (("parsley",), "sprig", 1.0),
]

# estimated average weights for common count-based ingredients (per piece)
ESTIMATED_WEIGHTS = {
    "onion": 110.0,
    "carrot": 60.0,
    "egg": 50.0,
    "mushroom": 18.0,
    "potato": 150.0,
    "tomato": 120.0,
    "lemon": 65.0,
    "lime": 65.0,
    "bell pepper": 120.0,
    "bun": 50.0,                # e.g., hamburger buns
    "hamburger bun": 50.0,
}

# size modifiers
SIZE_MULTIPLIER = {
    "small": 0.7,
    "large": 1.3,
    "extra large": 1.5,
}


def _vulgar_to_float(token: str) -> Optional[float]:
    token = token.strip()
    if token in _VULGAR:
        return _VULGAR[token]
    if re.fullmatch(r"\d+\s*/\s*\d+", token):
        n, d = re.split(r"\s*/\s*", token)
        try:
            return float(n) / float(d)
        except ZeroDivisionError:
            return None
    try:
        return float(token)
    except ValueError:
        return None


def _parse_quantity(text: str):
    """
    Return (qty, unit, remainder, paren_qty, paren_unit)
    - qty/unit: the leading quantity & unit if present (e.g., '2 cups ...' -> 2, 'cup')
    - remainder: leftover text after removing leading qty/unit tokens
    - paren_qty/paren_unit: quantity and unit detected in a parenthesis block like
      '(10.5 ounce)' or '(4 pound)', used for patterns like '2 (10.5 ounce) cans ...'
    """
    s = text.strip()
    # keep only before the first comma
    s = s.split(",", 1)[0].strip()

    qty = None
    unit = None
    paren_qty = None
    paren_unit = None

    # ---------- 1) 强化：前导括号（允许前面有破折号/项目符号/空白） ----------
    lead_paren = re.match(
        r"^[\s\-\u2013\u2014\u2022]*\(\s*(\d+(?:\.\d+)?|\d+\s*/\s*\d+|[¼½¾⅓⅔⅛⅜⅝⅞])\s*"
        r"(ounce|ounces|oz|pound|pounds|lb|lbs|g|kg|cup|cups|tbsp|tablespoon|tsp|teaspoon)\s*\)",
        s, flags=re.I
    )
    if lead_paren:
        q_raw = lead_paren.group(1)
        u_raw = lead_paren.group(2).lower()
        paren_qty = _vulgar_to_float(q_raw)
        paren_unit = UNIT_SYNONYMS.get(u_raw, u_raw)
        s = s[lead_paren.end():].lstrip()
    else:
        # ---------- 1b) 兜底：若行内任何位置出现“( 数字 单位 )”，也识别 ----------
        any_paren = re.search(
            r"\(\s*(\d+(?:\.\d+)?|\d+\s*/\s*\d+|[¼½¾⅓⅔⅛⅜⅝⅞])\s*"
            r"(ounce|ounces|oz|pound|pounds|lb|lbs|g|kg|cup|cups|tbsp|tablespoon|tsp|teaspoon)\s*\)",
            s, flags=re.I
        )
        if any_paren:
            q_raw = any_paren.group(1)
            u_raw = any_paren.group(2).lower()
            paren_qty = _vulgar_to_float(q_raw)
            paren_unit = UNIT_SYNONYMS.get(u_raw, u_raw)
            # 从文本里移除这段括号，便于后续提取名字/单位
            s = (s[:any_paren.start()] + " " + s[any_paren.end():]).strip()

    # ---------- 2) 数量：'2 1/2'、'1½'、'½'、'2' ----------
    m = re.match(r"^(\d+(?:\.\d+)?)\s+(\d+\s*/\s*\d+)\b", s)
    end = 0
    if m:
        qty = float(m.group(1)) + (_vulgar_to_float(m.group(2)) or 0.0)
        end = m.end()
    else:
        # 去掉 \b，支持“½teaspoon”这种连写
        m2 = re.match(r"^([¼½¾⅓⅔⅛⅜⅝⅞]|\d+(?:\.\d+)?)", s)
        if m2:
            qty = _vulgar_to_float(m2.group(1))
            end = m2.end()
    s = s[end:].lstrip() if end else s

    # ---------- 3) 单位：可能是第一词，或形容词+单位（如 "large cloves garlic"） ----------
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



def _extract_unit_and_name(remainder: str) -> Tuple[Optional[str], str]:
    """
    Fallback: if unit still not found, try first token; otherwise return as name.
    """
    if not remainder:
        return (None, "")
    parts = remainder.split()
    if not parts:
        return (None, remainder)
    u = UNIT_SYNONYMS.get(parts[0].lower())
    if u:
        return (u, " ".join(parts[1:]).strip())
    return (None, remainder)


def _convert_to_grams(qty: Optional[float], unit: Optional[str], name: str) -> Optional[float]:
    if qty is None and unit in MASS_PER_UNIT:
        return None

    # direct mass/volume units
    if qty is not None and unit in MASS_PER_UNIT:
        return qty * MASS_PER_UNIT[unit]

    low = name.lower()

    # piece-based heuristics (explicit piece units)
    for keywords, piece_unit, grams_per in PIECE_HEURISTICS:
        if unit == piece_unit and all(k in low for k in keywords):
            return qty * grams_per if qty is not None else grams_per

    # estimated by item name when no clear unit (count-based)
    if unit is None and qty is not None:
        mult = 1.0
        if "extra large" in low:
            mult = SIZE_MULTIPLIER["extra large"]
        elif "large" in low:
            mult = SIZE_MULTIPLIER["large"]
        elif "small" in low:
            mult = SIZE_MULTIPLIER["small"]

        for key, grams_per in ESTIMATED_WEIGHTS.items():
            if key in low:
                return qty * grams_per * mult

    return None


def _normalize_ingredient_line(raw: str) -> Ingredient:
    original = raw.strip()
    # keep only before the first comma
    before_comma = original.split(",", 1)[0].strip()

    # parse quantity (qty, unit, remainder, paren_qty, paren_unit)
    qty, unit, rem, pqty, punit = _parse_quantity(before_comma)

    # Still no unit? try once more
    if unit is None:
        u2, name_guess = _extract_unit_and_name(rem)
        if u2:
            unit = u2
            rem = name_guess

    name_clean = re.sub(r"\s+", " ", rem).strip().lower()

    if not name_clean:
        return None

    grams = None
    # If no quantity at all but item is count-based with known estimate, default to 1
    if qty is None:
        for key in ESTIMATED_WEIGHTS:
            if key in name_clean:
                qty = 1.0
                break

    if grams is None:
        grams = _convert_to_grams(qty, unit, name_clean)

    if grams is None:
        grams = 0.0   # 所有无法识别的都写 0

    meta = {
        "alias_raw": original,
        "kept_before_comma": before_comma,
        "quantity_parsed": "" if qty is None else str(qty),
        "unit_parsed": unit or "",
        "paren_quantity": "" if pqty is None else str(pqty),
        "paren_unit": punit or "",
        "name_parsed": name_clean,
    }
    return Ingredient(
        name=name_clean,
        quantity_g=round(grams, 2),
        meta=meta
    )



# ================== Page parsing ==================
def parse_recipe_page(url: str) -> Recipe:
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")
    text_all = soup.get_text(separator=" ", strip=True)
    data = _extract_jsonld_recipe(soup)

    title = None
    servings = None
    ingredients_raw: List[str] = []
    calories = None

    if data:
        title = data.get("name") or data.get("headline")
        servings = _parse_int(data.get("recipeYield"))
        if isinstance(data.get("recipeIngredient"), list):
            ingredients_raw = [i for i in data["recipeIngredient"] if isinstance(i, str) and i.strip()]
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
            r = parse_recipe_page(u)
            out.append(r)
        except Exception:
            continue
    return out

