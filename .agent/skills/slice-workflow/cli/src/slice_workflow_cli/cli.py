"""Argparse entrypoint for the skill-local slice workflow CLI."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .checks import ContractCheckError, run_check, run_sync_check
from .output import log_error
from .plan import PlanCreateError, run_plan
from .workflow import (
    SliceWorkflowError,
    inspect_status,
    print_render_result,
    print_status,
    render_phase_prompt,
)


def repo_root(raw_root: str | None) -> Path:
    candidate = raw_root or os.environ.get("MISE_PROJECT_ROOT") or str(Path.cwd())
    return Path(candidate).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slice-workflow",
        description="Skill-local CLI for planning, prompt rendering, and slice checks.",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Repository root. Defaults to MISE_PROJECT_ROOT or current directory.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Create a new plan directory")
    plan_parser.add_argument("slug", help="lowercase hyphenated plan slug")

    for name in ("plan-check", "spec-check", "evidence-check", "review-check"):
        check_parser = subparsers.add_parser(name, help=f"Run {name}")
        check_parser.add_argument("--plan-dir", default=None)

    sync_parser = subparsers.add_parser("sync-check", help="Run all handoff checks")
    group = sync_parser.add_mutually_exclusive_group()
    group.add_argument("--plan-dir", default=None)
    group.add_argument("--changed-plans", default=None)
    group.add_argument("--changed-hk-exports", default=None)
    group.add_argument("--hk-exports-only", action="store_true")

    render_parser = subparsers.add_parser("render", help="Render a slice prompt")
    render_parser.add_argument("phase", choices=["planner", "implementer", "reviewer"])
    render_parser.add_argument("--plan-dir", default=None)
    render_parser.add_argument("--task", default=None)
    render_parser.add_argument("--task-text", default=None)
    render_parser.add_argument("--print", action="store_true", dest="print_prompt")
    render_parser.add_argument("--json", action="store_true", dest="json_output")

    status_parser = subparsers.add_parser("status", help="Show active slice status")
    status_parser.add_argument("--plan-dir", default=None)
    status_parser.add_argument("--json", action="store_true", dest="json_output")

    return parser


def run(args: argparse.Namespace) -> int:
    root = repo_root(args.repo)
    command = args.command

    if command == "plan":
        return run_plan(root, args.slug)
    if command in {"plan-check", "spec-check", "evidence-check", "review-check"}:
        return run_check(root, command, plan_dir=args.plan_dir)
    if command == "sync-check":
        return run_sync_check(
            root,
            plan_dir=args.plan_dir,
            changed_plans=args.changed_plans,
            changed_hk_exports=args.changed_hk_exports,
            hk_exports_only=args.hk_exports_only,
        )
    if command == "render":
        result = render_phase_prompt(
            root=root,
            phase=args.phase,
            plan_arg=args.plan_dir,
            task=args.task,
            task_text=args.task_text,
            print_prompt=args.print_prompt,
        )
        print_render_result(result, json_output=args.json_output)
        return 0
    if command == "status":
        status = inspect_status(root=root, plan_arg=args.plan_dir)
        print_status(status, json_output=args.json_output)
        return 0

    raise SliceWorkflowError(f"Unknown command: {command}")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        raise SystemExit(run(args))
    except (ContractCheckError, PlanCreateError, SliceWorkflowError) as e:
        log_error(str(e))
        raise SystemExit(1) from e
    except KeyboardInterrupt:
        log_error("Interrupted")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main(sys.argv[1:])
