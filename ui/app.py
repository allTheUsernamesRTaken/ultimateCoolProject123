from __future__ import annotations

import csv
import base64
import json
import mimetypes
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from statistics import mean

import pandas as pd
import streamlit as st

from artifact_io import ARTIFACTS_ROOT, write_submission
from extraction.core import run_extraction
from grading.core import run_grading
from ingestion.classroom import mass_grade_assignment, sync_assignment
from schemas import GradingResult, Submission, SubmissionFile
from ui.analytics import load_grading_results, score_bins, summarize_topics, weak_topic_flags


ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS_DIR = ROOT / "artifacts" / "submissions"
SUBMISSION_FILES_DIR = ROOT / "artifacts" / "submission_files"
GRADING_DIR = ROOT / "artifacts" / "grading"
EXTRACTED_DIR = ROOT / "artifacts" / "extracted"


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def display_label(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw).replace("_", " ").title()


def save_feedback(path: Path, feedback: str) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["feedback"] = feedback
    raw["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


def load_submission(submission_id: str) -> Submission | None:
    path = SUBMISSIONS_DIR / f"{submission_id}.json"
    if not path.exists():
        return None
    return Submission.model_validate_json(path.read_text(encoding="utf-8"))


def load_extracted_text(submission_id: str) -> str | None:
    path = EXTRACTED_DIR / f"{submission_id}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("text") or None


def resolve_submission_file(file: SubmissionFile, submission_id: str) -> Path:
    if file.path:
        path = Path(file.path)
        if path.is_absolute():
            return path
        root_relative = ROOT / path
        if root_relative.exists():
            return root_relative
        artifact_relative = ARTIFACTS_ROOT / path
        if artifact_relative.exists():
            return artifact_relative
        return ROOT / "artifacts" / "raw_files" / file.filename
    return SUBMISSION_FILES_DIR / submission_id / file.filename


def safe_submission_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value.strip())
    return cleaned.strip("_") or f"submission_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


def safe_filename(value: str) -> str:
    path = Path(value)
    stem = safe_submission_id(path.stem)
    suffix = path.suffix.lower()
    return f"{stem}{suffix}" if suffix else stem


def reviewed_feedback_csv(results: list[GradingResult]) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "assignment_id",
            "submission_id",
            "score",
            "max_score",
            "percent",
            "confidence",
            "topics",
            "feedback",
        ],
    )
    writer.writeheader()
    for result in results:
        writer.writerow(
            {
                "assignment_id": result.assignment_id,
                "submission_id": result.submission_id,
                "score": result.score,
                "max_score": result.max_score,
                "percent": f"{result.percent * 100:.1f}",
                "confidence": f"{result.confidence:.2f}",
                "topics": "; ".join(result.topics),
                "feedback": result.feedback,
            }
        )
    return output.getvalue()


def printable_feedback(results: list[GradingResult]) -> str:
    sections = []
    for result in results:
        sections.append(
            "\n".join(
                [
                    f"Assignment: {result.assignment_id}",
                    f"Submission: {result.submission_id}",
                    f"Score: {result.score:g}/{result.max_score:g} ({percent(result.percent)})",
                    f"Topics: {', '.join(result.topics) if result.topics else 'None'}",
                    "",
                    result.feedback,
                ]
            )
        )
    return "\n\n" + ("-" * 72 + "\n\n").join(sections)


def render_source_file(path: Path, mime_type: str) -> None:
    if not path.exists():
        st.warning(f"Original file is missing: {path}")
        return

    suffix = path.suffix.lower()
    if mime_type.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        st.image(str(path), width="stretch")
        return

    if mime_type == "application/pdf" or suffix == ".pdf":
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        st.markdown(
            f"""
            <iframe
                src="data:application/pdf;base64,{encoded}"
                width="100%"
                height="760"
                style="border:1px solid #d9dee7;border-radius:8px;background:white;"
            ></iframe>
            """,
            unsafe_allow_html=True,
        )
        return

    if mime_type.startswith("text/") or suffix in {".txt", ".md", ".csv", ".tsv"}:
        st.code(path.read_text(encoding="utf-8", errors="replace"), language=None)
        return

    st.info(f"Preview is not available for {path.name}.")
    st.download_button("Download original file", path.read_bytes(), file_name=path.name)


