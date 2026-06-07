from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field


class TopicTag(str, Enum):
    LINEAR_EQUATIONS = "linear_equations"
    ALGEBRAIC_MANIPULATION = "algebraic_manipulation"
    PROCEDURE = "procedure"
    CONCEPTUAL_UNDERSTANDING = "conceptual_understanding"
    MATHEMATICAL_REASONING = "mathematical_reasoning"
    UNITS = "units"
    NOTATION = "notation"
    EVIDENCE = "evidence"
    CLAIMS = "claims"
    ORGANIZATION = "organization"
    GRAMMAR = "grammar"
    READING_COMPREHENSION = "reading_comprehension"
    SCIENTIFIC_REASONING = "scientific_reasoning"
    DATA_INTERPRETATION = "data_interpretation"


class ReviewFlag(str, Enum):
    EXTRACTION_NEEDS_REVIEW = "extraction_needs_review"
    LOW_CONFIDENCE = "low_confidence"
    LARGE_RUBRIC_DISAGREEMENT = "large_rubric_disagreement"
    TOPIC_OUTSIDE_ASSIGNMENT = "topic_outside_assignment"
    EMPTY_SUBMISSION = "empty_submission"
    MODEL_REFUSAL = "model_refusal"


class SubmissionFile(BaseModel):
    drive_id: str | None = None
    mime_type: str
    filename: str
    path: str | None = None


FileRef = SubmissionFile


class Submission(BaseModel):
    submission_id: str
    assignment_id: str
    student_id: str
    files: list[SubmissionFile] = Field(default_factory=list)
    pulled_at: datetime


class ExtractedContent(BaseModel):
    submission_id: str
    source: Literal["ocr", "parsed"]
    text: str
    needs_review: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class RubricCriterion(BaseModel):
    id: str = Field(validation_alias=AliasChoices("id", "criterion"))
    description: str = ""
    max_points: float = Field(validation_alias=AliasChoices("max_points", "points"), gt=0)
    topics: list[TopicTag] = Field(default_factory=list)


class AssignmentConfig(BaseModel):
    assignment_id: str | None = None
    subject: str
    max_score: float = Field(gt=0)
    rubric: list[RubricCriterion]
    answer_key: str | None = None
    allowed_topics: list[TopicTag] = Field(default_factory=lambda: list(TopicTag))


class CriterionScore(BaseModel):
    criterion_id: str = Field(validation_alias=AliasChoices("criterion_id", "criterion"))
    points: float = Field(validation_alias=AliasChoices("points", "score"), ge=0)
    max_points: float = Field(validation_alias=AliasChoices("max_points", "max_score"), gt=0)
    concept_tags: list[TopicTag | str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("concept_tags", "topics"),
    )
    feedback: str
    confidence: float = Field(default=1, ge=0, le=1)

    @property
    def criterion(self) -> str:
        return self.criterion_id

    @property
    def score(self) -> float:
        return self.points

    @property
    def max_score(self) -> float:
        return self.max_points

    @property
    def topics(self) -> list[TopicTag | str]:
        return self.concept_tags


RubricItem = CriterionScore
RubricBreakdown = CriterionScore


class GradingResult(BaseModel):
    submission_id: str
    assignment_id: str
    score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    rubric_breakdown: list[CriterionScore] = Field(default_factory=list)
    feedback: str
    topics: list[TopicTag | str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    needs_review: bool = False
    review_flags: list[ReviewFlag] = Field(default_factory=list)

    @property
    def percent(self) -> float:
        return self.score / self.max_score
