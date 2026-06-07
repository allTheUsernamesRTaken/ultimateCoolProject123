from __future__ import annotations

import json
import os
import re
from typing import Protocol

from pydantic import BaseModel, Field

from schemas import AssignmentConfig, ExtractedContent, TopicTag


DEFAULT_MODEL = "gpt-5-mini"
POWERSHELL_ENV_PATTERN = re.compile(
    r"""^\s*\$env:([A-Za-z_][A-Za-z0-9_]*)\s*=\s*["'](.*)["']\s*$"""
)
DOTENV_PATTERN = re.compile(r"""^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$""")


class CriterionGradeDraft(BaseModel):
    criterion_id: str
    points: float = Field(ge=0)
    concept_tags: list[TopicTag] = Field(default_factory=list)
    feedback: str
    confidence: float = Field(ge=0, le=1)


class FeedbackParts(BaseModel):
    what_went_well: str
    specific_error: str
    misconception: str
    next_step: str


class GradeDraft(BaseModel):
    rubric_breakdown: list[CriterionGradeDraft]
    topics: list[TopicTag] = Field(default_factory=list)
    feedback: FeedbackParts
    confidence: float = Field(ge=0, le=1)
    rubric_disagreement: float = Field(ge=0, le=1)


class GradingClient(Protocol):
    def grade(self, config: AssignmentConfig, extracted: ExtractedContent) -> GradeDraft:
        ...


class OpenAIGradingClient:
    def __init__(self, model: str | None = None) -> None:
        _load_environment()
        self.model = model or os.getenv("AIGRADER_OPENAI_MODEL", DEFAULT_MODEL)

    def grade(self, config: AssignmentConfig, extracted: ExtractedContent) -> GradeDraft:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The openai package is not installed. Install requirements.txt before running grading."
            ) from exc

        client = OpenAI()
        messages = _build_messages(config, extracted)

        responses = getattr(client, "responses", None)
        parse = getattr(responses, "parse", None)
        if parse is not None:
            response = parse(
                model=self.model,
                input=messages,
                text_format=GradeDraft,
            )
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                raise RuntimeError("OpenAI returned no parsed structured grading output.")
            return GradeDraft.model_validate(parsed)

        response = client.responses.create(
            model=self.model,
            input=messages,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "grade_draft",
                    "schema": GradeDraft.model_json_schema(),
                    "strict": True,
                }
            },
        )
        return GradeDraft.model_validate_json(_extract_response_text(response))


def _build_messages(config: AssignmentConfig, extracted: ExtractedContent) -> list[dict[str, str]]:
    allowed_topics = [topic.value for topic in config.allowed_topics]
    rubric = [
        {
            "id": criterion.id,
            "description": criterion.description,
            "max_points": criterion.max_points,
            "topics": [topic.value for topic in criterion.topics],
        }
        for criterion in config.rubric
    ]
    payload = {
        "assignment": {
            "assignment_id": config.assignment_id,
            "subject": config.subject,
            "max_score": config.max_score,
            "rubric": rubric,
            "answer_key": config.answer_key,
            "allowed_topics": allowed_topics,
        },
        "extracted_submission": {
            "submission_id": extracted.submission_id,
            "text": extracted.text,
            "extraction_source": extracted.source,
            "extraction_confidence": extracted.confidence,
            "extraction_needs_review": extracted.needs_review,
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You are an encouraging teacher's grading assistant. Grade only against the provided "
                "rubric and answer key. Return structured output only. Use topic tags only from the "
                "controlled vocabulary supplied in the assignment. Feedback must name what the student "
                "did well, pinpoint a specific error, explain the misconception behind that error, and "
                "give exactly one concrete next step. Be precise and supportive, never punitive."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, indent=2),
        },
    ]


def _load_environment() -> None:
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, encoding="utf-8-sig") as env_file:
        for line in env_file:
            _load_env_line(line)


def _load_env_line(line: str) -> None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return

    match = POWERSHELL_ENV_PATTERN.match(line) or DOTENV_PATTERN.match(line)
    if not match:
        return

    key, value = match.groups()
    os.environ.setdefault(key, _clean_env_value(value))


def _clean_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _extract_response_text(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    output = getattr(response, "output", None)
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            content = getattr(item, "content", None)
            if isinstance(content, list):
                for content_item in content:
                    text = getattr(content_item, "text", None)
                    if text:
                        parts.append(str(text))
        if parts:
            return "\n".join(parts)

    raise RuntimeError("Could not extract text from OpenAI response.")
