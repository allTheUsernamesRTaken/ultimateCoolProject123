# AI Grader — Project Plan

An AI grading assistant for teachers. It pulls assignment submissions from Google
Classroom / Drive, extracts the student's work (OCR for scans, direct parse for text
PDFs), grades it with an AI model, and returns **constructive feedback** instead of a
bare score. Over time it tracks cohort performance to surface topics the whole class is
struggling with.

The plan is deliberately structured as a **pipeline of independent stages** so a team of
2–3 people can work in parallel with almost no day-to-day coordination.

---

## 1. Goals

- Read teacher assignment submissions from Google Classroom + Drive automatically.
- Handle **scanned pages via OCR**; skip OCR for parsable text/PDF.
- Grade content with an AI model (math-first, but subject-agnostic).
- Produce **encouraging, actionable feedback** explaining *why* a grade was given.
- Track class performance over time → flag cohort-wide weak topics
  (e.g. *"the class is consistently struggling with quadratic equations"*).

### Non-goals (v1)
- No mobile app, no LMS other than Google Classroom.
- No auto-posting grades back to Classroom (export/review only — keeps the teacher in the loop and avoids a risky write integration early).
- No real-time grading; batch/triggered runs are fine.

---

## 2. The key design idea: a contract-first pipeline

Everything flows through five stages. **Each stage reads one artifact and writes the
next** — they never call each other directly. The artifacts are plain JSON (validated by
a shared schema). This is what makes parallel work cheap: each person mocks the upstream
artifact with a fixture and builds their stage in isolation.

```
[1] Ingestion    →  Submission        (raw refs pulled from Classroom/Drive)
[2] Extraction   →  ExtractedContent  (OCR-or-parse → clean text/structure)
[3] Grading      →  GradingResult     (score + rubric + feedback)
[4] Analytics    →  AnalyticsRecord   (denormalized for cohort queries)
[5] UI/Teacher   →  (reads everything, no new artifact)
```

Rule of thumb: **if you need data from another stage, you read its artifact — you never
import its code.** As long as the artifact shape doesn't change, two people can rewrite
their internals freely without breaking each other.

---

## 3. Shared contracts (define these FIRST — day 1, together)

This is the only thing that requires the whole team in one room. ~1–2 hours. Once these
are frozen, everyone scatters. Put them in `schemas/` as Pydantic models (or JSON Schema).

```python
Submission:
    submission_id: str
    assignment_id: str
    student_id: str            # anonymizable
    files: list[FileRef]       # {drive_id, mime_type, filename}
    pulled_at: datetime

ExtractedContent:
    submission_id: str
    source: "ocr" | "parsed"
    text: str
    pages: list[PageText]      # per-page text + confidence (OCR only)
    needs_review: bool         # low OCR confidence flag

GradingResult:
    submission_id: str
    assignment_id: str
    score: float
    max_score: float
    rubric_breakdown: list[Criterion]   # {name, points, comment}
    feedback: str                       # the encouraging, actionable prose
    topics: list[str]                   # tagged concepts, e.g. ["quadratic_equations"]
    model_version: str
    confidence: float

AnalyticsRecord:   # mostly derived from GradingResult, optimized for queries
    assignment_id, student_id, topic, score_pct, graded_at
```

Plus an **AssignmentConfig** the teacher provides per assignment: rubric, max score,
subject, optional answer key.

---

## 4. Work split

Each stream is a vertical slice you can build, test, and demo on its own using fixtures.

### Option A — 3 people

| Owner | Stream | Scope |
|---|---|---|
| **P1** | Ingestion + Storage | Google OAuth, Classroom/Drive APIs, file download, the DB + the artifact read/write layer everyone uses. |
| **P2** | Extraction + Grading | Scan-vs-text detection, OCR pipeline, AI grading prompts, rubric → feedback logic. |
| **P3** | Analytics + Teacher UI | Cohort aggregation, weak-topic detection, dashboard, feedback review/export. |

### Option B — 2 people

| Owner | Stream | Scope |
|---|---|---|
| **P1** | "Data plumbing" | Ingestion + Storage + Analytics. |
| **P2** | "Intelligence + presentation" | Extraction + Grading + Teacher UI. |

P1 always owns the shared storage/artifact layer because everyone depends on it — that
keeps the dependency in one place instead of spread across the team.

---

## 5. Sequencing — walking skeleton first, then deepen in parallel

The one real risk to parallel work is integrating late. Avoid it by building a **thin
end-to-end skeleton in the first day or two**, where every stage is a stub that just
passes a hardcoded fixture through. Once data flows end-to-end, each person deepens their
own stage independently — integration is already done.

