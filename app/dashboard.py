"""Stock Studio dashboard - review and approve. Run:  streamlit run app/dashboard.py"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_studio.analytics.sales import import_sales, performance, update_weights  # noqa: E402
from stock_studio.config import load_settings  # noqa: E402
from stock_studio.export.exporter import PLATFORMS, Exporter, iso_week  # noqa: E402
from stock_studio.models import ADOBE_CATEGORIES, Lane, Status  # noqa: E402
from stock_studio.pipeline import Studio  # noqa: E402
from stock_studio.scout.demand import DemandScout, write_briefs  # noqa: E402

st.set_page_config(page_title="Stock Studio", page_icon="📷", layout="wide")


@st.cache_resource
def studio() -> Studio:
    return Studio(load_settings(ROOT / "config.yaml"))


S = studio()
CATS = list(ADOBE_CATEGORIES)

with st.sidebar:
    st.title("Stock Studio")
    st.caption(f"LLM: **{S.llm.name}** · week **{iso_week()}**")
    counts = S.store.counts()
    for status in Status:
        if counts.get(status.value):
            st.write(f"{status.value.replace('_', ' ')}: **{counts[status.value]}**")
    ex = Exporter(S.settings, S.store)
    for p in PLATFORMS:
        st.progress(1 - ex.remaining(p) / max(1, S.settings.get("export.weekly_cap", 100)),
                    text=f"{p}: {ex.remaining(p)} uploads left this week")

tab_scout, tab_make, tab_review, tab_export, tab_stats, tab_rejected = st.tabs(
    ["Scout", "Produce", "Review", "Export", "Analytics", "Rejected"])

# ------------------------------------------------------------------ scout
with tab_scout:
    st.subheader("What to make this week")
    c1, c2 = st.columns([1, 3])
    n = c1.number_input("Briefs", 4, 40, S.settings.get("scout.briefs_per_week", 12))
    use_llm = c1.checkbox("Expand shot lists with the LLM", value=False, disabled=S.llm.name == "offline")
    if c1.button("Generate briefs", type="primary"):
        briefs = DemandScout(S.settings, S.llm if use_llm else None).weekly_briefs(n=int(n))
        st.session_state["briefs_path"] = str(write_briefs(briefs, S.settings))
        st.session_state["briefs"] = briefs
    for b in st.session_state.get("briefs", []):
        with st.expander(f"{b.topic} · {b.lane} · score {b.score:.2f}"):
            st.caption(b.why)
            if b.upload_by:
                st.write(f"**Upload by:** {b.upload_by}")
            st.markdown("\n".join(f"- {s}" for s in b.shots))
            for p in b.ai_prompts:
                st.code(p, language=None)
    if "briefs_path" in st.session_state:
        st.success(f"Saved to {st.session_state['briefs_path']}")

# ------------------------------------------------------------------ produce
with tab_make:
    st.subheader("Produce")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**My photos**")
        folder = st.text_input("Folder of phone photos/videos")
        topic = st.text_input("Topic (from a brief)")
        if st.button("Ingest folder") and folder:
            from stock_studio.producers.my_photos import ingest_folder
            st.write(ingest_folder(folder, S.settings, S.store, topic=topic))
    with c2:
        st.markdown("**Code vectors**")
        kind = st.selectbox("Kind", ["icons", "patterns", "infographics"])
        count = st.number_input("How many", 1, 30, 4)
        if st.button("Generate vectors"):
            from stock_studio.producers import code_vectors as cv
            fn = {"icons": lambda: cv.make_icon_sets(S.settings, S.store, styles_per_set=1),
                  "patterns": lambda: cv.make_patterns(S.settings, S.store, count=int(count)),
                  "infographics": lambda: cv.make_infographics(S.settings, S.store, count=int(count))}[kind]
            st.write(f"{len(fn())} assets created")
    with c3:
        st.markdown("**AI images** (Gemini Imagen)")
        prompt = st.text_area("Prompt (compliance-checked before sending)")
        if st.button("Generate", disabled=not S.llm.can_generate_images) and prompt:
            from stock_studio.producers.ai_images import generate
            st.write(generate([prompt], S.settings, S.store, S.llm))
        if not S.llm.can_generate_images:
            st.caption("Set LLM_PROVIDER=gemini and GEMINI_API_KEY in .env to enable.")
    st.divider()
    new = len(S.store.list(Status.NEW))
    if st.button(f"Run QC → duplicate guard → metadata on {new} new asset(s)", type="primary", disabled=not new):
        with st.spinner("Checking..."):
            st.write(S.process())


# ------------------------------------------------------------------ review
def show_image(a):
    p = a.raster_path
    if Path(p).exists() and Path(p).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        st.image(p, use_container_width=True)
    if a.is_video:
        st.video(a.path)


with tab_review:
    pending = S.store.list(Status.PENDING_REVIEW)
    lanes = st.multiselect("Lanes", [l.value for l in Lane], default=[l.value for l in Lane])
    pending = [a for a in pending if a.lane.value in lanes]
    st.subheader(f"{len(pending)} waiting for your approval")
    st.caption("Nothing is uploaded automatically. Approved assets go into the next export batch.")
    page = st.number_input("Page", 1, max(1, (len(pending) + 9) // 10), 1) - 1
    for a in pending[page * 10 : page * 10 + 10]:
        with st.container(border=True):
            left, right = st.columns([2, 3])
            with left:
                show_image(a)
                st.caption(f"{a.lane.value} · {a.topic or 'no topic'} · {a.style or ''} · id {a.id}")
                flags = []
                if a.ai_generated:
                    flags.append("🤖 AI-generated")
                if a.fictional:
                    flags.append("people/property fictional")
                if a.needs_release:
                    flags.append("⚠️ needs release")
                st.write(" · ".join(flags) or "no flags")
                for r in a.reasons:
                    st.caption(r)
            with right, st.form(f"f_{a.id}"):
                title = st.text_input("Title", a.title, max_chars=200)
                kw = st.text_area("Keywords (most important first, comma separated)", ", ".join(a.keywords), height=140)
                kws = [k.strip() for k in kw.split(",") if k.strip()]
                st.caption(f"{len(kws)} keywords")
                cat = st.selectbox("Adobe category", CATS, index=CATS.index(a.category) if a.category in CATS else 0,
                                   format_func=lambda c: f"{c} · {ADOBE_CATEGORIES[c]}")
                rel = st.checkbox("Needs model/property release", a.needs_release, disabled=a.lane != Lane.MY_PHOTOS)
                if a.prompt:
                    st.caption(f"Prompt / brief: {a.prompt}")
                b1, b2 = st.columns(2)
                if b1.form_submit_button("✅ Approve", type="primary"):
                    problems = S.approve(a.id, title=title, keywords=kws, category=cat, needs_release=rel)
                    if problems:
                        st.error("Not approved: " + "; ".join(problems))
                    else:
                        st.rerun()
                if b2.form_submit_button("❌ Reject"):
                    S.reject(a.id)
                    st.rerun()

# ------------------------------------------------------------------ export
with tab_export:
    st.subheader("Export upload batches")
    ex = Exporter(S.settings, S.store)
    for p in PLATFORMS:
        st.write(f"**{p}**: {len(ex.candidates(p))} approved and not yet exported · {ex.remaining(p)} left in this week's cap")
    if st.button("Export now", type="primary"):
        for p in PLATFORMS:
            if S.settings.get(f"platforms.{p}.enabled", True):
                r = ex.export(p)
                st.write(f"{p}: {len(r.exported)} exported, {r.deferred} deferred to next week")
                for b in r.batches:
                    st.code(b, language=None)
    st.caption("Each batch has the files, the metadata CSV and CHECKLIST.md (AI and release boxes to tick).")

# ------------------------------------------------------------------ analytics
with tab_stats:
    st.subheader("What sells")
    up = st.file_uploader("Sales / downloads CSV export", type=["csv"])
    plat = st.radio("Platform", PLATFORMS, horizontal=True)
    if up and st.button("Import"):
        dest = S.settings.dir("analytics/imports") / f"{date.today()}_{plat}_{up.name}"
        dest.write_bytes(up.getvalue())
        added, matched = import_sales(dest, plat, S.store)
        st.success(f"{added} new rows, {matched} matched to your assets")
        st.json(update_weights(S.settings, S.store))
    perf = performance(S.store)
    if not perf:
        st.info("Export and sell something first - the report needs exported assets.")
    else:
        for dim in ("lane", "topic", "style"):
            st.markdown(f"**By {dim}** (earnings per asset is the fair comparison)")
            st.dataframe(perf[dim], use_container_width=True)
            if not perf[dim].empty:
                st.bar_chart(perf[dim]["earnings_per_asset"])
        st.markdown("**Top assets**")
        st.dataframe(perf["top_assets"], use_container_width=True)

# ------------------------------------------------------------------ rejected
with tab_rejected:
    rows = []
    for s in (Status.QC_FAILED, Status.DUPLICATE, Status.COMPLIANCE_FAILED, Status.REJECTED):
        rows += [{"id": a.id, "status": s.value, "lane": a.lane.value, "reason": (a.reasons or [""])[0],
                  "file": a.path} for a in S.store.list(s)]
    st.subheader(f"{len(rows)} stopped before review")
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
        rq = st.selectbox("Send one back through the pipeline", [""] + df["id"].tolist())
        if rq and st.button("Requeue"):
            S.requeue(rq)
            st.rerun()
