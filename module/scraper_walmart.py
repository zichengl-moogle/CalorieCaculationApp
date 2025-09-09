# prices_walmart.py
"""
This part implements Walmart pricing here.
REQUIREMENTS:
- Input: dish name (e.g., "Chicken").
- Return: Dict[str, float] mapping canonical ingredient name -> USD per gram.
- Parse Walmart results (price/lb or price/oz or total price + net weight), convert to $/g.
- Robustness: if a price not found, set 0.0 (do not raise).
"""
from typing import Dict
# Change into grams
LB_IN_G = 453.59237
OZ_IN_G = 28.349523125

# ---- DEMO implementation (replace with real logic later) ----

def get_walmart_price_per_g(dish_name: str, use_cache: bool = True) -> Dict[str, float]:
    """
    INPUT:
      - dish_name: str (e.g., "Chicken")
      - use_cache: optional

    OUTPUT (exact): Dict[str, float]
      Example:
        {
          "chicken breast": 0.012,   # USD per gram (≈ $5.44 / lb)
          "green pepper":   0.005,
          "olive oil":      0.010
        }
    """
    demo_prices = {
        "chicken breast": 5.44 / LB_IN_G,   # ~0.012 $/g
        "green pepper": 2.27 / LB_IN_G,     # ~0.005 $/g
        "green chili pepper": 3.50 / LB_IN_G,
        "garlic": 1.99 / LB_IN_G,
        "olive oil": 10.00 / 1000.0,        # assume 1L≈1000g for demo
    }
    return demo_prices


if __name__ == "__main__":
    # Self-test for scraper_walmart.py
    from pprint import pprint

    dish_name = "chicken"
    price_map = get_walmart_price_per_g(dish_name, use_cache=True)

    print(f"[WALMART OK] price map for dish='{dish_name}':")
    for k, v in price_map.items():
        print(f"  {k:20s} -> ${v:.5f} per g")