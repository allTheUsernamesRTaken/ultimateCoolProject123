from pathlib import Path

from extraction.core import extract_submission
from extraction.ocr import OcrResult
from schemas import Submission, SubmissionFile


class FailingOcrEngine:
    def extract(self, path: Path, mime_type: str) -> OcrResult:
        raise AssertionError("OCR should not run when text is parseable")


class FakeOcrEngine:
    def extract(self, path: Path, mime_type: str) -> OcrResult:
        return OcrResult(
            text="OCR recovered answer: x = 4",
            confidence=0.52,
            needs_review=True,
            warnings=["Low OCR confidence"],
        )


def test_extract_submission_skips_ocr_for_text_file(tmp_path):
    source = tmp_path / "answer.txt"
    source.write_text("x + 3 = 7, so x = 4.", encoding="utf-8")
    submission = Submission(
        submission_id="sub_text",
        assignment_id="assignment",
        student_id="student",
        files=[
            SubmissionFile(
                mime_type="text/plain",
                filename="answer.txt",
                path=str(source),
            )
        ],
        pulled_at="2026-06-07T21:00:00Z",
    )

    extracted = extract_submission(submission, tmp_path, FailingOcrEngine())

    assert extracted.source == "parsed"
    assert extracted.needs_review is False
    assert "x = 4" in extracted.text


def test_extract_submission_uses_ocr_when_no_text_layer(tmp_path):
    source = tmp_path / "scan.bin"
    source.write_bytes(b"not parseable text")
    submission = Submission(
        submission_id="sub_ocr",
        assignment_id="assignment",
        student_id="student",
        files=[
            SubmissionFile(
                mime_type="image/png",
                filename="scan.png",
                path=str(source),
            )
        ],
        pulled_at="2026-06-07T21:00:00Z",
    )

    extracted = extract_submission(submission, tmp_path, FakeOcrEngine())

    assert extracted.source == "ocr"
    assert extracted.needs_review is True
    assert extracted.confidence == 0.52
    assert "OCR recovered answer" in extracted.text
