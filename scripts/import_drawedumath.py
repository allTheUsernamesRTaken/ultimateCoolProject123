from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from artifact_io import write_grading_result
from schemas import CriterionScore, GradingResult, TopicTag


DATASET_CSV_URL = (
    "https://huggingface.co/datasets/Heffernan-WPI-Lab/DrawEduMath/"
    "resolve/main/Data/DrawEduMath_QA.csv"
)

OUTPUT_PREFIX = "drawedumath"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate GradingResult fixtures from a small DrawEduMath sample."
    )
    parser.add_argument("--limit", type=int, default=12, help="Number of rows to import.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts"),
        help="Artifact root that contains grading/.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing drawedumath_*.json grading fixtures before import.",
    )
    parser.add_argument(
        "--csv-url",
        default=DATASET_CSV_URL,
        help="Raw DrawEduMath CSV URL.",
    )
    return parser.parse_args()


def normalize_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return cleaned[:72] or "criterion"


def parse_json_list(value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def score_answer(answer: str) -> float:
    text = answer.lower()
    negative_markers = [
        "incorrect",
        "not correct",
        "not labeled",
        "not use",
        "did not",
        "no,",
        " no.",
        "missing",
    ]
    partial_markers = ["partial", "some", "mostly", "with errors", "unclear"]

    if any(marker in text for marker in negative_markers):
        return 0.8
    if any(marker in text for marker in partial_markers):
        return 1.5
    if "correct" in text or text.strip().lower() in {"yes", "accurate"}:
        return 2.5
    return 2.0 if len(answer.strip()) > 30 else 1.8


def topics_for_question(question: str) -> list[TopicTag]:
    text = question.lower()
    topics: list[TopicTag] = []
    if any(word in text for word in ["label", "tick", "number line", "axis"]):
        topics.append(TopicTag.NOTATION)
    if any(word in text for word in ["arrow", "sum", "add", "subtract", "operation"]):
        topics.append(TopicTag.PROCEDURE)
    if any(word in text for word in ["answer", "value", "solution"]):
        topics.append(TopicTag.CONCEPTUAL_UNDERSTANDING)
    if any(word in text for word in ["explain", "represent", "show", "model"]):
        topics.append(TopicTag.MATHEMATICAL_REASONING)
    return topics or [TopicTag.MATHEMATICAL_REASONING]


def row_to_result(row: dict[str, str], index: int) -> GradingResult:
    problem_id = row["Problem ID"].strip()
    image_name = row["Image Name"].strip()
    image_caption = row.get("Image Caption", "").strip()
    teacher_qa = parse_json_list(row.get("QA Teacher", ""))

    selected_qa = teacher_qa[:4]
    if not selected_qa:
        selected_qa = [
            {
                "question": "Does the visual response contain enough evidence to review?",
                "answer": image_caption or "No caption was available.",
            }
        ]

    max_points_per_item = 10 / len(selected_qa)
    rubric: list[CriterionScore] = []
    topic_set: set[TopicTag] = set()

    for item in selected_qa:
        question = str(item.get("question", "Teacher QA criterion")).strip()
        answer = str(item.get("answer", "")).strip()
        scaled_points = round((score_answer(answer) / 2.5) * max_points_per_item, 2)
        criterion_topics = topics_for_question(question)
        topic_set.update(criterion_topics)
        rubric.append(
            CriterionScore(
                criterion_id=normalize_id(question),
                points=scaled_points,
                max_points=max_points_per_item,
                concept_tags=criterion_topics,
                feedback=answer or "No teacher QA answer was provided.",
                confidence=0.86,
            )
        )

    score = round(sum(item.points for item in rubric), 2)
    topics = sorted(topic_set, key=lambda topic: topic.value)
    preview = image_caption[:220] + ("..." if len(image_caption) > 220 else "")

    return GradingResult(
        submission_id=f"{OUTPUT_PREFIX}_{problem_id}_{index:03d}",
        assignment_id=f"drawedumath_problem_{problem_id}",
        score=score,
        max_score=10,
        rubric_breakdown=rubric,
        feedback=(
            "Dataset-backed review fixture from DrawEduMath. "
            f"Teacher QA was converted into rubric feedback for image {image_name}. "
            f"Caption evidence: {preview}"
        ),
        topics=topics,
        confidence=0.86,
        needs_review=False,
    )


def fetch_rows(csv_url: str, limit: int) -> list[dict[str, str]]:
    with urllib.request.urlopen(csv_url, timeout=90) as response:
        text = response.read().decode("utf-8", errors="replace")
    reader = csv.DictReader(text.splitlines())
    rows: list[dict[str, str]] = []
    for row in reader:
        if row.get("Problem ID") and row.get("Image Name"):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def main() -> None:
    args = parse_args()
    grading_dir = args.output_root / "grading"
    grading_dir.mkdir(parents=True, exist_ok=True)

    if args.replace:
        for path in grading_dir.glob(f"{OUTPUT_PREFIX}_*.json"):
            path.unlink()

    rows = fetch_rows(args.csv_url, args.limit)
    for index, row in enumerate(rows, start=1):
        write_grading_result(row_to_result(row, index), root=args.output_root)

    print(f"Imported {len(rows)} DrawEduMath grading fixtures into {grading_dir}.")


if __name__ == "__main__":
    main()
