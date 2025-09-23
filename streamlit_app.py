# streamlit run streamlit_app.py
import json
import os
from runner import run_once

import sys
import os

def _is_streamlit_runtime() -> bool:
    try:
        import streamlit.runtime as rt  # type: ignore
        return getattr(rt, "exists", lambda: False)()
    except Exception:
        return any(k in os.environ for k in ["STREAMLIT_SERVER_PORT", "STREAMLIT_BROWSER_GATHER_USAGE_STATS"])

if not _is_streamlit_runtime():
    sys.stderr.write(
        "This script must be run with Streamlit.\n"
        "Try:  streamlit run streamlit_app.py\n"
    )
    sys.exit(1)

try:
    import streamlit as st
except ImportError:
    raise SystemExit("Please install Streamlit: pip install streamlit")

# ---------- Initialize session_state ----------
st.session_state.setdefault("page", "home")          # "home" | "results"
st.session_state.setdefault("query", "chicken")
st.session_state.setdefault("use_cache", True)
st.session_state.setdefault("results_path", None)
st.session_state.setdefault("results_data", None)

# ---------- Page Setting ----------
st.set_page_config(page_title="Calorie & Cost Finder", page_icon="🥗", layout="centered")

# ---------- Sidebar ----------
with st.sidebar:
    st.markdown("**Options**")
    st.session_state["use_cache"] = st.toggle(
        "Use cache when possible",
        value=st.session_state["use_cache"]
    )
    st.caption("Forwarded to scrapers/APIs if implemented.")

# ---------- Helper ----------
def _money(x: float) -> str:
    return f"${x:,.2f}"

def _run_search_and_go_results():
    q = st.session_state["query"]
    out = run_once(q, top_k=5, use_cache=st.session_state["use_cache"])
    st.session_state["results_path"] = out if os.path.exists(out) else None
    if st.session_state["results_path"]:
        with open(st.session_state["results_path"], "r", encoding="utf-8") as f:
            st.session_state["results_data"] = json.load(f)
    else:
        st.session_state["results_data"] = None
    st.session_state["page"] = "results"
    st.rerun()

# ---------- HOME ----------
if st.session_state["page"] == "home":
    st.title("🥗 Calorie & Cost Finder")

    st.session_state["query"] = st.text_input(
        "Search recipes by dish name",
        value=st.session_state["query"]
    )

    if st.button("Search", type="primary"):
        _run_search_and_go_results()

# ---------- RESULTS ----------
elif st.session_state["page"] == "results":
    cols = st.columns([1, 3])
    with cols[0]:
        if st.button("← Back", use_container_width=True):
            st.session_state["page"] = "home"
            st.rerun()

    st.title(f"🥗 Results for: {st.session_state['query']}")

    data = st.session_state["results_data"]

    if data is None:
        st.warning("No results file generated. Please go back and try again.")
    elif not data:
        st.info("No recipes found.")
    else:
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

