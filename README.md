# Smart Bite

## Team Members
- Zicheng Liu (AndrewID: zichengl)
- Lanshun Yuan (AndrewID: lanshuny)
- Yipeng Sun (AndrewID: yipengs)
- Anastasia Harouse (AndrewID: aharouse)

---

A small Streamlit app that searches real recipes on the web, estimates **nutrition** and **cost**, then shows per-serving stats with an ingredient breakdown.

- **Recipes**: scraped from Allrecipes search results.  
- **Nutrition**: queried from the Nutritionix Natural Language API.  
- **Prices**: first Walmart search result via SerpAPI’s Walmart engine.  

The project emphasizes *pragmatic accuracy* (looks reasonable) and *responsiveness* with simple caching and unit-handling for both **grams (g)** and **each**.

---

## Features

- 🔎 **Search recipes** by dish or keyword.  
- 🧮 **Nutrition per ingredient** and totals:  
  - Supports **kcal/g** and **kcal/each** (eggs, buns, etc.).  
- 💵 **Walmart prices**:  
  - Supports **$/g** and **$/each**, bridges mismatches automatically.  
- 📊 **Per-serving** calories & cost, plus a detailed ingredient breakdown.  
- ⚡ **Caching** (LRU + simple in-process maps) to cut API calls.  
- 🧰 **Debuggable pipeline** with clear module boundaries.  

---

## ⚠️ Performance Notice

Our app relies on the **Walmart engine from SerpAPI**, which is essentially a **third-party web-scraping API** rather than an official Walmart data interface.  
As a result:

- We use a **free-tier API key**, meaning the daily quota is extremely limited — typically **2–3 successful uses of app per day**.  
- Once the quota is exhausted, subsequent price or calorie calculations will **return 0** until the quota resets.  

These limitations reflect the **educational and experimental nature** of the project rather than production-grade reliability.

---
## Project structure

```
module/
  scraper_recipe.py        # Scrapes Allrecipes; parses ingredients & units (g/each)
  nutritionix_client.py    # Nutritionix API client (kcal_per_gram / kcal_per_each)
  prices_walmart.py        # SerpAPI Walmart search -> (price, unit {'g'|'each'})
  knowledgebase.py         # Ingredient alias map (canonical names)
runner.py                  # End-to-end pipeline -> writes data/results_<query>.json
streamlit_app.py           # Streamlit UI
```

---

## Requirements

- Python 3.9+  
- pip packages (see below)  

### Install

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt  
```

> `lxml` is required for robust HTML parsing of the Allrecipes search page.

---

## Environment variables

Create a `.env` file in the project root:

```env
# Nutritionix
NUTRITIONIX_APP_ID=your_app_id
NUTRITIONIX_API_KEY=your_api_key

# SerpAPI (Walmart engine)
SERPAPI_API_KEY=your_serpapi_key
```

**Important:**  
- Make sure your keys only contain plain ASCII; remove any stray non-ASCII characters if you copied from a portal.  
- Nutritionix requires attribution; this app credits them in the UI/docs.  

---

## How it works (high level)

1. **Scrape recipes**  
   - `scraper_recipe.scrape_recipes(query, top_k)` fetches top recipe URLs from Allrecipes search and parses each recipe page.  
   - For every ingredient it tries to parse:  
     - `quantity_g` (if measurable in mass or convertible from volume), or  
     - `each_count` (for *“3 eggs”*, *“1 bun”*), stored in `Ingredient.meta`.  

2. **Fetch nutrition**  
   - `nutritionix_client.kcal_per_gram(name)` and `nutritionix_client.kcal_per_each(name)` call Nutritionix API.  
   - If only one is available, infer `grams_per_each = kcal_per_each / kcal_per_gram`.  

3. **Fetch prices**  
   - `prices_walmart.search_walmart(name)` returns `(price, unit)` where unit is `'g'` or `'each'`.  
   - The runner bridges mismatches using `grams_per_each`.  

4. **Compute totals**  
   - `runner.compute_recipe_energy_and_cost` aggregates kcal & cost, plus per-serving values.  

5. **Show in the app**  
   - `streamlit_app.py` runs the pipeline and renders the results.  

---

## Run it

### Streamlit app

```bash
streamlit run streamlit_app.py
```

- Type a query like “chicken”, hit **Search**.  
- The app shows a waiting screen while scraping/APIs run, then renders results.  
- Expand a recipe to see ingredient-level details.  

---

## Units & conversions

- **Mass units**: `g`, `kg`, `oz`, `lb` (all normalized to grams).  
- **Volume units**: `cup`, `tbsp`, `tsp`, `ml`, `l` (converted using density rules where available).  
- **Each**: Items expressed as pieces (eggs, buns, cloves, etc.) are preserved as `each`.  
  - Calories can be `kcal/each`.  
  - Prices can be `$/each`.  
  - When needed, the pipeline bridges `each ↔ g`.  

The UI shows a note when a **price unit mismatch** had to be bridged.  

---

## Caching

- `nutritionix_client` uses `functools.lru_cache`.  
- `runner.py` keeps small in-process dict caches for prices/nutrition during one run.  
- Restarting clears caches.  

---

## Configuration tips

- **Top-K recipes**: Tune `runner.run_once(query, top_k=5)` for speed vs. variety.  
- **Parallelism**: Currently serial; for speed, parallelize scraping & API calls.  

---

## Troubleshooting

- **`FeatureNotFound: lxml`** → install `lxml` (`pip install lxml`).  
- **Nutritionix errors** → check `.env` values and ensure no stray characters.  
- **0 prices** → Walmart results may miss size; runner bridges via `grams_per_each` if possible.  
- **Odd ingredient parsing** → handled conservatively; e.g., “1 (8 pound) pork shoulder roast” parsed via parenthetical unit.  

---

## Acknowledgements

- **Nutritionix** – Nutrition data API.  
  https://www.nutritionix.com/  
- **SerpAPI** – Walmart search API.  
  https://serpapi.com/  

This project is for **educational/demo use only**.  

---

## License

MIT (feel free to adapt).
