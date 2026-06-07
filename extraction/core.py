from __future__ import annotations

from pathlib import Path

from artifact_io import ARTIFACTS_ROOT, read_submission, write_extracted
from schemas import ExtractedContent, Submission, SubmissionFile

from .ocr import OcrEngine, TesseractOcrEngine


PDF_MIME_TYPES = {"application/pdf", "application/x-pdf"}
TEXT_MIME_PREFIXES = ("text/",)
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tsv"}
IMAGE_MIME_PREFIXES = ("image/",)


def run_extraction(
    submission_id: str,
    artifacts_root: Path = ARTIFACTS_ROOT,
    ocr_engine: OcrEngine | None = None,
) -> ExtractedContent:
    submission = read_submission(submission_id, artifacts_root)
    content = extract_submission(submission, artifacts_root, ocr_engine or TesseractOcrEngine())
    write_extracted(content, artifacts_root)
    return content


def extract_submission(
    submission: Submission,
    artifacts_root: Path,
    ocr_engine: OcrEngine,
) -> ExtractedContent:
    chunks: list[str] = []
    warnings: list[str] = []
    confidences: list[float] = []
    used_ocr = False
    needs_review = False

    for file in submission.files:
        path = _resolve_file_path(file, artifacts_root, submission.submission_id)
        if not path.exists():
            warnings.append(f"Missing file: {path}")
            needs_review = True
            continue

        parsed_text = _extract_parseable_text(file, path, warnings)
        if parsed_text.strip():
            chunks.append(_format_file_chunk(file.filename, parsed_text))
            continue

        used_ocr = True
        ocr_result = ocr_engine.extract(path, file.mime_type)
        if ocr_result.text.strip():
            chunks.append(_format_file_chunk(file.filename, ocr_result.text))
        if ocr_result.confidence is not None:
            confidences.append(ocr_result.confidence)
        if ocr_result.needs_review:
            needs_review = True
        warnings.extend(ocr_result.warnings)

    text = "\n\n".join(chunks).strip()
    if not text:
        needs_review = True
        warnings.append("No text was extracted from the submission.")

    confidence = _mean(confidences)
    return ExtractedContent(
        submission_id=submission.submission_id,
        source="ocr" if used_ocr else "parsed",
        text=text,
        needs_review=needs_review,
        confidence=confidence,
        warnings=warnings,
    )


def _extract_parseable_text(file: SubmissionFile, path: Path, warnings: list[str]) -> str:
    mime_type = file.mime_type.lower()
    suffix = path.suffix.lower()

    if mime_type in PDF_MIME_TYPES or suffix == ".pdf":
        return _extract_pdf_text(path, warnings)

    if mime_type.startswith(TEXT_MIME_PREFIXES) or suffix in TEXT_SUFFIXES:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="latin-1")

    if mime_type.startswith(IMAGE_MIME_PREFIXES):
        return ""

    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _extract_pdf_text(path: Path, warnings: list[str]) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        warnings.append("pypdf is not installed; PDF text-layer parsing was skipped.")
        return ""

    try:
        reader = PdfReader(str(path))
        page_text = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        warnings.append(f"PDF text-layer parsing failed for {path.name}: {exc}")
        return ""

    return "\n".join(part for part in page_text if part.strip())


def _resolve_file_path(file: SubmissionFile, artifacts_root: Path, submission_id: str) -> Path:
    if file.path:
        path = Path(file.path)
        return path if path.is_absolute() else Path.cwd() / path

    return artifacts_root / "submission_files" / submission_id / file.filename


def _format_file_chunk(filename: str, text: str) -> str:
    return f"--- {filename} ---\n{text.strip()}"


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