def render_annotation_panel(result: GradingResult) -> None:
    st.markdown("#### Review Annotations")
    if result.review_flags:
        for flag in result.review_flags:
            st.warning(display_label(flag))

    for item in result.rubric_breakdown:
        status = "Needs attention" if item.score < item.max_points else "Looks good"
        st.markdown(f"**{item.criterion}**")
        st.progress(item.score / item.max_points, text=f"{item.score:g}/{item.max_points:g} - {status}")
        st.caption(", ".join(display_label(topic) for topic in item.topics) or "No topic tags")
        st.write(item.feedback)


def render_sheet_review(result: GradingResult) -> None:
    submission = load_submission(result.submission_id)
    st.markdown("#### Annotated Sheet")
    st.caption(
        "This shows the original submission beside feedback annotations. Pinpoint overlays require "
        "page coordinates from OCR or document parsing, which the current artifacts do not store yet."
    )

    if submission is None or not submission.files:
        extracted_text = load_extracted_text(result.submission_id)
        if extracted_text:
            st.text_area("Extracted submission text", value=extracted_text, height=360, disabled=True)
        else:
            st.info("No original submission artifact is linked to this grading result.")
        return

    file_labels = [file.filename for file in submission.files]
    selected_label = st.selectbox("Source file", file_labels, key=f"source-file-{result.submission_id}")
    selected_file = next(file for file in submission.files if file.filename == selected_label)
    selected_path = resolve_submission_file(selected_file, submission.submission_id)

    sheet_col, notes_col = st.columns([1.35, 1])
    with sheet_col:
        render_source_file(selected_path, selected_file.mime_type)
    with notes_col:
        render_annotation_panel(result)


def render_submission(path: Path, result: GradingResult) -> None:
    st.subheader("Submission Review")
    c1, c2, c3 = st.columns(3)
    c1.metric("Score", f"{result.score:g}/{result.max_score:g}", percent(result.percent))
    c2.metric("Confidence", f"{result.confidence:.2f}")
    c3.metric("Topics", str(len(result.topics)))

    st.caption(f"Assignment {result.assignment_id} - Submission {result.submission_id}")
    if result.topics:
        st.write(" ".join(f"`{topic}`" for topic in result.topics))

    render_sheet_review(result)

    rubric_rows = [
        {
            "Criterion": item.criterion,
            "Score": item.score,
            "Max": item.max_points,
            "Percent": percent(item.score / item.max_points),
            "Feedback": item.feedback,
            "Topics": ", ".join(item.topics),
        }
        for item in result.rubric_breakdown
    ]
    st.markdown("#### Rubric Breakdown")
    st.dataframe(pd.DataFrame(rubric_rows), width="stretch", hide_index=True)

    form_key = f"feedback-form-{path.stem}"
    with st.form(form_key):
        edited_feedback = st.text_area(
            "Reviewed feedback",
            value=result.feedback,
            height=220,
            help="Teacher edits are saved back into this grading JSON artifact.",
        )
        submitted = st.form_submit_button("Save feedback")
        if submitted:
            save_feedback(path, edited_feedback)
            st.success("Feedback saved to the grading artifact.")
            st.rerun()


