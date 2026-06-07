from datetime import datetime, timezone

from artifact_io import read_grading_result, write_extracted, write_submission
from grading.clients import CriterionGradeDraft, FeedbackParts, GradeDraft
from grading.core import grade_submission, run_grading
from schemas import (
    AssignmentConfig,
    ExtractedContent,
    ReviewFlag,
    RubricCriterion,
    Submission,
    SubmissionFile,
    TopicTag,
)


class FakeGradingClient:
    def grade(self, config: AssignmentConfig, extracted: ExtractedContent) -> GradeDraft:
        return GradeDraft(
            rubric_breakdown=[
                CriterionGradeDraft(
                    criterion_id="solve",
                    points=4,
                    concept_tags=[TopicTag.LINEAR_EQUATIONS],
                    feedback="The equation is solved correctly.",
                    confidence=0.92,
                ),
                CriterionGradeDraft(
                    criterion_id="explain",
                    points=1.5,
                    concept_tags=[TopicTag.CONCEPTUAL_UNDERSTANDING],
                    feedback="The explanation names the operation but not why equality is preserved.",
                    confidence=0.55,
                ),
            ],
            topics=[TopicTag.LINEAR_EQUATIONS, TopicTag.CONCEPTUAL_UNDERSTANDING],
            feedback=FeedbackParts(
                what_went_well="You correctly isolated x and got x = 4.",
                specific_error="The explanation skips why subtracting 3 is allowed on both sides.",
                misconception="This suggests you may see inverse operations as a trick rather than a balance-preserving move.",
                next_step="Write one sentence explaining that doing the same operation to both sides keeps the equation equal.",
            ),
            confidence=0.6,
            rubric_disagreement=0.4,
        )


def _config() -> AssignmentConfig:
    return AssignmentConfig(
        assignment_id="assignment",
        subject="Algebra I",
        max_score=7,
        rubric=[
            RubricCriterion(
                id="solve",
                description="Solve the equation.",
                max_points=4,
                topics=[TopicTag.LINEAR_EQUATIONS],
            ),
            RubricCriterion(
                id="explain",
                description="Explain the inverse operation.",
                max_points=3,
                topics=[TopicTag.CONCEPTUAL_UNDERSTANDING],
            ),
        ],
        answer_key="x = 4",
        allowed_topics=[TopicTag.LINEAR_EQUATIONS, TopicTag.CONCEPTUAL_UNDERSTANDING],
    )


def test_grade_submission_builds_controlled_result_and_review_flags():
    extracted = ExtractedContent(
        submission_id="sub",
        source="parsed",
        text="x + 3 = 7, x = 4",
        needs_review=True,
    )

    result = grade_submission("sub", "assignment", _config(), extracted, FakeGradingClient())

    assert result.score == 5.5
    assert result.needs_review is True
    assert ReviewFlag.EXTRACTION_NEEDS_REVIEW in result.review_flags
    assert ReviewFlag.LOW_CONFIDENCE in result.review_flags
    assert ReviewFlag.LARGE_RUBRIC_DISAGREEMENT in result.review_flags
    assert result.topics == [TopicTag.LINEAR_EQUATIONS, TopicTag.CONCEPTUAL_UNDERSTANDING]
    assert "What went well" in result.feedback
    assert "Misconception" in result.feedback
    assert "Next step" in result.feedback


def test_run_grading_reads_and_writes_artifacts(tmp_path):
    config = _config()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "assignment.json").write_text(
        config.model_dump_json(indent=2), encoding="utf-8"
    )
    write_submission(
        Submission(
            submission_id="sub",
            assignment_id="assignment",
            student_id="student",
            files=[
                SubmissionFile(
                    mime_type="text/plain",
                    filename="answer.txt",
                    path="answer.txt",
                )
            ],
            pulled_at=datetime(2026, 6, 7, 21, 0, tzinfo=timezone.utc),
        ),
        tmp_path,
    )
    write_extracted(
        ExtractedContent(
            submission_id="sub",
            source="parsed",
            text="x + 3 = 7, x = 4",
        ),
        tmp_path,
    )

    result = run_grading("sub", artifacts_root=tmp_path, grading_client=FakeGradingClient())

    assert result == read_grading_result("sub", tmp_path)
