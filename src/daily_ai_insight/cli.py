"""Command-line entry point for reproducible local runs."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from daily_ai_insight.pipeline.prepare import prepare_dataset


def parse_datetime(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise argparse.ArgumentTypeError("datetime must include a timezone")
    return timestamp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daily-ai-insight")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="validate and normalize source data")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--report-date", type=date.fromisoformat, required=True)
    prepare.add_argument("--collected-at", type=parse_datetime, required=True)

    extract = subparsers.add_parser("extract", help="extract one validated insight per item")
    extract.add_argument("--input", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)
    extract.add_argument("--model-runs-dir", type=Path, required=True)
    extract.add_argument("--trace", type=Path, required=True)
    extract.add_argument("--quarantine", type=Path, required=True)
    extract.add_argument("--manifest", type=Path, required=True)
    extract.add_argument(
        "--model",
        help="Pydantic AI model name; defaults to MODEL_NAME from .env",
    )
    extract.add_argument("--extracted-at", type=parse_datetime, required=True)
    extract.add_argument("--project-root", type=Path, default=Path.cwd())
    extract.add_argument(
        "--resume",
        action="store_true",
        help="keep valid outputs and retry only missing or quarantined items",
    )

    cluster = subparsers.add_parser("cluster", help="materialize and rank event clusters")
    cluster.add_argument("--raw", type=Path, required=True)
    cluster.add_argument("--insights", type=Path, required=True)
    cluster.add_argument("--merge-specs", type=Path, required=True)
    cluster.add_argument("--output", type=Path, required=True)
    cluster.add_argument("--manifest", type=Path, required=True)
    cluster.add_argument("--report-date", type=date.fromisoformat, required=True)

    report = subparsers.add_parser("report", help="build JSON, Markdown, HTML, and SVG report")
    report.add_argument("--raw", type=Path, required=True)
    report.add_argument("--insights", type=Path, required=True)
    report.add_argument("--events", type=Path, required=True)
    report.add_argument("--analysis", type=Path, required=True)
    report.add_argument("--output-json", type=Path, required=True)
    report.add_argument("--output-markdown", type=Path, required=True)
    report.add_argument("--output-html", type=Path, required=True)
    report.add_argument("--charts-dir", type=Path, required=True)
    report.add_argument("--manifest", type=Path, required=True)
    report.add_argument("--report-date", type=date.fromisoformat, required=True)
    report.add_argument("--generated-at", type=parse_datetime, required=True)
    report.add_argument("--project-root", type=Path, default=Path.cwd())

    verify = subparsers.add_parser("verify", help="run final evidence and artifact gates")
    verify.add_argument("--raw", type=Path, required=True)
    verify.add_argument("--insights", type=Path, required=True)
    verify.add_argument("--events", type=Path, required=True)
    verify.add_argument("--report-json", type=Path, required=True)
    verify.add_argument("--markdown", type=Path, required=True)
    verify.add_argument("--html", type=Path, required=True)
    verify.add_argument("--chart", type=Path, action="append", required=True)
    verify.add_argument("--output", type=Path, required=True)

    live = subparsers.add_parser(
        "run-live", help="run the complete primary pipeline with a real model"
    )
    live.add_argument("--input", type=Path, required=True)
    live.add_argument("--merge-specs", type=Path, required=True)
    live.add_argument("--report-date", type=date.fromisoformat, required=True)
    live.add_argument("--model", help="defaults to MODEL_NAME from .env")
    live.add_argument("--retry-failures", type=int, default=1)
    live.add_argument("--fresh", action="store_true")
    live.add_argument("--project-root", type=Path, default=Path.cwd())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "prepare":
        manifest = prepare_dataset(
            input_path=args.input,
            output_path=args.output,
            manifest_path=args.manifest,
            report_date=args.report_date,
            collected_at=args.collected_at,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "extract":
        from daily_ai_insight.ai.extractor import build_extraction_agent
        from daily_ai_insight.config import load_project_env
        from daily_ai_insight.pipeline.extract import extract_dataset

        project_root = args.project_root.resolve()
        load_project_env(project_root / ".env")
        model_name = args.model or os.getenv("MODEL_NAME")
        if not model_name:
            raise SystemExit("model is required: pass --model or set MODEL_NAME in .env")
        agent = build_extraction_agent(model_name, project_root)
        manifest = extract_dataset(
            agent=agent,
            input_path=args.input,
            output_path=args.output,
            model_runs_dir=args.model_runs_dir,
            trace_path=args.trace,
            quarantine_path=args.quarantine,
            manifest_path=args.manifest,
            model_name=model_name,
            extracted_at=args.extracted_at,
            resume=args.resume,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "cluster":
        from daily_ai_insight.pipeline.cluster import cluster_dataset

        manifest = cluster_dataset(
            raw_path=args.raw,
            insight_path=args.insights,
            merge_spec_path=args.merge_specs,
            output_path=args.output,
            manifest_path=args.manifest,
            report_date=args.report_date,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "report":
        from daily_ai_insight.reporting.generate import generate_report_artifacts

        manifest = generate_report_artifacts(
            raw_path=args.raw,
            insight_path=args.insights,
            event_path=args.events,
            analysis_path=args.analysis,
            output_json_path=args.output_json,
            output_markdown_path=args.output_markdown,
            output_html_path=args.output_html,
            charts_dir=args.charts_dir,
            manifest_path=args.manifest,
            project_root=args.project_root.resolve(),
            report_date=args.report_date,
            generated_at=args.generated_at,
            manifest_root=args.project_root.resolve(),
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "verify":
        from daily_ai_insight.reporting.verify import verify_report_artifacts

        result = verify_report_artifacts(
            raw_path=args.raw,
            insight_path=args.insights,
            event_path=args.events,
            report_json_path=args.report_json,
            markdown_path=args.markdown,
            html_path=args.html,
            chart_paths=args.chart,
            output_path=args.output,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "run-live":
        from daily_ai_insight.config import load_project_env
        from daily_ai_insight.pipeline.live import run_live_pipeline

        project_root = args.project_root.resolve()
        load_project_env(project_root / ".env")
        model_name = args.model or os.getenv("MODEL_NAME")
        if not model_name:
            raise SystemExit("model is required: pass --model or set MODEL_NAME in .env")
        result = run_live_pipeline(
            project_root=project_root,
            input_path=args.input,
            merge_spec_path=args.merge_specs,
            report_date=args.report_date,
            model_name=model_name,
            retry_failures=args.retry_failures,
            fresh=args.fresh,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
