# scraper_recipe.py - enhanced version
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
    name: str                     # 清洗后的原名（小写）
    canonical_name: str           # 规范名（用于检索/营养/价格）
    quantity_g: Optional[float]   # 换算后的克（允许 0）
    optional: bool = False
    to_taste: bool = False
    approx: bool = False
    skip_for_kcal: bool = False
    prep: str = ""                # chopped/minced/...（预处理信息）
    meta: Dict[str, str] = field(default_factory=dict)

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
    punct_only_re = re.compile(r"^[\s\-\u2013\u2014\u2022=\.]+$")  # 只含分隔符/空白
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

    "clove": "clove", "cloves": "clove",
    "leaf": "leaf", "leaves": "leaf",
    "sprig": "sprig", "sprigs": "sprig",
    "piece": "piece", "pieces": "piece",
}

# 质量单位（体积单位默认=水密度，后面会按食材覆盖）
MASS_PER_UNIT = {
    "lb": 453.59237,
    "oz": 28.349523125,
    "kg": 1000.0,
    "g": 1.0,
    "cup": 240.0, "tbsp": 15.0, "tsp": 5.0,
    "l": 1000.0, "ml": 1.0,
}

# 体积→克：食材特异密度（匹配到则覆盖上面的 cup/tbsp/tsp）
DENSITY_RULES = [
    # 米类（未煮未洗堆密度）
    (re.compile(r"\b((glutinous|sweet|sticky)\s+rice|rice(?!\s+vinegar))\b", re.I),
        {"cup": 185.0, "tbsp": 185.0/16.0, "tsp": 185.0/48.0}),
    # 油类
    (re.compile(r"\b(olive|vegetable|canola|peanut|sesame)\s+oil\b|\boil\b", re.I),
        {"cup": 218.0, "tbsp": 218.0/16.0, "tsp": 218.0/48.0}),
    # broth/stock ≈ 水
    (re.compile(r"\b(broth|stock)\b", re.I),
        {"cup": 240.0, "tbsp": 15.0, "tsp": 5.0}),
    # 糖
    (re.compile(r"\b(light\s+)?brown\s+sugar\b", re.I),
        {"cup": 220.0, "tbsp": 220.0/16.0, "tsp": 220.0/48.0}),
    (re.compile(r"\b(granulated)?\s*sugar\b", re.I),
        {"cup": 200.0, "tbsp": 200.0/16.0, "tsp": 200.0/48.0}),
]

# 明确件数单位
PIECE_HEURISTICS = [
    (("garlic",), "clove", 3.0),
    (("bay", "leaf"), "leaf", 0.2),
    (("parsley",), "sprig", 1.0),
]

# 无单位时的“估重/个”
ESTIMATED_WEIGHTS = {
    "green onion": 15.0, "scallion": 15.0, "spring onion": 15.0,
    "onion": 110.0,
    "carrot": 60.0,
    "egg": 50.0,
    "mushroom": 18.0,
    "potato": 150.0,
    "tomato": 120.0,
    "lemon": 65.0, "lime": 65.0,
    "bell pepper": 120.0,
    "hamburger bun": 50.0, "bun": 50.0,
    "ginger": 10.0,  # 没有长度信息时按块估
}

SIZE_MULTIPLIER = {"small": 0.7, "large": 1.3, "extra large": 1.5}
GINGER_G_PER_INCH = 5.5  # 2-inch piece ≈ 11 g

PREP_WORDS = {
    "chopped","diced","minced","sliced","crushed","ground","grated","shredded",
    "beaten","peeled","seeded","deveined","rinsed","drained","softened","melted",
    "cubed","halved","julienned","thinly","thickly","coarsely","finely"
}

# 可选/随意用量标记
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

# 规范名同义
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

def _parse_quantity(text: str):
    """
    Return (qty, unit, remainder, paren_qty, paren_unit)
    """
    s = text.strip()
    s = s.split(",", 1)[0].strip()

    qty = None; unit = None; paren_qty = None; paren_unit = None

    # 括号规格 (10.5 ounce) / (4 pound) / (2 inch)
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

    # 数量：混合数 2 1/4 / 2 ¼，或单独 ½ / 2 / 2.5
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
            m_single = re.match(r"^([¼½¾⅓⅔⅛⅜⅝⅞]|\d+(?:\.\d+)?)", s)  # 支持 ½teaspoon 连写
            if m_single:
                qty = _vulgar_to_float(m_single.group(1))
                end = m_single.end()
    s = s[end:].lstrip() if end else s

    # 单位：第一词或“形容词 + 单位”（large cloves garlic）
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
    """返回 canonical_name, cleaned_name, flags, prep"""
    n = name.lower().strip()
    # 去括号
    n = re.sub(r"\([^)]*\)", " ", n)
    # 标记可选/随意
    flags = {"optional": False, "to_taste": False, "approx": False, "skip_for_kcal": False}
    for phrase, key in OPTIONAL_PATTERNS:
        if phrase in n:
            flags[key] = True
            if key in ("optional", "to_taste"):
                flags["skip_for_kcal"] = True
            n = n.replace(phrase, " ")
    # 去修饰
    n = re.sub(r"\b(extra\s+large|large|small|medium|fresh|prepared|unsalted|salted)\b", " ", n)
    n = re.sub(r"\bpieces?\b", " ", n)

    # 提取切法等
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

    # 规范名同义
    canonical = SYNONYM_CANONICAL.get(n2, n2)
    return canonical, n2, flags, " ".join(preps)