def render_submission_intake(assignment_ids: list[str]) -> None:
    st.subheader("Add Submissions")
    st.caption(
        "Upload local files into the same artifact structure used by Classroom sync. "
        "Google Classroom sync and mass grading are available in the Google Classroom tab."
    )

    with st.form("manual-submission-form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        default_assignment = assignment_ids[0] if assignment_ids else ""
        assignment_id = c1.text_input("Assignment ID", value=default_assignment)
        submission_id = c2.text_input("Submission ID")
        student_id = c3.text_input("Student ID", value="manual")
        uploads = st.file_uploader(
            "Submission files",
            accept_multiple_files=True,
            type=["pdf", "png", "jpg", "jpeg", "webp", "txt", "md", "csv", "tsv"],
        )
        run_pipeline = st.checkbox("Run extraction and grading after upload", value=False)
        submitted = st.form_submit_button("Save submission")

    if not submitted:
        st.info(
            "For Google Classroom from the command line: `python -m ingestion sync <course_id> "
            "<coursework_id>` pulls submissions, and `python -m ingestion grade <course_id> "
            "<coursework_id>` syncs and grades them."
        )
        return

    if not assignment_id.strip():
        st.error("Assignment ID is required.")
        return
    if not uploads:
        st.error("Upload at least one file.")
        return

    submission_key = safe_submission_id(submission_id or Path(uploads[0].name).stem)
    target_dir = SUBMISSION_FILES_DIR / submission_key
    target_dir.mkdir(parents=True, exist_ok=True)

    files: list[SubmissionFile] = []
    for upload in uploads:
        filename = safe_filename(upload.name)
        destination = target_dir / filename
        destination.write_bytes(upload.getbuffer())
        mime_type = upload.type or mimetypes.guess_type(upload.name)[0] or "application/octet-stream"
        files.append(
            SubmissionFile(
                mime_type=mime_type,
                filename=filename,
                path=str(destination.relative_to(ROOT)),
            )
        )

    submission = Submission(
        submission_id=submission_key,
        assignment_id=assignment_id.strip(),
        student_id=student_id.strip() or "manual",
        files=files,
        pulled_at=datetime.now(timezone.utc),
    )
    write_submission(submission, ARTIFACTS_ROOT)
    st.success(f"Saved submission {submission_key}.")

    if run_pipeline:
        try:
            run_extraction(submission_key, ARTIFACTS_ROOT)
            result = run_grading(submission_key, ARTIFACTS_ROOT)
            st.success(f"Graded {submission_key}: {result.score:g}/{result.max_score:g}.")
        except Exception as exc:
            st.error(f"Saved the submission, but the pipeline did not finish: {exc}")


def render_classroom_integration() -> None:
    st.subheader("Google Classroom")
    st.caption(
        "Sync a Classroom assignment, download attached student work, and run extraction/grading in bulk. "
        "Grade passback writes overall scores only; Classroom rubric-line grades are read-only through the API."
    )

    with st.form("classroom-sync-form"):
        c1, c2 = st.columns(2)
        course_id = c1.text_input("Course ID")
        course_work_id = c2.text_input("Coursework / assignment ID")

        c3, c4 = st.columns(2)
        credentials_path = c3.text_input("OAuth credentials JSON", value="credentials.json")
        token_path = c4.text_input("Token cache", value="token.json")

        c5, c6, c7 = st.columns(3)
        mode = c5.selectbox("Action", ["Sync only", "Sync and mass grade"])
        turned_in_only = c6.checkbox("Turned-in only", value=True)
        force_sync = c7.checkbox("Refresh existing submissions", value=False)

        c8, c9, c10 = st.columns(3)
        force_regrade = c8.checkbox("Regrade existing results", value=False)
        publish_drafts = c9.checkbox("Publish draft grades", value=False)
        assign_grades = c10.checkbox("Also assign grades", value=False)
        return_submissions = st.checkbox("Return submissions after publishing grades", value=False)

        submitted = st.form_submit_button("Run Classroom job")

    st.info(
        "Setup needed once: create a Google OAuth desktop client, save it as `credentials.json`, "
        "then run this job and sign in as a teacher for the course. If you change scopes, delete "
        "`token.json` so Google asks for the new permissions. If grade passback returns PERMISSION_DENIED, "
        "Google may require the coursework to be associated with this OAuth project."
    )

    if not submitted:
        return

    if not course_id.strip() or not course_work_id.strip():
        st.error("Course ID and coursework ID are required.")
        return

    states = ["TURNED_IN"] if turned_in_only else None
    try:
        with st.spinner("Talking to Google Classroom and processing submissions..."):
            if mode == "Sync only":
                summary = sync_assignment(
                    course_id=course_id.strip(),
                    course_work_id=course_work_id.strip(),
                    artifacts_root=ARTIFACTS_ROOT,
                    credentials_path=Path(credentials_path),
                    token_path=Path(token_path),
                    force=force_sync,
                    states=states,
                )
                st.success(
                    f"Imported {summary.imported}, skipped {summary.skipped}, "
                    f"downloaded {summary.downloaded_files} file(s)."
                )
                warnings = summary.warnings
            else:
                summary = mass_grade_assignment(
                    course_id=course_id.strip(),
                    course_work_id=course_work_id.strip(),
                    artifacts_root=ARTIFACTS_ROOT,
                    credentials_path=Path(credentials_path),
                    token_path=Path(token_path),
                    force_sync=force_sync,
                    force_regrade=force_regrade,
                    publish_grades=publish_drafts or assign_grades or return_submissions,
                    assign_grades=assign_grades,
                    return_submissions=return_submissions,
                    states=states,
                )
                st.success(
                    f"Imported {summary.synced.imported}, skipped {summary.synced.skipped}, "
                    f"graded {summary.graded}, failed {summary.failed}, "
                    f"published {summary.published}, returned {summary.returned}."
                )
                warnings = summary.warnings

        for warning in warnings:
            st.warning(warning)
        st.rerun()
    except Exception as exc:
        st.error(f"Classroom job failed: {exc}")


def render_analytics(results: list[GradingResult], cutoff: float, min_students: int) -> None:
    st.subheader("Cohort Dashboard")
    summaries = summarize_topics(results)
    flags = weak_topic_flags(summaries, cutoff / 100, min_students)

    avg_score = mean([result.percent for result in results]) if results else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Submissions", str(len(results)))
    c2.metric("Average score", percent(avg_score))
    c3.metric("Weak-topic flags", str(len(flags)))

    if flags:
        st.markdown("#### Class may be struggling with")
        for flag in flags:
            st.warning(
                f"{flag.topic}: class average is {percent(flag.average_percent)} "
                f"across {flag.student_count} students."
            )
    else:
        st.info("No weak-topic flags at the current cutoff and minimum student count.")

    st.markdown("#### Topic averages")
    topic_rows = [
        {
            "Assignment": summary.assignment_id,
            "Topic": summary.topic,
            "Average": round(summary.average_percent * 100, 1),
            "Students": summary.student_count,
        }
        for summary in summaries
    ]
    st.dataframe(pd.DataFrame(topic_rows), width="stretch", hide_index=True)

    st.markdown("#### Score distribution")
    bins = score_bins(results)
    st.bar_chart(pd.DataFrame({"Submissions": bins}).T)

    st.markdown("#### Assignment trend")
    trend_rows = []
    for assignment_id in sorted({result.assignment_id for result in results}):
        assignment_results = [result for result in results if result.assignment_id == assignment_id]
        trend_rows.append(
            {
                "Assignment": assignment_id,
                "Average score": mean(result.percent for result in assignment_results) * 100,
            }
        )
    if trend_rows:
        st.line_chart(pd.DataFrame(trend_rows).set_index("Assignment"))


def main() -> None:
    st.set_page_config(page_title="AI Grader Teacher Review", layout="wide")
    st.title("AI Grader Teacher Review")

    loaded = load_grading_results(GRADING_DIR)
    paths = {result.submission_id: path for path, result in loaded}
    all_results = [result for _, result in loaded]
    assignment_ids = sorted({result.assignment_id for result in all_results})

    with st.sidebar:
        st.header("Controls")
        assignment_options = ["All assignments", *assignment_ids]
        assignment = st.selectbox("Assignment", assignment_options)
        cutoff = st.slider("Weak-topic cutoff", min_value=40, max_value=95, value=70, step=5)
        min_students = st.number_input("Minimum students", min_value=1, value=2, step=1)

    filtered = [
        result
        for result in all_results
        if assignment == "All assignments" or result.assignment_id == assignment
    ]

    tab_review, tab_add, tab_classroom, tab_dashboard, tab_export = st.tabs(
        ["Review", "Add Submissions", "Google Classroom", "Dashboard", "Export"]
    )

    with tab_review:
        if not filtered:
            st.info(f"No grading artifacts found in {GRADING_DIR}. Add submissions or run a Classroom mass-grade job.")
        else:
            ordered_ids = [result.submission_id for result in filtered]
            selected_id = st.selectbox("Submission", ordered_ids)
            selected_path = paths[selected_id]
            selected_result = next(result for result in filtered if result.submission_id == selected_id)
            render_submission(selected_path, selected_result)

    with tab_add:
        render_submission_intake(assignment_ids)

    with tab_classroom:
        render_classroom_integration()

    with tab_dashboard:
        if filtered:
            render_analytics(filtered, cutoff, int(min_students))
        else:
            st.info("No graded submissions yet.")

    with tab_export:
        st.subheader("Export Reviewed Feedback")
        if filtered:
            st.download_button(
                "Download CSV",
                reviewed_feedback_csv(filtered),
                file_name="reviewed_feedback.csv",
                mime="text/csv",
            )
            st.download_button(
                "Download printable text",
                printable_feedback(filtered),
                file_name="reviewed_feedback.txt",
                mime="text/plain",
            )
        else:
            st.info("No reviewed feedback to export yet.")


if __name__ == "__main__":
    main()
