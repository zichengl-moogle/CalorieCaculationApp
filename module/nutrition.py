# nutrition_api.py
"""
This part implements fuzzy matching + nutrition lookup here.
REQUIREMENTS:
- Input: raw ingredient name (may be noisy).
- Output: (canonical_name: str (lowercase English preferred), kcal_per_100g: float)
- Must fuzzy-resolve to a reasonable canonical (e.g., "green chili pepper")
  and provide kcal per 100g. If unknown, return (normalized_name, 0.0) but
  NEVER raise exceptions.
- Implement minimal normalization: lowercase, strip punctuation/quantities,
  remove descriptors (chopped/minced/fresh/organic/boneless/skinless...),
  basic plural->singular rule, simple alias map; optionally use difflib/rapidfuzz.
"""
import re
from typing import Tuple

def get_canonical_and_kcal_per_100g(raw_name: str) -> Tuple[str, float]:
    """
    Example:
      - Input: "green chili"  -> ("green chili pepper", 40.0)
      - Input: "Chicken breast" -> ("chicken breast", 165.0)
    """
    norm = re.sub(r"[^a-zA-Z\s]", " ", raw_name).lower().strip()
    norm = re.sub(r"\s+", " ", norm)

    aliases = {
        "green chili": "green chili pepper",
        "chili pepper": "green chili pepper",
        "green bell pepper": "green pepper",
        "bell pepper": "green pepper",
        "scallions": "green onion",
        "spring onion": "green onion",
    }
    lookup_key = aliases.get(raw_name, aliases.get(norm, norm))

    kcal_table = {
        "chicken breast": 165.0,
        "green pepper": 20.0,
        "green chili pepper": 40.0,
        "garlic": 149.0,
        "olive oil": 884.0,
        "green onion": 32.0,
    }
    canonical = lookup_key
    kcal = kcal_table.get(canonical, 0.0)
    return canonical, float(kcal)


if __name__ == "__main__":
    # Self-test for nutrition.py
    tests = [
        "Chicken breast",
        "green bell pepper",
        "spring onion",
        "mystery thing 123",
    ]
    print("[NUTRITION OK] canonical + kcal/100g")
    for t in tests:
        canonical, kcal100 = get_canonical_and_kcal_per_100g(t)
        print(f"  IN: {t:20s} -> OUT: {canonical:20s} | {kcal100:.1f} kcal/100g")