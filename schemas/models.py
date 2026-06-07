from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class FileRef(BaseModel):
    drive_id: str
    mime_type: str
    filename: str

class Submission(BaseModel):
    submission_id: str
    assignment_id: str
    student_id: str
    files: List[FileRef] = Field(default_factory=list)
    pulled_at: datetime

class ExtractedContent(BaseModel):
    submission_id: str
    source: str = Field(pattern="^(ocr|parsed)$")
    text: str
    needs_review: bool

class RubricItem(BaseModel):
    criterion: str
    points: float
    max_points: float

class GradingResult(BaseModel):
    submission_id: str
    assignment_id: str
    score: float
    max_score: float
    rubric_breakdown: List[RubricItem] = Field(default_factory=list)
    feedback: str
    topics: List[str] = Field(default_factory=list)
    confidence: float

class AssignmentConfig(BaseModel):
    rubric: str
    max_score: float
    subject: str
    answer_key: Optional[str] = None
