# Make schemas a package

from .models import (
    AssignmentConfig,
    ExtractedContent,
    FileRef,
    GradingResult,
    RubricBreakdown,
    Submission,
)

__all__ = [
    "AssignmentConfig",
    "ExtractedContent",
    "FileRef",
    "GradingResult",
    "RubricBreakdown",
    "Submission",
]