**Phase 0 — Foundation (together, ~half a day)**
- Freeze the schemas in §3.
- Agree storage choice (SQLite for v1 — zero infra).
- Commit fixtures: 2–3 sample submissions (one scanned, one text PDF) at every artifact stage, so every downstream stage has realistic input on day 1.

**Phase 1 — Walking skeleton (~1–2 days, parallel)**
- Each stage runs with stubbed logic and reads/writes real artifacts.
- Demo: a fake submission flows all the way to a fake dashboard entry.

**Phase 2 — Deepen each stage (parallel, the bulk of the work)**
- P1: real Google auth + sync. P2: real OCR + real grading. P3: real analytics + UI.
- Nobody is blocked because the contracts and fixtures already exist.

**Phase 3 — Integration polish & demo**
- Swap fixtures for live data, error handling, end-to-end run on a real assignment.

---

## 6. Stage detail

### Stage 1 — Ingestion (P1)
- Google OAuth (service account or OAuth2 with `classroom.coursework` + `drive.readonly` scopes).
- List coursework submissions for an assignment → resolve attached Drive file IDs → download.
- Output `Submission` artifacts. Idempotent: re-running a sync shouldn't duplicate.
- **Security:** least-privilege scopes, tokens in env/secret store (never committed), anonymizable `student_id`.

### Stage 2 — Extraction (P2)
- **Branch first:** inspect mime type / try a text parse. If the PDF has an extractable text layer → `source="parsed"`, **skip OCR**. Otherwise → OCR.
- OCR options: Google Cloud Vision (best for math/handwriting, same ecosystem) or Tesseract (free/local). Start with one behind an interface so it's swappable.
- Math note: capture layout/per-page text; flag low-confidence pages with `needs_review`.
- Output `ExtractedContent`.

### Stage 3 — Grading (P2)
- Prompt = `AssignmentConfig` (rubric + optional answer key) + `ExtractedContent`.
- Ask the model for **structured output**: per-criterion points, concept tags, and feedback prose.
- Feedback guidelines baked into the prompt: name what was done well, pinpoint the specific error and the misconception behind it, give one concrete next step. Encouraging, not punitive.
- Tag `topics` from a per-subject concept list — this is what powers cohort analytics, so it must be consistent (controlled vocabulary, not free text).
- Output `GradingResult`. Low confidence / large rubric disagreement → flag for teacher review.

### Stage 4 — Analytics (P3)
- On each new `GradingResult`, write `AnalyticsRecord` rows (one per topic).
- Cohort queries: average score per topic per assignment; trend over time; threshold rule that emits *"class struggling with X"* when a topic's class average drops below a cutoff across enough students.

### Stage 5 — Teacher UI (P3)
- Per-submission view: score, rubric breakdown, editable feedback (teacher can tweak before exporting).
- Cohort dashboard: weak-topic flags, score distributions, trends.
- Fastest path: **Streamlit** (one person owns the whole UI in a day). Alternative: React + the API if more polish is needed.

---

## 7. Tech stack (chosen for low overhead)

- **Language:** Python (best fit for Google client libs, OCR, AI SDKs).
- **Storage:** SQLite v1 → Postgres if needed. Artifacts stored as JSON columns + a few indexed fields.
- **APIs:** `google-api-python-client`, Google Cloud Vision (or Tesseract).
- **AI:** a single grading client behind one interface (model swappable).
- **UI:** Streamlit (v1).
- **Repo:** one repo, one folder per stage (`ingestion/`, `extraction/`, `grading/`, `analytics/`, `ui/`, `schemas/`, `fixtures/`). Clear ownership per folder = few merge conflicts.

---

## 8. Conventions that keep overhead low

- **Schemas are frozen by agreement.** Changing one = a 5-min team ping, not a silent edit.
- **Every stage ships with fixtures** so others aren't blocked on your live integration.
- **No cross-stage imports.** Communicate only through artifacts.
- **Each stage runs standalone** via a CLI entrypoint (`python -m grading run <id>`), so it's independently testable and demoable.
- Short daily async check-in (text, not meeting) on the one shared thing: the schema.

---

## 9. Open questions to resolve in Phase 0

- OCR provider: Cloud Vision (quality, cost) vs Tesseract (free, weaker on handwriting)?
- How are rubrics/answer keys supplied — teacher form, or read from the Classroom assignment description?
- Student data handling: anonymize at ingestion, or store identifiable and lock down access?
- Weak-topic threshold: what score % and how many students trigger a flag?
- Does the teacher edit feedback before it's finalized? (Plan assumes yes.)
