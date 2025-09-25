# prices_walmart.py
"""
This part implements Walmart pricing here.
REQUIREMENTS:
- Input: dish name (e.g., "Chicken").
- Return: Dict[str, float] mapping canonical ingredient name -> USD per gram.
- Parse Walmart results (price/lb or price/oz or total price + net weight), convert to $/g.
- Robustness: if a price not found, set 0.0 (do not raise).
"""


#implementation 
pip install requests pandas python-dotenv

import re
import json
import requests
import pandas as pd


# Fixed API key & API method
API_KEY = "043b5ae44adbd3774c83f2d925e62080ab6eadceb3fa72cf626fb937b1b40f51"
SEARCH_URL = "https://serpapi.com/search.json"


def check_serpapi_account():
    """Check SerpAPI account info and return remaining searches."""
    url = "https://serpapi.com/account.json"
    try:
        r = requests.get(url, params={"api_key": API_KEY}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def serpapi_walmart_search(query_str, num=1, timeout=15):
    """Call SerpApi Walmart engine and return JSON response."""
    params = {"engine": "walmart", "query": query_str, "api_key": API_KEY, "num": num}
    r = requests.get(SEARCH_URL, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def extract_first_item(resp):
    """Extract the first Walmart item with normalized fields."""
    items = resp.get("products") or resp.get("organic_results") or []
    if not items:
        return None

    it = items[0]
    title = it.get("title")
    price = None
    if isinstance(it.get("primary_offer"), dict):
        price = it["primary_offer"].get("offer_price")
    price = price if price is not None else it.get("price") or it.get("offer_price")

    # Potential unit or weight info
    ppu = it.get("price_per_unit")
    price_per_unit_raw = ppu.get("amount") if isinstance(ppu, dict) else ppu
    size_str = it.get("secondary_offer_text") or it.get("unit") or ""

    link = it.get("product_page_url") or it.get("link")

    return {
        "title": title,
        "price": price,
        "price_per_unit_raw": price_per_unit_raw,
        "size_str": size_str,
        "link": link,
        "rating": it.get("rating"),
        "reviews": it.get("reviews"),
    }


def parse_weight_to_g(text: str) -> float:
    """Parse a weight string (e.g., '1 lb', '16 oz', '500 g') and convert to grams."""
    if not text:
        return 0.0
    text = text.lower()
    match = re.search(r"([\d.]+)\s*(oz|lb|kg|g)", text)
    if not match:
        return 0.0

    num = float(match.group(1))
    unit = match.group(2)

    if unit == "lb":
        return num * 453.592
    elif unit == "oz":
        return num * 28.3495
    elif unit == "kg":
        return num * 1000
    elif unit == "g":
        return num
    return 0.0

# main search method
def search_walmart(ingredient: str):
    """
    Search Walmart for an ingredient and return a dict with price per gram.
    - If weight info is missing, try parsing title or fallback to price_per_unit_raw.
    - If still missing, price_per_g = 0.0.
    """
    try:
        resp = serpapi_walmart_search(ingredient, num=1)
        item = extract_first_item(resp)
        if not item:
            return {"ingredient": ingredient, "price_per_g": 0.0, "note": "no item found"}

        price = item.get("price")
        title = item.get("title") or ""
        size_str = item.get("size_str") or ""

        # parse weight from size_str or title
        weight_g = parse_weight_to_g(size_str) or parse_weight_to_g(title)

        # calculate price per g
        price_per_g = 0.0
        if price and weight_g > 0:
            price_per_g = float(price) / weight_g
        elif price and item.get("price_per_unit_raw"):
            # fallback using price_per_unit_raw (e.g., "39.4 ¢/oz")
            ppu = str(item["price_per_unit_raw"]).lower()
            m = re.match(r"([\d.]+)\s*¢/oz", ppu)
            if m:
                cents_per_oz = float(m.group(1))
                usd_per_oz = cents_per_oz / 100
                price_per_g = usd_per_oz / 28.3495

        return {
            "ingredient": ingredient,
            "product": title,
            "price_usd": price,
            "weight_g": weight_g,
            "price_per_g": price_per_g,
            "rating": item.get("rating"),
            "reviews": item.get("reviews"),
            "link": item.get("link"),
        }

    except Exception as e:
        return {"ingredient": ingredient, "price_per_g": 0.0, "error": str(e)}

"""
--- demo trial ---
if __name__ == "__main__":
    acct_info = check_serpapi_account()
    print(json.dumps(acct_info, indent=2, ensure_ascii=False))

    result = search_walmart("chicken")
    df = pd.DataFrame([result])
    with pd.option_context("display.max_colwidth", 200):
        print(df)
"""
