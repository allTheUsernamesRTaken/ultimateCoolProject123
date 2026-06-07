from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ArtifactModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class FileRef(ArtifactModel):
    drive_id: str
    mime_type: str
    filename: str


class Submission(ArtifactModel):
    submission_id: str
    assignment_id: str
    student_id: str
    files: list[FileRef]
    pulled_at: datetime


class ExtractedContent(ArtifactModel):
    submission_id: str
    source: Literal["ocr", "parsed"]
    text: str
    needs_review: bool = False


class RubricBreakdown(ArtifactModel):
    criterion: str
    score: float
    max_score: float
    feedback: str = ""
    topics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def score_cannot_exceed_max(self) -> "RubricBreakdown":
        if self.max_score <= 0:
            raise ValueError("max_score must be greater than 0")
        if self.score < 0:
            raise ValueError("score cannot be negative")
        if self.score > self.max_score:
            raise ValueError("score cannot exceed max_score")
        return self


class GradingResult(ArtifactModel):
    submission_id: str
    assignment_id: str
    score: float
    max_score: float
    rubric_breakdown: list[RubricBreakdown]
    feedback: str
    topics: list[str] = Field(default_factory=list)
    confidence: float

    @field_validator("topics", mode="before")
    @classmethod
    def coerce_topics(cls, value: Any) -> list[str]:
        if value is None:
            return []
        return value

    @model_validator(mode="after")
    def scores_are_valid(self) -> "GradingResult":
        if self.max_score <= 0:
            raise ValueError("max_score must be greater than 0")
        if self.score < 0:
            raise ValueError("score cannot be negative")
        if self.score > self.max_score:
            raise ValueError("score cannot exceed max_score")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return self

    @property
    def percent(self) -> float:
        return self.score / self.max_score


class AssignmentConfig(ArtifactModel):
    assignment_id: str
    rubric: list[dict[str, Any]]
    max_score: float
    subject: str
    answer_key: str | None = None
