from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from schemas import AssignmentConfig, ExtractedContent, GradingResult, Submission


ARTIFACTS_ROOT = Path("artifacts")

ModelT = TypeVar("ModelT", bound=BaseModel)


def _read_model(path: Path, model_type: type[ModelT]) -> ModelT:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return model_type.model_validate(payload)


def _write_model(path: Path, model: BaseModel) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump_json(indent=2)
    path.write_text(payload + "\n", encoding="utf-8")
    return path


def read_submission(submission_id: str, root: Path = ARTIFACTS_ROOT) -> Submission:
    return _read_model(root / "submissions" / f"{submission_id}.json", Submission)


def write_submission(submission: Submission, root: Path = ARTIFACTS_ROOT) -> Path:
    return _write_model(root / "submissions" / f"{submission.submission_id}.json", submission)


def read_extracted(submission_id: str, root: Path = ARTIFACTS_ROOT) -> ExtractedContent:
    return _read_model(root / "extracted" / f"{submission_id}.json", ExtractedContent)


def write_extracted(content: ExtractedContent, root: Path = ARTIFACTS_ROOT) -> Path:
    return _write_model(root / "extracted" / f"{content.submission_id}.json", content)


def read_assignment_config(config_id: str, root: Path = ARTIFACTS_ROOT) -> AssignmentConfig:
    config = _read_model(root / "config" / f"{config_id}.json", AssignmentConfig)
    if config.assignment_id is None:
        config = config.model_copy(update={"assignment_id": config_id})
    return config


def write_assignment_config(config: AssignmentConfig, root: Path = ARTIFACTS_ROOT) -> Path:
    if config.assignment_id is None:
        raise ValueError("AssignmentConfig.assignment_id is required when writing config artifacts")
    return _write_model(root / "config" / f"{config.assignment_id}.json", config)


def read_config_for_submission(submission: Submission, root: Path = ARTIFACTS_ROOT) -> AssignmentConfig:
    assignment_path = root / "config" / f"{submission.assignment_id}.json"
    if assignment_path.exists():
        return read_assignment_config(submission.assignment_id, root)
    return read_assignment_config(submission.submission_id, root)


def write_grading_result(result: GradingResult, root: Path = ARTIFACTS_ROOT) -> Path:
    return _write_model(root / "grading" / f"{result.submission_id}.json", result)


def read_grading_result(submission_id: str, root: Path = ARTIFACTS_ROOT) -> GradingResult:
    return _read_model(root / "grading" / f"{submission_id}.json", GradingResult)
