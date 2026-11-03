"""Command line: python -m stock_studio <command>."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .config import load_settings


def _studio(args):
    from .pipeline import Studio
    return Studio(load_settings(args.config))


def cmd_scout(args):
    from .scout.demand import DemandScout, write_briefs
    st = _studio(args)
    briefs = DemandScout(st.settings, st.llm if args.llm else None).weekly_briefs(n=args.n)
    path = write_briefs(briefs, st.settings)
    for b in briefs:
        print(f"{b.score:5.2f}  {b.lane:13s} {b.topic}")
    print(f"\nBriefs written to {path} and {path.with_suffix('.md')}")


def cmd_photos(args):
    from .producers.my_photos import ingest_folder
    st = _studio(args)
    print(asdict(ingest_folder(args.folder, st.settings, st.store, topic=args.topic)))


def cmd_vectors(args):
    from .producers import code_vectors as cv
    st = _studio(args)
    made = []
    if args.kind in ("icons", "all"):
        made += cv.make_icon_sets(st.settings, st.store, sets=args.sets, styles_per_set=args.styles, seed=args.seed)
    if args.kind in ("patterns", "all"):
        made += cv.make_patterns(st.settings, st.store, count=args.count, seed=args.seed)
    if args.kind in ("infographics", "all"):
        made += cv.make_infographics(st.settings, st.store, count=args.count, seed=args.seed)
    print(f"{len(made)} vector assets ready (status: {', '.join(sorted({a.status.value for a in made}))})")


def cmd_ai(args):
    from .producers.ai_images import generate
    from .scout.demand import load_briefs
    st = _studio(args)
    prompts, topic = list(args.prompt or []), args.topic
    if args.brief:
        for b in load_briefs(Path(args.brief)):
            if b.lane == "ai_images" and (not args.only or args.only in b.id):
                prompts += b.ai_prompts
                topic = topic or b.topic
    if not prompts:
        sys.exit("No prompts. Use --prompt '...' or --brief workspace/briefs/<week>.json")
    rep = generate(prompts, st.settings, st.store, st.llm, topic=topic or "", aspect_ratio=args.aspect)
    print(f"generated {len(rep.generated)}, blocked {len(rep.blocked)}, failed {len(rep.failed)}")
    for p, why in rep.blocked:
        print(f"  BLOCKED: {p[:70]}... -> {why}")
    for p, err in rep.failed:
        print(f"  FAILED: {p[:70]}... -> {err}")


def cmd_process(args):
    st = _studio(args)
    print(f"LLM: {st.llm.name}   embedder: {st.embedder.name}")
    print(asdict(st.process(limit=args.limit)))
    print("Review and approve in the dashboard:  streamlit run app/dashboard.py")


def cmd_history(args):
    st = _studio(args)
    print(f"indexed {st.guard().index_history(args.folder)} previously uploaded files")


def cmd_export(args):
    from .export.exporter import PLATFORMS, Exporter
    st = _studio(args)
    ex = Exporter(st.settings, st.store)
    for p in (PLATFORMS if args.platform == "both" else [args.platform]):
        if not st.settings.get(f"platforms.{p}.enabled", True):
            continue
        r = ex.export(p)
        print(f"{p}: exported {len(r.exported)} into {len(r.batches)} batch(es); "
              f"{r.deferred} wait for next week; {r.remaining_cap} left in {r.week}'s cap")
        for b in r.batches:
            print(f"   {b}")
        for aid, err in r.errors:
            print(f"   ERROR {aid}: {err}")


def cmd_sales(args):
    from .analytics.sales import import_sales, update_weights
    st = _studio(args)
    mapping = dict(m.split("=", 1) for m in args.map or [])
    added, matched = import_sales(args.csv, args.platform, st.store, mapping)
    print(f"imported {added} new sale rows ({matched} matched to assets)")
    print("weights:", json.dumps(update_weights(st.settings, st.store), indent=2))


def cmd_report(args):
    from .analytics.sales import performance
    st = _studio(args)
    perf = performance(st.store)
    if not perf:
        print("No exported assets yet.")
        return
    for dim in ("lane", "topic", "style"):
        print(f"\n== by {dim} ==\n{perf[dim].to_string()}")


def cmd_status(args):
    st = _studio(args)
    print(json.dumps(st.store.counts(), indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stock-studio", description=__doc__)
    ap.add_argument("--config", default=None, help="path to config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scout", help="suggest this week's topics and write briefs")
    s.add_argument("-n", type=int, default=None)
    s.add_argument("--llm", action="store_true", help="let the LLM expand shot lists")
    s.set_defaults(fn=cmd_scout)

    s = sub.add_parser("photos", help="ingest a folder of your phone photos/videos")
    s.add_argument("folder")
    s.add_argument("--topic", default="")
    s.set_defaults(fn=cmd_photos)

    s = sub.add_parser("vectors", help="generate icon sets, patterns, infographic templates")
    s.add_argument("kind", choices=["icons", "patterns", "infographics", "all"])
    s.add_argument("--sets", nargs="*", help="icon sets (business, technology, ecology, travel, festival, food, health_education)")
    s.add_argument("--styles", type=int, default=1, help="styles per icon set")
    s.add_argument("--count", type=int, default=6)
    s.add_argument("--seed", type=int, default=None)
    s.set_defaults(fn=cmd_vectors)

    s = sub.add_parser("ai", help="generate AI images from compliance-checked prompts (Gemini Imagen)")
    s.add_argument("--prompt", action="append")
    s.add_argument("--brief", help="briefs JSON from `scout`")
    s.add_argument("--only", help="only briefs whose id contains this")
    s.add_argument("--topic", default="")
    s.add_argument("--aspect", default="4:3")
    s.set_defaults(fn=cmd_ai)

    s = sub.add_parser("process", help="run QC, duplicate guard and metadata on new assets")
    s.add_argument("--limit", type=int, default=None)
    s.set_defaults(fn=cmd_process)

    s = sub.add_parser("history", help="index files you've already uploaded for the duplicate guard")
    s.add_argument("folder")
    s.set_defaults(fn=cmd_history)

    s = sub.add_parser("export", help="export approved assets into upload batches")
    s.add_argument("--platform", choices=["adobe", "freepik", "both"], default="both")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("sales", help="import a sales/download CSV and update scout weights")
    s.add_argument("csv")
    s.add_argument("--platform", choices=["adobe", "freepik"], required=True)
    s.add_argument("--map", nargs="*", help="field=Column overrides, e.g. earnings='Royalty USD'")
    s.set_defaults(fn=cmd_sales)

    sub.add_parser("report", help="earnings by lane/topic/style").set_defaults(fn=cmd_report)
    sub.add_parser("status", help="asset counts by status").set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
