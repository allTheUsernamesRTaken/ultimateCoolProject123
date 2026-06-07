from __future__ import annotations

from pathlib import Path

from artifact_io import (
    ARTIFACTS_ROOT,
    read_config_for_submission,
    read_extracted,
    read_submission,
    write_grading_result,
)
from schemas import (
    AssignmentConfig,
    CriterionScore,
    ExtractedContent,
    GradingResult,
    ReviewFlag,
    TopicTag,
)

from .clients import GradeDraft, GradingClient, OpenAIGradingClient


LOW_CONFIDENCE_THRESHOLD = 0.65
LARGE_RUBRIC_DISAGREEMENT_THRESHOLD = 0.35


def run_grading(
    submission_id: str,
    artifacts_root: Path = ARTIFACTS_ROOT,
    grading_client: GradingClient | None = None,
) -> GradingResult:
    submission = read_submission(submission_id, artifacts_root)
    config = read_config_for_submission(submission, artifacts_root)
    extracted = read_extracted(submission_id, artifacts_root)
    result = grade_submission(
        submission_id=submission.submission_id,
        assignment_id=submission.assignment_id,
        config=config,
        extracted=extracted,
        grading_client=grading_client or OpenAIGradingClient(),
    )
    write_grading_result(result, artifacts_root)
    return result


def grade_submission(
    submission_id: str,
    assignment_id: str,
    config: AssignmentConfig,
    extracted: ExtractedContent,
    grading_client: GradingClient,
) -> GradingResult:
    if not extracted.text.strip():
        return _empty_submission_result(submission_id, assignment_id, config, extracted)

    try:
        draft = grading_client.grade(config, extracted)
    except Exception:
        raise

    allowed_topics = set(config.allowed_topics)
    criteria_by_id = {criterion.id: criterion for criterion in config.rubric}
    drafts_by_id = {item.criterion_id: item for item in draft.rubric_breakdown}

    breakdown: list[CriterionScore] = []
    review_flags: list[ReviewFlag] = []

    for criterion in config.rubric:
        criterion_draft = drafts_by_id.get(criterion.id)
        if criterion_draft is None:
            review_flags.append(ReviewFlag.LARGE_RUBRIC_DISAGREEMENT)
            breakdown.append(
                CriterionScore(
                    criterion_id=criterion.id,
                    points=0,
                    max_points=criterion.max_points,
                    concept_tags=_filter_topics(criterion.topics, allowed_topics),
                    feedback="This criterion was not scored by the grading model and needs teacher review.",
                    confidence=0,
                )
            )
            continue

        raw_tags = criterion_draft.concept_tags or criterion.topics
        filtered_tags = _filter_topics(raw_tags, allowed_topics)
        if len(filtered_tags) != len(raw_tags):
            review_flags.append(ReviewFlag.TOPIC_OUTSIDE_ASSIGNMENT)

        breakdown.append(
            CriterionScore(
                criterion_id=criterion.id,
                points=_clamp(criterion_draft.points, 0, criterion.max_points),
                max_points=criterion.max_points,
                concept_tags=filtered_tags,
                feedback=criterion_draft.feedback,
                confidence=criterion_draft.confidence,
            )
        )

    score = _clamp(sum(item.points for item in breakdown), 0, config.max_score)
    topics = _dedupe_topics(
        _filter_topics(draft.topics, allowed_topics)
        + [tag for item in breakdown for tag in item.concept_tags]
    )
    if len(_filter_topics(draft.topics, allowed_topics)) != len(draft.topics):
        review_flags.append(ReviewFlag.TOPIC_OUTSIDE_ASSIGNMENT)

    if extracted.needs_review:
        review_flags.append(ReviewFlag.EXTRACTION_NEEDS_REVIEW)
    if draft.confidence < LOW_CONFIDENCE_THRESHOLD or any(
        item.confidence < LOW_CONFIDENCE_THRESHOLD for item in breakdown
    ):
        review_flags.append(ReviewFlag.LOW_CONFIDENCE)
    if draft.rubric_disagreement >= LARGE_RUBRIC_DISAGREEMENT_THRESHOLD:
        review_flags.append(ReviewFlag.LARGE_RUBRIC_DISAGREEMENT)

    review_flags = list(dict.fromkeys(review_flags))
    return GradingResult(
        submission_id=submission_id,
        assignment_id=assignment_id,
        score=score,
        max_score=config.max_score,
        rubric_breakdown=breakdown,
        feedback=_compose_feedback(draft),
        topics=topics,
        confidence=draft.confidence,
        needs_review=bool(review_flags),
        review_flags=review_flags,
    )


def _empty_submission_result(
    submission_id: str,
    assignment_id: str,
    config: AssignmentConfig,
    extracted: ExtractedContent,
) -> GradingResult:
    flags = [ReviewFlag.EMPTY_SUBMISSION]
    if extracted.needs_review:
        flags.append(ReviewFlag.EXTRACTION_NEEDS_REVIEW)

    return GradingResult(
        submission_id=submission_id,
        assignment_id=assignment_id,
        score=0,
        max_score=config.max_score,
        rubric_breakdown=[
            CriterionScore(
                criterion_id=criterion.id,
                points=0,
                max_points=criterion.max_points,
                concept_tags=_filter_topics(criterion.topics, set(config.allowed_topics)),
                feedback="No readable submission text was available for this criterion.",
                confidence=0,
            )
            for criterion in config.rubric
        ],
        feedback=(
            "I could not find readable work to grade. A teacher should review the original submission "
            "and ask the student to resubmit a clearer copy if needed."
        ),
        topics=_dedupe_topics([tag for criterion in config.rubric for tag in criterion.topics]),
        confidence=0,
        needs_review=True,
        review_flags=flags,
    )


def _compose_feedback(draft: GradeDraft) -> str:
    return (
        f"What went well: {draft.feedback.what_went_well}\n"
        f"Specific error: {draft.feedback.specific_error}\n"
        f"Misconception: {draft.feedback.misconception}\n"
        f"Next step: {draft.feedback.next_step}"
    )


def _filter_topics(topics: list[TopicTag], allowed_topics: set[TopicTag]) -> list[TopicTag]:
    return [topic for topic in topics if topic in allowed_topics]


def _dedupe_topics(topics: list[TopicTag]) -> list[TopicTag]:
    return list(dict.fromkeys(topics))


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)
