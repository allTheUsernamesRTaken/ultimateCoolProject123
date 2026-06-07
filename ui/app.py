from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from statistics import mean

import pandas as pd
import streamlit as st

from schemas import GradingResult
from ui.analytics import load_grading_results, score_bins, summarize_topics, weak_topic_flags


ROOT = Path(__file__).resolve().parents[1]
GRADING_DIR = ROOT / "artifacts" / "grading"


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def save_feedback(path: Path, feedback: str) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["feedback"] = feedback
    raw["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


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


def render_submission(path: Path, result: GradingResult) -> None:
    st.subheader("Submission Review")
    c1, c2, c3 = st.columns(3)
    c1.metric("Score", f"{result.score:g}/{result.max_score:g}", percent(result.percent))
    c2.metric("Confidence", f"{result.confidence:.2f}")
    c3.metric("Topics", str(len(result.topics)))

    st.caption(f"Assignment {result.assignment_id} - Submission {result.submission_id}")
    if result.topics:
        st.write(" ".join(f"`{topic}`" for topic in result.topics))

    rubric_rows = [
        {
            "Criterion": item.criterion,
            "Score": item.score,
            "Max": item.max_score,
            "Percent": percent(item.score / item.max_score),
            "Feedback": item.feedback,
            "Topics": ", ".join(item.topics),
        }
        for item in result.rubric_breakdown
    ]
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
    if not loaded:
        st.error(f"No grading artifacts found in {GRADING_DIR}.")
        return

    paths = {result.submission_id: path for path, result in loaded}
    all_results = [result for _, result in loaded]
    assignment_ids = sorted({result.assignment_id for result in all_results})

    with st.sidebar:
        st.header("Controls")
        assignment = st.selectbox("Assignment", ["All assignments", *assignment_ids])
        cutoff = st.slider("Weak-topic cutoff", min_value=40, max_value=95, value=70, step=5)
        min_students = st.number_input("Minimum students", min_value=1, value=2, step=1)

    filtered = [
        result
        for result in all_results
        if assignment == "All assignments" or result.assignment_id == assignment
    ]

    tab_review, tab_dashboard, tab_export = st.tabs(["Review", "Dashboard", "Export"])

    with tab_review:
        ordered_ids = [result.submission_id for result in filtered]
        selected_id = st.selectbox("Submission", ordered_ids)
        selected_path = paths[selected_id]
        selected_result = next(result for result in filtered if result.submission_id == selected_id)
        render_submission(selected_path, selected_result)

    with tab_dashboard:
        render_analytics(filtered, cutoff, int(min_students))

    with tab_export:
        st.subheader("Export Reviewed Feedback")
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


if __name__ == "__main__":
    main()
