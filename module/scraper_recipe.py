# scraper_recipe.py
"""
This part implements real scraping/collection here.
REQUIREMENTS:
- Input: dish name (e.g., "Chicken").
- Return: multiple recipes (list[Recipe]).
- Use Requests+BS4/Selenium.
- Normalize ingredient names to lowercase English; convert quantities to GRAMS.
"""
from __future__ import annotations
import re, json, time, random, hashlib
from typing import List, Optional, Dict
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

# ===== (可选) 兼容你们项目的数据模型 =====
from dataclasses import dataclass, field

@dataclass
class Ingredient:
    name: str
    quantity_g: Optional[float] = None   # MVP：暂不换算克
    meta: Dict[str, str] = field(default_factory=dict)

@dataclass
class Recipe:
    id: str
    title: str
    url: str
    servings: Optional[int]
    ingredients: List[Ingredient]
    meta: Dict[str, object] = field(default_factory=dict)  # 放 calories 等
# MVP: 把热量放到 meta 里

# ===== HTTP 会话：自定义 UA + 简单重试 =====
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CMU-MISM-RecipeBot/1.0 (+edu use; respectful crawling)"
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

# ===== 工具：去重且保序 =====
def _unique(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

# ===== 搜索：从站内搜索页提取 /recipe/<id>/... 链接 =====
def search_allrecipes(query: str, top_k: int = 5) -> List[str]:
    # robots.txt 禁的是 *?kw 不是 ?q，因此 /search?q= 是允许的；仍建议限速。:contentReference[oaicite:3]{index=3}
    url = f"{BASE}/search?q={quote_plus(query)}"
    html = _get(url)
    soup = BeautifulSoup(html, "lxml")

    # 抓所有指向食谱详情的链接（形如 /recipe/12345/xxx/）
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"^https?://www\.allrecipes\.com/recipe/\d+/", href):
            urls.append(href)
    urls = _unique(urls)
    return urls[: max(1, min(top_k, len(urls)))]

# ===== 解析：尽量走 JSON-LD；失败则回退 DOM 文本 =====
def _extract_jsonld_recipe(soup: BeautifulSoup) -> Optional[dict]:
    # 页面常含多段 JSON-LD，需找到 @type == "Recipe" 的对象
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        # 可能是列表、@graph 或单对象
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
    """
    只在配料区块抓取，并清洗掉控件/碎片。
      结构1：section.ingredients-section > li.ingredients-item > span.ingredients-item-name
      结构2：section/div[class*='structured-ingredients'] 下的 li（只取 li，不取 span）
    """
    items: List[str] = []

    # --- 结构1（新版最常见） ---
    sec = soup.select_one("section.ingredients-section")
    if sec:
        for span in sec.select("li.ingredients-item span.ingredients-item-name"):
            txt = span.get_text(" ",True)
            if txt:
                items.append(txt)

    # --- 结构2（mntl 命名）---
    if not items:
        sec2 = soup.select_one(
            "section[class*='structured-ingredients'], "
            "div[class*='structured-ingredients']"
        )
        if sec2:
            # 只取 li，避免把 li 里的各个 span（amount/unit/name）拆成碎片
            for li in sec2.select("li"):
                txt = li.get_text(" ", True)
                if txt:
                    items.append(txt)

    # --- 兜底：Ingredients 标题附近（标题到下一个标题之间） ---
    if not items:
        header = None
        for h in soup.select("h2, h3"):
            if "ingredient" in h.get_text().lower():
                header = h
                break
        cur = header.next_sibling if header else None
        while cur and getattr(cur, "name", None) not in ("h2", "h3"):
            for li in getattr(cur, "find_all", lambda *a, **k: [])("li"):
                txt = li.get_text(" ", True)
                if txt:
                    items.append(txt)
            cur = getattr(cur, "next_sibling", None)

    # --- 清洗：过滤控件/报错/碎片行，规范空白并去重 ---
    bad_pat = re.compile(
        r"(keep\s*screen\s*awake|oops!|log\s*in|log\s*out|my\s*account|"
        r"account settings|help|view all|recipes\b|occasions|kitchen tips|"
        r"collections|saved|back to school|tailgating|dotdash meredith|"
        r"food studios|our favorite products|^1/2x$|^1x$|^2x$)",
        re.I
    )

    units_only = {
        "cup", "cups", "tablespoon", "tablespoons", "tbsp",
        "teaspoon", "teaspoons", "tsp", "clove", "cloves",
        "pound", "pounds", "ounce", "ounces", "oz",
        "gram", "grams", "g", "kg", "ml", "liter", "liters"
    }
    units_alt = r"(?:{})".format("|".join(map(re.escape, units_only)))
    numeric_only_re = re.compile(r"^[\d\s¼½¾⅓⅔/.\-]+$")
    units_only_re = re.compile(rf"^\d+(?:\s*[¼½¾⅓⅔/.\-]\s*\d+)?\s+{units_alt}\b$")

    clean: List[str] = []
    seen = set()

    for raw in items:
        t = re.sub(r"\s+", " ", raw).strip()
        if not t:
            continue
        if bad_pat.search(t):
            continue
        t_low = t.lower()
        if numeric_only_re.match(t_low):
            continue
        if t_low in units_only:
            continue
        if units_only_re.match(t_low):
            continue
        if len(t) > 120 or t_low.startswith((
                "add ", "stir ", "pour ", "heat ", "cook ", "reduce ", "season ",
                "whisk ", "drain ", "bake ", "serve "
        )):
            continue

        if t not in seen:
            seen.add(t)
            clean.append(t)

    return clean

