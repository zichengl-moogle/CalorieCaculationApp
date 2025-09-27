# streamlit run streamlit_app.py
import json
import os
import sys

from runner import run_once  # run_once(query: str, top_k: int = 5)

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
st.session_state.setdefault("page", "home")          # "home" | "waiting" | "results"
st.session_state.setdefault("query", "chicken")
st.session_state.setdefault("results_path", None)
st.session_state.setdefault("results_data", None)

# ---------- Page Setting ----------
st.set_page_config(page_title="Calorie & Cost Finder", page_icon="🥗", layout="centered")

# ---------- Helpers ----------
def _money(x: float) -> str:
    try:
        return f"${x:,.2f}"
    except Exception:
        return "$0.00"

def _fmt_qty(unit: str, qty: float) -> str:
    if unit == "g":
        return f"{qty:.0f} g" if qty >= 1 else f"{qty:.2f} g"
    if unit == "each":
        return f"{qty:.0f} each" if abs(qty - round(qty)) < 1e-6 else f"{qty:.1f} each"
    return f"{qty:g} {unit}"

def _fmt_unit_price(unit: str, p: float) -> str:
    if p <= 0:
        return "N/A"
    return f"{_money(p)}/{unit}"

def _fmt_kcal_per_unit(unit: str, k: float) -> str:
    if k <= 0:
        return "N/A"
    if unit == "g":
        return f"{k:.2f} kcal/g (~{k*100:.0f}/100g)"
    if unit == "each":
        return f"{k:.0f} kcal/each"
    return f"{k:.2f} kcal/{unit}"

def _go_waiting_then_search():
    q = st.session_state["query"].strip()
    if not q:
        st.warning("Please enter a query.")
        return
    st.session_state["page"] = "waiting"
    st.session_state["results_path"] = None
    st.session_state["results_data"] = None
    st.rerun()

# ---------- HOME ----------
if st.session_state["page"] == "home":
    st.title("🥗 Calorie & Cost Finder")

    st.session_state["query"] = st.text_input(
        "Search recipes by dish name",
        value=st.session_state["query"]
    )

    if st.button("Search", type="primary"):
        _go_waiting_then_search()

# ---------- WAITING ----------
elif st.session_state["page"] == "waiting":
    st.title("⏳ Searching & Calculating")
    st.caption("We’ll fetch recipes, prices, and nutrition, then show all results together.")
    placeholder = st.empty()
    with st.spinner("Working..."):
        q = st.session_state["query"]
        # Run the full pipeline (blocking): once finished, return everything at once
        out = run_once(q, top_k=5)
        st.session_state["results_path"] = out if os.path.exists(out) else None
        if st.session_state["results_path"]:
            with open(st.session_state["results_path"], "r", encoding="utf-8") as f:
                st.session_state["results_data"] = json.load(f)
        else:
            st.session_state["results_data"] = None

    st.session_state["page"] = "results"
    st.rerun()

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
            st.markdown(f"### {rec.get('title','(untitled)')}")
            c1, c2 = st.columns(2)
            c1.metric("Per serving kcal", f"{rec.get('per_serving_kcal', 0):.0f} kcal")
            c2.metric("Per serving cost", _money(rec.get('per_serving_cost_usd', 0.0)))
            st.caption(f"Servings: {rec.get('servings', 1)} • Source: {rec.get('url', '')}")

            breakdown = rec.get("breakdown", []) or []
            if breakdown:
                with st.expander("See ingredient breakdown"):
                    for b in breakdown:
                        name = b.get("name", "")
                        unit = b.get("unit", "g")          # "g" or "each"
                        qty = float(b.get("quantity", 0.0))
                        kcal = float(b.get("kcal", 0.0))
                        kpu = float(b.get("kcal_per_unit", 0.0))
                        unit_price = float(b.get("unit_price_usd", 0.0))
                        cost = float(b.get("cost_usd", 0.0))
                        api_unit = b.get("price_unit_from_api", unit)
                        price_note = b.get("price_note")

                        left = f"- **{name}** — {_fmt_qty(unit, qty)}"
                        mid = f" · {kcal:.1f} kcal ({_fmt_kcal_per_unit(unit, kpu)})"
                        right = f" · unit price {_fmt_unit_price(api_unit, unit_price)} · cost {_money(cost)}"
                        st.write(left + mid + right)
                        if price_note:
                            st.caption(f"⚠️ {price_note}")
            st.divider()
