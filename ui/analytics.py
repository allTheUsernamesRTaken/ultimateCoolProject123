from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from schemas import GradingResult


@dataclass(frozen=True)
class TopicSummary:
    assignment_id: str
    topic: str
    average_percent: float
    student_count: int


@dataclass(frozen=True)
class WeakTopicFlag:
    assignment_id: str
    topic: str
    average_percent: float
    student_count: int
    cutoff_percent: float


def load_grading_results(grading_dir: Path) -> list[tuple[Path, GradingResult]]:
    if not grading_dir.exists():
        return []

    results: list[tuple[Path, GradingResult]] = []
    for path in sorted(grading_dir.glob("*.json")):
        result = GradingResult.model_validate_json(path.read_text(encoding="utf-8"))
        results.append((path, result))
    return results


def summarize_topics(results: list[GradingResult]) -> list[TopicSummary]:
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for result in results:
        for topic in sorted(set(result.topics)):
            buckets[(result.assignment_id, topic)].append(result.percent)

    summaries = [
        TopicSummary(
            assignment_id=assignment_id,
            topic=topic,
            average_percent=sum(scores) / len(scores),
            student_count=len(scores),
        )
        for (assignment_id, topic), scores in buckets.items()
    ]
    return sorted(summaries, key=lambda item: (item.assignment_id, item.topic))


def weak_topic_flags(
    summaries: list[TopicSummary],
    cutoff_percent: float,
    min_students: int,
) -> list[WeakTopicFlag]:
    return [
        WeakTopicFlag(
            assignment_id=summary.assignment_id,
            topic=summary.topic,
            average_percent=summary.average_percent,
            student_count=summary.student_count,
            cutoff_percent=cutoff_percent,
        )
        for summary in summaries
        if summary.student_count >= min_students
        and summary.average_percent < cutoff_percent
    ]


def score_bins(results: list[GradingResult], bin_size: int = 10) -> dict[str, int]:
    bins = {f"{start}-{start + bin_size - 1}%": 0 for start in range(0, 100, bin_size)}
    bins["100%"] = 0

    for result in results:
        percent = round(result.percent * 100, 2)
        if percent >= 100:
            bins["100%"] += 1
            continue
        start = int(percent // bin_size) * bin_size
        bins[f"{start}-{start + bin_size - 1}%"] += 1

    return bins
