from __future__ import annotations

import argparse
from pathlib import Path

from .classroom import mass_grade_assignment, sync_assignment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ingestion")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="Sync submissions from Google Classroom")
    sync_parser.add_argument("course_id")
    sync_parser.add_argument("course_work_id")
    sync_parser.add_argument("--artifacts-root", default="artifacts")
    sync_parser.add_argument("--credentials", default="credentials.json")
    sync_parser.add_argument("--token", default="token.json")
    sync_parser.add_argument("--force", action="store_true", help="Refresh existing submission artifacts")
    sync_parser.add_argument("--turned-in-only", action="store_true", help="Only sync TURNED_IN submissions")

    grade_parser = subparsers.add_parser("grade", help="Sync and grade submissions from Google Classroom")
    grade_parser.add_argument("course_id")
    grade_parser.add_argument("course_work_id")
    grade_parser.add_argument("--artifacts-root", default="artifacts")
    grade_parser.add_argument("--credentials", default="credentials.json")
    grade_parser.add_argument("--token", default="token.json")
    grade_parser.add_argument("--force-sync", action="store_true")
    grade_parser.add_argument("--force-regrade", action="store_true")
    grade_parser.add_argument("--publish-drafts", action="store_true", help="Write draft grades back to Classroom")
    grade_parser.add_argument("--assign-grades", action="store_true", help="Also set assigned grades")
    grade_parser.add_argument("--return-submissions", action="store_true", help="Return submissions after grade passback")
    grade_parser.add_argument("--turned-in-only", action="store_true")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    states = ["TURNED_IN"] if args.turned_in_only else None
    artifacts_root = Path(args.artifacts_root)
    credentials_path = Path(args.credentials)
    token_path = Path(args.token)

    if args.command == "sync":
        summary = sync_assignment(
            course_id=args.course_id,
            course_work_id=args.course_work_id,
            artifacts_root=artifacts_root,
            credentials_path=credentials_path,
            token_path=token_path,
            force=args.force,
            states=states,
        )
        print(
            f"Imported {summary.imported}, skipped {summary.skipped}, "
            f"downloaded {summary.downloaded_files} file(s)."
        )
        for warning in summary.warnings:
            print(f"WARNING: {warning}")

    if args.command == "grade":
        summary = mass_grade_assignment(
            course_id=args.course_id,
            course_work_id=args.course_work_id,
            artifacts_root=artifacts_root,
            credentials_path=credentials_path,
            token_path=token_path,
            force_sync=args.force_sync,
            force_regrade=args.force_regrade,
            publish_grades=args.publish_drafts or args.assign_grades,
            assign_grades=args.assign_grades,
            return_submissions=args.return_submissions,
            states=states,
        )
        print(
            f"Imported {summary.synced.imported}, skipped {summary.synced.skipped}, "
            f"graded {summary.graded}, failed {summary.failed}, "
            f"published {summary.published}, returned {summary.returned}."
        )
        for warning in summary.warnings:
            print(f"WARNING: {warning}")


if __name__ == "__main__":
    main()
