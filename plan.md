# AI Grader — 1-Day Plan

An AI grading assistant for teachers. Pulls submissions from Google Classroom / Drive,
extracts the student's work (OCR for scans, direct parse for text PDFs), grades it with
an AI model, and returns **constructive feedback** — not just a score. Tracks cohort
performance to flag topics the whole class is struggling with.

## Pipeline

Data flows through stages as plain JSON artifacts. Each stage reads one artifact and
writes the next — no cross-stage imports. This lets people work in parallel against
fixtures.

```
Ingestion   → Submission        (file refs from Classroom/Drive)
Extraction  → ExtractedContent  (OCR-or-parse → clean text)
Grading     → GradingResult     (score + rubric + feedback + topics)
UI          → reads everything  (review, export, cohort dashboard)
```

Analytics is just queries over `GradingResult` — not a separate stage.

## Contracts (agree on these first, ~30 min)

Put in `schemas/` as Pydantic models.

```python
Submission:        submission_id, assignment_id, student_id, files[], pulled_at
ExtractedContent:  submission_id, source("ocr"|"parsed"), text, needs_review
GradingResult:     submission_id, assignment_id, score, max_score,
                   rubric_breakdown[], feedback, topics[], confidence
AssignmentConfig:  rubric, max_score, subject, optional answer_key
```

## Build order (single day)

1. **Foundation (together, ~1h):** freeze schemas, pick SQLite, commit 2–3 sample
   fixtures (one scanned, one text PDF) at each artifact stage so everyone has input.
2. **Skeleton:** every stage stubbed, passing a fixture through end-to-end. Fake
   submission → fake dashboard entry. Integration is done early.
3. **Deepen in parallel:** real Google sync, real OCR + grading, real UI. Nobody blocked
   because contracts + fixtures exist.
4. **Polish:** swap fixtures for live data, error handling, one real end-to-end run.

## Work split

- **P1 — Plumbing:** Google OAuth, Classroom/Drive download, SQLite + artifact read/write
  layer (everyone depends on this, so one owner).
- **P2 — Intelligence:** scan-vs-text detection, OCR (Tesseract to start, swappable),
  AI grading prompt → structured rubric + feedback + topic tags.
- **P3 — UI:** Streamlit. Per-submission view (editable feedback, export) + cohort
  dashboard with weak-topic flags.

2 people? Merge P1+UI plumbing and P2+UI presentation.

## Stage notes

- **Ingestion:** `classroom.coursework.students.readonly` + `drive.readonly` for
  sync; `classroom.coursework.students` when publishing grades. Idempotent sync.
  Tokens stay local, never committed. Anonymizable `student_id`.
- **Extraction:** try a text parse first; if PDF has a text layer → `source="parsed"`,
  skip OCR. Else OCR, flag low-confidence pages with `needs_review`.
- **Grading:** prompt = `AssignmentConfig` + `ExtractedContent`. Ask for structured
  output. Feedback = name what's good, pinpoint the error + misconception, give one next
  step. Tag `topics` from a controlled vocabulary so cohort analytics stay consistent.
- **UI / analytics:** average score per topic; flag "class struggling with X" when a
  topic's average drops below a cutoff across enough students. Teacher edits feedback
  before export. Classroom passback can publish overall draft/assigned grades; rubric
  line scores remain local because the Classroom API does not allow writing them.

## Stack

Python · SQLite (JSON columns) · `google-api-python-client` · Tesseract/Cloud Vision ·
one swappable grading client · Streamlit · one repo, one folder per stage.

## Open questions

- OCR: Tesseract (free) vs Cloud Vision (better handwriting)?
- Rubrics: teacher form or read from the Classroom assignment description?
- Weak-topic threshold: what score % and how many students trigger a flag?
