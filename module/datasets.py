"""
===============================================================================
datasets.py — Core data models (Recipe & Ingredient)
===============================================================================

Author: Zicheng Liu (zichengl)
Team Name: Smart Bite
Course: Heinz College — Data Focused Python
Institution: Carnegie Mellon University
Semester: Fall 2025

-------------------------------------------------------------------------------
Purpose:
    Defines the core dataclasses used across the Calorie & Cost Finder project:
        • Ingredient — standardized ingredient representation (in grams)
        • Recipe — structured recipe entity with per-serving context

Design Principles:
    • Consistent internal units (grams) to simplify nutrition and cost math.
    • Type-safe structure using Python dataclasses.
    • Minimal, dependency-free core that other modules (scraper, price, nutrition)
      can import without circular dependencies.

-------------------------------------------------------------------------------
Fields:
    Ingredient:
        - name (str): canonical ingredient name
        - quantity_g (float): mass in grams
        - price_per_g (float): cost per gram (default 0.0)
        - meta (dict): debug or provenance metadata

    Recipe:
        - id (str): stable identifier (hash or composite key)
        - title (str): recipe title
        - url (str): recipe source URL
        - servings (int): number of servings
        - ingredients (List[Ingredient]): all converted to grams

-------------------------------------------------------------------------------
Notes:
    • No external dependencies beyond Python standard library.
    • Conversion from volume/imperial units is handled upstream by scraper modules.
    • Provides a `to_dict()` method for JSON serialization in downstream analysis.

===============================================================================
"""
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