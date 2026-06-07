import json
import os
from pathlib import Path
from typing import TypeVar, Type

from schemas.models import Submission, ExtractedContent, GradingResult, AssignmentConfig

ARTIFACTS_DIR = Path("artifacts")

def _write_artifact(model_obj, type_folder: str, obj_id: str):
    folder = ARTIFACTS_DIR / type_folder
    folder.mkdir(parents=True, exist_ok=True)
    file_path = folder / f"{obj_id}.json"
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(model_obj.model_dump_json(indent=2))

T = TypeVar('T')

def _read_artifact(model_class: Type[T], type_folder: str, obj_id: str) -> T:
    file_path = ARTIFACTS_DIR / type_folder / f"{obj_id}.json"
    if not file_path.exists():
        raise FileNotFoundError(f"Artifact not found: {file_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        return model_class.model_validate_json(f.read())

# --- Submission ---
def write_submission(obj: Submission):
    _write_artifact(obj, "submissions", obj.submission_id)

def read_submission(submission_id: str) -> Submission:
    return _read_artifact(Submission, "submissions", submission_id)

# --- ExtractedContent ---
def write_extracted_content(obj: ExtractedContent):
    _write_artifact(obj, "extracted", obj.submission_id)

def read_extracted_content(submission_id: str) -> ExtractedContent:
    return _read_artifact(ExtractedContent, "extracted", submission_id)

# --- GradingResult ---
def write_grading_result(obj: GradingResult):
    _write_artifact(obj, "grading", obj.submission_id)

def read_grading_result(submission_id: str) -> GradingResult:
    return _read_artifact(GradingResult, "grading", submission_id)

# --- AssignmentConfig ---
def write_assignment_config(obj: AssignmentConfig, assignment_id: str):
    _write_artifact(obj, "config", assignment_id)

def read_assignment_config(assignment_id: str) -> AssignmentConfig:
    return _read_artifact(AssignmentConfig, "config", assignment_id)
