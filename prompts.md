# Team Role Prompts

Three self-contained prompts — one per person. Each is written to paste into your own AI
coding assistant to bootstrap your slice. They share the contracts below and communicate
**only through JSON artifacts on disk**, so all three can be built in parallel with zero
coordination after the contracts are frozen.

## Shared rules (everyone reads this)

- Stack: Python. Storage: read/write JSON files under `artifacts/` (P1 swaps in SQLite later).
- Never import another stage's code. Read its JSON output, write yours.
- Every stage has a CLI entrypoint: `python -m <stage> run <submission_id>`.
- Validate every artifact against the Pydantic models in `schemas/`.
- Commit fixtures so others have realistic input immediately.

### Contracts (`schemas/`, freeze before splitting)

```python
Submission:        submission_id, assignment_id, student_id, files[], pulled_at
ExtractedContent:  submission_id, source("ocr"|"parsed"), text, needs_review
GradingResult:     submission_id, assignment_id, score, max_score,
                   rubric_breakdown[], feedback, topics[], confidence
AssignmentConfig:  rubric, max_score, subject, optional answer_key
```

### Artifact flow on disk

```
artifacts/submissions/<id>.json        ← P1 writes
artifacts/extracted/<id>.json          ← P2 writes (reads submissions/)
artifacts/grading/<id>.json            ← P2 writes (reads extracted/ + config)
artifacts/config/<assignment_id>.json  ← AssignmentConfig (hand-authored fixture)
```

---

## P1 — Ingestion + Storage

```
Build the ingestion + storage slice of an AI grader, in Python.

Contracts (Pydantic, in schemas/): Submission has submission_id, assignment_id,
student_id, files[] (each {drive_id, mime_type, filename}), pulled_at.

Tasks:
1. Define ALL shared Pydantic models in schemas/ (Submission, ExtractedContent,
   GradingResult, AssignmentConfig) — you own the schema file the whole team imports.
2. Build a storage layer with two functions per artifact type: write_<x>(obj) and
   read_<x>(id), backed by JSON files under artifacts/<type>/<id>.json. Keep the
   interface clean so it can be swapped to SQLite without callers changing.
3. Ingestion: Google OAuth (scopes classroom.coursework.readonly + drive.readonly),
   list coursework submissions for an assignment, resolve attached Drive file IDs,
   download files, and write Submission artifacts. Make sync idempotent (re-running
   doesn't duplicate). Tokens from env vars, never committed. student_id anonymizable.
4. CLI: `python -m ingestion sync <assignment_id>`.
5. Ship 2-3 Submission fixtures (one scanned PDF, one text PDF) so P2 isn't blocked.

Start with the schemas and the JSON storage layer FIRST and commit them — the rest of
the team is waiting on those.
```

---

## P2 — Extraction + Grading

```
iBuild the extraction + grading slice of an AI grader, in Python.

You read artifacts/submissions/<id>.json (Submission) and artifacts/config/<id>.json
(AssignmentConfig), and write artifacts/extracted/<id>.json (ExtractedContent) then
artifacts/grading/<id>.json (GradingResult). Use the Pydantic models in schemas/.
Until P1's real submissions land, work against the committed Submission fixtures.

Extraction tasks:
1. Branch first: inspect mime type / attempt a text-layer parse. If the PDF has
   extractable text → source="parsed", skip OCR. Otherwise run OCR.
2. OCR behind a swappable interface; start with Tesseract. Flag low-confidence output
   with needs_review=true.
3. Output ExtractedContent. CLI: `python -m extraction run <submission_id>`.

Grading tasks:
4. Prompt = AssignmentConfig (rubric + optional answer key) + ExtractedContent.text.
   Use the openai API (openai or openai) with structured output.
5. Return per-criterion points, concept tags, and feedback prose. Feedback must: name
   what was done well, pinpoint the specific error AND the misconception behind it, and
   give one concrete next step. Encouraging, not punitive.
6. Tag topics from a fixed controlled vocabulary (NOT free text) so cohort analytics
   stay consistent. Low confidence or large rubric disagreement → set a review flag.
7. Output GradingResult. CLI: `python -m grading run <submission_id>`.

Before writing openai API code, consult the openai -api skill for current model ids and
structured-output usage.
```

---

## P3 — Analytics + Teacher UI

```
Build the teacher-facing UI + cohort analytics for an AI grader, using Streamlit.

You read artifacts/grading/<id>.json (GradingResult) — fields: score, max_score,
rubric_breakdown[], feedback, topics[], confidence. Use the Pydantic models in schemas/.
Work against committed GradingResult fixtures until P2's real output lands.

Tasks:
1. Per-submission view: show score, rubric breakdown, and an EDITABLE feedback box the
   teacher can tweak. Save edits back to the grading artifact. Export reviewed feedback
   (CSV or printable). No auto-posting back to Classroom in v1.
2. Cohort analytics (just queries over GradingResult, no separate stage): average score
   per topic per assignment; flag "class struggling with X" when a topic's average drops
   below a cutoff across enough students. Make the cutoff/min-students configurable.
3. Cohort dashboard: weak-topic flags, score distribution, simple trend view.
4. Run with `streamlit run ui/app.py`.

Build entirely against the fixtures first — you should have a working dashboard before
P2's live grading exists.
```