def _match_estimate_key(name: str) -> Optional[Tuple[str, float]]:
    # 优先匹配更长的 key，避免 'onion' 抢到 'green onion'
    for key in sorted(ESTIMATED_WEIGHTS.keys(), key=lambda x: -len(x)):
        if re.search(rf"\b{re.escape(key)}\b", name):
            return key, ESTIMATED_WEIGHTS[key]
    return None

def _inch_to_g_for_item(name: str, inches: float) -> Optional[float]:
    if "ginger" in name:    # 姜按长度估重
        return inches * GINGER_G_PER_INCH
    return None

def _convert_to_grams(qty: Optional[float], unit: Optional[str], name: str,
                      pqty: Optional[float]=None, punit: Optional[str]=None) -> Optional[float]:
    # 括号中的“inch/cm”专用（如姜）
    if pqty is not None and punit:
        if punit in ("inch","in","cm"):
            inches = pqty * (0.3937007874 if punit=="cm" else 1.0)
            per = _inch_to_g_for_item(name, inches)
            if per is not None:
                count = qty if qty is not None else 1.0
                return count * per

    # 质量单位
    if qty is not None and unit in ("lb","oz","kg","g"):
        return qty * MASS_PER_UNIT[unit]

    # 体积单位：按食材密度表覆盖，否则按水密度
    if qty is not None and unit in ("cup","tbsp","tsp","l","ml"):
        dens = _density_for(name, unit)
        if dens is None:
            dens = MASS_PER_UNIT[unit]
        return qty * dens

    # 明确件数单位
    if qty is not None and unit:
        for keywords, piece_unit, grams_per in PIECE_HEURISTICS:
            if unit == piece_unit and all(k in name for k in keywords):
                return qty * grams_per
        if unit == "piece":
            est = _match_estimate_key(name)
            if est:
                key, grams_per = est
                return qty * grams_per

    # 无单位但有数量：按估重
    if qty is not None and unit is None:
        mult = 1.0
        if "extra large" in name: mult = SIZE_MULTIPLIER["extra large"]
        elif "large" in name:     mult = SIZE_MULTIPLIER["large"]
        elif "small" in name:     mult = SIZE_MULTIPLIER["small"]
        est = _match_estimate_key(name)
        if est:
            key, grams_per = est
            return qty * grams_per * mult

    return None

def _normalize_ingredient_line(raw: str) -> Optional[Ingredient]:
    original = raw.strip()
    before_comma = original.split(",", 1)[0].strip()
    if not before_comma:
        return None

    qty, unit, rem, pqty, punit = _parse_quantity(before_comma)

    # 规范化名字 + 标记
    canonical, cleaned_name, flags, prep = _canonicalize_name(rem)
    name_clean = cleaned_name.strip().lower()
    if not name_clean:
        return None

    grams = None

    # (10.5 ounce) 这类包规格：count × 规格
    if pqty is not None and punit and punit in UNIT_SYNONYMS:
        base = MASS_PER_UNIT.get(UNIT_SYNONYMS[punit], None)
        if base:
            count = qty if qty is not None else 1.0
            grams = count * pqty * base

    if grams is None:
        grams = _convert_to_grams(qty, unit, name_clean, pqty, punit)

    if grams is None:
        grams = 0.0  # 统一用 0

    meta = {
        "alias_raw": original,
        "kept_before_comma": before_comma,
        "quantity_parsed": "" if qty is None else str(qty),
        "unit_parsed": unit or "",
        "paren_quantity": "" if pqty is None else str(pqty),
        "paren_unit": punit or "",
        "name_parsed": name_clean,
        "prep": prep
    }
    return Ingredient(
        name=name_clean,
        canonical_name=canonical,
        quantity_g=round(float(grams), 2),
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


