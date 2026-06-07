from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


LOW_CONFIDENCE_THRESHOLD = 0.70


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float | None
    needs_review: bool
    warnings: list[str] = field(default_factory=list)


class OcrEngine(Protocol):
    def extract(self, path: Path, mime_type: str) -> OcrResult:
        ...


class TesseractOcrEngine:
    def __init__(self, low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD) -> None:
        self.low_confidence_threshold = low_confidence_threshold

    def extract(self, path: Path, mime_type: str) -> OcrResult:
        try:
            images = self._load_images(path, mime_type)
        except Exception as exc:
            return OcrResult(
                text="",
                confidence=None,
                needs_review=True,
                warnings=[f"OCR could not load {path.name}: {exc}"],
            )

        texts: list[str] = []
        confidences: list[float] = []
        warnings: list[str] = []

        try:
            import pytesseract
            from pytesseract import Output
        except ImportError:
            return OcrResult(
                text="",
                confidence=None,
                needs_review=True,
                warnings=["pytesseract is not installed; OCR could not run."],
            )

        for page_number, image in enumerate(images, start=1):
            try:
                data = pytesseract.image_to_data(image, output_type=Output.DICT)
            except Exception as exc:
                warnings.append(f"Tesseract failed on page {page_number}: {exc}")
                continue

            words = [word for word in data.get("text", []) if word and word.strip()]
            texts.append(" ".join(words))
            for raw_confidence in data.get("conf", []):
                try:
                    confidence = float(raw_confidence)
                except (TypeError, ValueError):
                    continue
                if confidence >= 0:
                    confidences.append(confidence / 100)

        text = "\n\n".join(part for part in texts if part.strip()).strip()
        confidence = sum(confidences) / len(confidences) if confidences else None
        needs_review = (
            not text
            or confidence is None
            or confidence < self.low_confidence_threshold
            or bool(warnings)
        )
        return OcrResult(text=text, confidence=confidence, needs_review=needs_review, warnings=warnings)

    def _load_images(self, path: Path, mime_type: str) -> list[object]:
        suffix = path.suffix.lower()
        if mime_type.lower() == "application/pdf" or suffix == ".pdf":
            try:
                from pdf2image import convert_from_path
            except ImportError as exc:
                raise RuntimeError("pdf2image is not installed") from exc
            return list(convert_from_path(str(path)))

        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Pillow is not installed") from exc

        return [Image.open(path)]
