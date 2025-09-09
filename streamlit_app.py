# streamlit_app.py
import json
import os
from runner import run_once

try:
    import streamlit as st
except ImportError:
    raise SystemExit("Please install Streamlit: pip install streamlit")

st.set_page_config(page_title="Calorie & Cost Finder", page_icon="🥗", layout="centered")
st.title("🥗 Calorie & Cost Finder – Demo")

with st.sidebar:
    st.markdown("**Options**")
    use_cache_gui = st.toggle("Use cache when possible", value=True)
    st.caption("Forwarded to scrapers/APIs if implemented.")

query = st.text_input("Search recipes by dish name", value="chicken")
if st.button("Search"):
    out = run_once(query, top_k=5, use_cache=use_cache_gui)
    st.success(f"Results saved to: {out}")

    if os.path.exists(out):
        with open(out, "r", encoding="utf-8") as f:
            data = json.load(f)
        st.subheader(f"Results for: {query}")
        if not data:
            st.info("No recipes found.")
        else:
            def _money(x: float) -> str:
                return f"${x:,.2f}"

            for rec in data:
                st.markdown(f"### {rec['title']}")
                c1, c2 = st.columns(2)
                c1.metric("Per serving kcal", f"{rec['per_serving_kcal']:.0f} kcal")
                c2.metric("Per serving cost", _money(rec['per_serving_cost_usd']))
                st.caption(f"Servings: {rec['servings']} • Source: {rec['url']}")

                with st.expander("See ingredient breakdown"):
                    for b in rec["breakdown"]:
                        st.write(
                            f"- **{b['name']}** — {b['quantity_g']} g · "
                            f"{b['kcal']:.1f} kcal (~{b['kcal_per_100g']:.0f}/100g) · "
                            f"cost {_money(b['cost_usd'])}"
                        )
                st.divider()