def _parse_calories(cal_str: Optional[str], fallback_text: str, soup: BeautifulSoup) -> Optional[int]:
    # 1) JSON-LD 优先
    if cal_str:
        m = re.search(r"(\d{2,4})", cal_str.replace(",", ""))
        if m:
            return int(m.group(1))

    # 2) 只在 nutrition 区块内找，避免把“15 minutes”当成卡路里
    for sel in ["section.nutrition-section", "[class*='nutrition']", "div#nutrition-section"]:
        node = soup.select_one(sel)
        if not node:
            continue
        t = node.get_text(separator=" ", strip=True)
        m = re.search(r"Calories\s+(\d{2,4})\b", t, flags=re.I)
        if m:
            return int(m.group(1))

    # 3) 兜底：限定在 “Nutrition Facts ... Calories NNN”
    m = re.search(r"Nutrition Facts.*?Calories\s+(\d{2,4})\b", fallback_text, flags=re.I | re.S)
    if m:
        return int(m.group(1))
    return None

def parse_recipe_page(url: str) -> Recipe:
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")

    # 用命名参数
    text_all = soup.get_text(separator=" ", strip=True)

    # —— 优先 JSON-LD —— #
    data = _extract_jsonld_recipe(soup)

    title = None
    servings = None
    ingredients_raw: List[str] = []
    calories = None

    if data:
        title = data.get("name") or data.get("headline")
        servings = _parse_int(data.get("recipeYield"))
        # ✅ 配料优先用 JSON-LD 的 recipeIngredient
        if isinstance(data.get("recipeIngredient"), list):
            ingredients_raw = [i for i in data["recipeIngredient"] if isinstance(i, str) and i.strip()]
        nut = data.get("nutrition") or {}
        # ✅ 调用新版 _parse_calories（带 soup）
        calories = _parse_calories(nut.get("calories"), text_all, soup)

    # —— 回退 DOM —— #
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

    # 组装对象
    ing_objs = []
    for raw in ingredients_raw:
        name = re.sub(r"\s+", " ", raw).strip().lower()
        name = re.sub(r"^\d+([/.\d\s-])*[a-zA-Z]*\s+", "", name)  # 注意这里的 [/.\d\s-] 无需转义点号
        ing_objs.append(Ingredient(name=name, quantity_g=None, meta={"alias_raw": raw}))

    rid = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
    return Recipe(
        id=rid, title=title or "unknown", url=url,
        servings=servings, ingredients=ing_objs,
        meta={"calories_kcal_per_serving": calories}
    )

# ===== 顶层函数：与接口对齐 =====
def scrape_recipes(query: str, top_k: int = 5, _use_cache: bool = True) -> List[Recipe]:
    urls = search_allrecipes(query, top_k=top_k)
    out: List[Recipe] = []
    for u in urls:
        # 抓取（每页小延时）
        time.sleep(random.uniform(0.0, 0.3))
        try:
            r = parse_recipe_page(u)
            out.append(r)
        except Exception:
            continue
    return out