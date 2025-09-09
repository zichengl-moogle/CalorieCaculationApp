# datasets.py
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class Ingredient:
    """
    Ingredient model (INTERNAL UNITS: grams)
    - name: canonical or normalized ingredient name (lowercase English preferred)
    - quantity_g: float, GRAMS (you MUST convert from cup/oz/lb/tbsp into grams upstream)
    - price_per_g: float, USD per gram (filled by Walmart pricing; default 0.0 if unknown)
    - meta: free-form provenance/debug info (e.g., raw alias, candidates, source url)
    """
    name: str
    quantity_g: float
    price_per_g: float = 0.0
    meta: Dict = field(default_factory=dict)

@dataclass
class Recipe:
    """
    Recipe model.
    - id: stable identifier (e.g., 'site-key:hash(url)') – must be reproducible
    - title: recipe title
    - url: source url
    - servings: positive integer
    - ingredients: list[Ingredient] (ALL in grams)
    """
    id: str
    title: str
    url: str
    servings: int
    ingredients: List[Ingredient]

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "servings": self.servings,
            "ingredients": [
                {
                    "name": i.name,
                    "quantity_g": i.quantity_g,
                    "price_per_g": i.price_per_g,
                    "meta": i.meta,
                }
                for i in self.ingredients
            ],
        }