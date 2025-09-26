#!/usr/bin/env python
# coding: utf-8

# # Nutrionix says we need to attribute them, so we should just add their logo to give them credit or whatever and avoid an academic integrity violation :)
# 
# - https://www.nutritionix.com/

# In[13]:

import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()


app_id = os.getenv("NUTRITIONIX_APP_ID")
api_key = os.getenv("NUTRITIONIX_API_KEY")
api_key = api_key.encode('ascii', 'ignore').decode()


url = "https://trackapi.nutritionix.com/v2/natural/nutrients"


# In[15]:


headers = {
    "x-app-id": app_id,
    "x-app-key": api_key,
    "Content-Type": "application/json"
}


# # Nutrionix uses a Natural Language API, so we do not need to worry too much about the format of the ingredients as long as they are in list format.

# In[16]:


# example input, feel free to delete later

recipe = """Ingredients:
- 6 cups all-purpose flour
- 2 cups cold water divided
- 2 large eggs beaten
- 6 tablespoons canola oil
- 2 teaspoons salt
- 3 ¾ pounds baking potatoes
- 1 medium white onion finely diced
- ⅓ cup salted butter softened, divided
- 4 ½ cups shredded cheddar cheese finely shredded
"""

# recipe is the input string


# In[17]:


recipe_input = []

for line in recipe.split("\n"):
    line = line.strip()
    if line.startswith("-"):
        cleaned = line.lstrip("- ").strip()
        recipe_input.append(cleaned)


# In[18]:

# Query to Nutritionix
query_string = ", ".join(recipe_input)
data = {"query": query_string}

response = requests.post(url, headers=headers, json=data)
foods = response.json().get("foods", [])

# Create dictionary for individual recipe parts and the total recipe

#food breakdown has the individual ingredients
food_breakdown = {}

# totals has the entire recipe
totals = {
    "calories": 0,
    "protein": 0,
    "fat": 0,
    "carbs": 0,
}

for item in foods:
    name = item.get("food_name")
    nutrients = {
        "quantity": item.get("serving_qty"),
        "unit": item.get("serving_unit"),
        "calories": item.get("nf_calories"),
        "protein": item.get("nf_protein"),
        "fat": item.get("nf_total_fat"),
        "carbs": item.get("nf_total_carbohydrate"),
    }

    food_breakdown[name] = nutrients

    for key in totals:
        totals[key] += nutrients.get(key, 0)
