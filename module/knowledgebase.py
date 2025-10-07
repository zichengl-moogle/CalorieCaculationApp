"""
===============================================================================
knowledgebase.py — Ingredient synonym dictionary
===============================================================================

Author: Zicheng Liu (zichengl)
Team Name: Smart Bite
Course: Heinz College — Data Focused Python
Institution: Carnegie Mellon University
Semester: Fall 2025

-------------------------------------------------------------------------------
Purpose:
    Centralizes ingredient name normalization across all data sources
    (recipes, Walmart prices, and Nutritionix nutrition data).
    Provides a consistent mapping of alternate or regional ingredient names
    to canonical English terms used throughout the system.

-------------------------------------------------------------------------------
Contents:
    • SYNONYMS — a dictionary mapping alias → canonical form.
        Example:  "scallions" → "green onion"
                  "aubergine" → "eggplant"
                  "yoghurt"   → "yogurt"

    • CANONICAL_PREFERENCES — a reference set of standardized names
      that represent preferred spellings within this project.

-------------------------------------------------------------------------------
Design Principles:
    • Keep mappings one-directional (alias → canonical).
    • No typo or fuzzy handling; only legitimate linguistic / regional variants.
    • All keys and values are lowercase for consistency.
    • Used by the Nutritionix and recipe modules for normalization.

-------------------------------------------------------------------------------
Notes:
    • This module has no dependencies and may be safely imported anywhere.
    • Add new entries here when encountering alternative ingredient terms.

===============================================================================
"""

SYNONYMS = {
    # onions & herbs
    "scallion": "green onion",
    "scallions": "green onion",
    "spring onion": "green onion",
    "spring onions": "green onion",
    "coriander": "cilantro",
    "fresh coriander": "cilantro",
    "italian parsley": "parsley",
    "flat leaf parsley": "parsley",
    "curly parsley": "parsley",

    # peppers & chilies
    "bell pepper": "pepper",
    "bell peppers": "pepper",
    "capsicum": "pepper",
    "green bell pepper": "green pepper",
    "red bell pepper": "red pepper",
    "yellow bell pepper": "yellow pepper",
    "chili": "chili pepper",
    "chilli": "chili pepper",
    "chiles": "chili pepper",
    "chilies": "chili pepper",
    "thai chile": "thai chili",
    "thai chilli": "thai chili",
    "jalapeño": "jalapeno",
    "jalapeno pepper": "jalapeno",

    # eggplant & zucchini (UK vs US)
    "aubergine": "eggplant",
    "courgette": "zucchini",

    # beans & legumes
    "garbanzo bean": "chickpea",
    "garbanzo beans": "chickpea",
    "chickpeas": "chickpea",
    "black beans": "black bean",
    "kidney beans": "kidney bean",
    "soy beans": "soybean",
    "soybeans": "soybean",
    "edamame": "soybean",

    # dairy
    "yoghurt": "yogurt",
    "whole milk yogurt": "yogurt",
    "greek yoghurt": "greek yogurt",
    "double cream": "heavy cream",
    "whipping cream": "heavy cream",
    "single cream": "light cream",
    "half and half": "half-and-half",

    # sugars & baking
    "caster sugar": "granulated sugar",
    "superfine sugar": "granulated sugar",
    "confectioners sugar": "powdered sugar",
    "icing sugar": "powdered sugar",
    "dark brown sugar": "brown sugar",
    "light brown sugar": "brown sugar",
    "bicarbonate of soda": "baking soda",
    "bicarbonate": "baking soda",
    "bi-carb": "baking soda",
    "cornflour": "cornstarch",

    # flours & grains
    "plain flour": "all-purpose flour",
    "strong flour": "bread flour",
    "wholemeal flour": "whole wheat flour",
    "maize": "corn",
    "sweetcorn": "corn",
    "polenta": "cornmeal",
    "oatmeal": "rolled oats",

    # oils
    "veg oil": "vegetable oil",
    "rapeseed oil": "canola oil",
    "groundnut oil": "peanut oil",

    # meats & seafood
    "minced beef": "ground beef",
    "beef mince": "ground beef",
    "minced pork": "ground pork",
    "pork mince": "ground pork",
    "minced chicken": "ground chicken",
    "prawns": "shrimp",
    "king prawn": "shrimp",
    "tiger prawn": "shrimp",
    "brisket point": "beef brisket",
    "brisket flat": "beef brisket",

    # greens & leaves
    "rocket": "arugula",
    "corn salad": "mache",
    "lambs lettuce": "mache",
    "beetroot": "beet",
    "scallop squash": "pattypan squash",

    # vinegars & condiments
    "distilled vinegar": "white vinegar",
    "malt vinegar": "barley vinegar",
    "catsup": "ketchup",

    # misc
    "brown rice syrup": "rice syrup",
    "molasses": "blackstrap molasses",
}

# Optionally: some canonical names we prefer (lowercase).
# Not required by the code, but helpful as documentation.
CANONICAL_PREFERENCES = {
    "pepper", "green pepper", "red pepper", "yellow pepper",
    "chili pepper", "thai chili", "jalapeno",
    "green onion", "onion", "garlic", "shallot",
    "cilantro", "parsley", "basil", "mint", "dill",
    "eggplant", "zucchini", "tomato", "potato", "carrot", "celery", "spinach",
    "broccoli", "cauliflower", "cabbage", "kale", "lettuce",
    "chickpea", "black bean", "kidney bean", "soybean", "lentil",
    "yogurt", "greek yogurt", "heavy cream", "light cream", "half-and-half",
    "granulated sugar", "powdered sugar", "brown sugar",
    "baking soda", "cornstarch",
    "all-purpose flour", "bread flour", "whole wheat flour", "cornmeal", "rolled oats",
    "olive oil", "vegetable oil", "canola oil", "peanut oil",
    "ground beef", "ground pork", "ground chicken", "shrimp", "beef brisket",
    "arugula", "mache", "beet",
    "white vinegar", "balsamic vinegar", "rice vinegar", "ketchup",
}
