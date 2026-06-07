from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from artifact_io import ARTIFACTS_ROOT, read_submission, write_submission
from extraction.core import run_extraction
from grading.core import run_grading
from schemas import GradingResult, Submission, SubmissionFile


READ_SCOPES = [
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
GRADE_PASSBACK_SCOPES = [
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/drive.readonly",
]
GOOGLE_EXPORT_MIME_TYPES = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}


@dataclass(frozen=True)
class ClassroomSyncSummary:
    course_id: str
    course_work_id: str
    imported: int = 0
    skipped: int = 0
    downloaded_files: int = 0
    warnings: list[str] = field(default_factory=list)
    submission_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MassGradeSummary:
    synced: ClassroomSyncSummary
    graded: int = 0
    failed: int = 0
    published: int = 0
    returned: int = 0
    warnings: list[str] = field(default_factory=list)
    results: list[GradingResult] = field(default_factory=list)


def get_credentials(
    scopes: list[str],
    credentials_path: Path = Path("credentials.json"),
    token_path: Path = Path("token.json"),
) -> Credentials:
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not credentials_path.exists():
            raise FileNotFoundError(
                f"Missing {credentials_path}. Download an OAuth client JSON from Google Cloud Console."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), scopes)
        creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def build_services(scopes: list[str], credentials_path: Path = Path("credentials.json"), token_path: Path = Path("token.json")):
    creds = get_credentials(scopes, credentials_path, token_path)
    classroom = build("classroom", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return classroom, drive


def anonymize_id(student_id: str) -> str:
    return hashlib.sha256(student_id.encode("utf-8")).hexdigest()[:12]


def sync_assignment(
    course_id: str,
    course_work_id: str,
    artifacts_root: Path = ARTIFACTS_ROOT,
    credentials_path: Path = Path("credentials.json"),
    token_path: Path = Path("token.json"),
    force: bool = False,
    states: list[str] | None = None,
) -> ClassroomSyncSummary:
    classroom, drive = build_services(READ_SCOPES, credentials_path, token_path)
    return sync_assignment_with_services(
        classroom=classroom,
        drive=drive,
        course_id=course_id,
        course_work_id=course_work_id,
        artifacts_root=artifacts_root,
        force=force,
        states=states,
    )


def sync_assignment_with_services(
    classroom,
    drive,
    course_id: str,
    course_work_id: str,
    artifacts_root: Path = ARTIFACTS_ROOT,
    force: bool = False,
    states: list[str] | None = None,
) -> ClassroomSyncSummary:
    raw_files_dir = artifacts_root / "raw_files"
    raw_files_dir.mkdir(parents=True, exist_ok=True)

    imported = 0
    skipped = 0
    downloaded_files = 0
    warnings: list[str] = []
    submission_ids: list[str] = []
    page_token = None

    while True:
        request_kwargs = {
            "courseId": course_id,
            "courseWorkId": course_work_id,
            "pageToken": page_token,
        }
        if states:
            request_kwargs["states"] = states

        response = classroom.courses().courseWork().studentSubmissions().list(**request_kwargs).execute()
        for classroom_submission in response.get("studentSubmissions", []):
            submission_id = classroom_submission.get("id")
            if not submission_id:
                warnings.append("Skipped a Classroom submission without an id.")
                continue

            if not force:
                try:
                    read_submission(submission_id, artifacts_root)
                    skipped += 1
                    submission_ids.append(submission_id)
                    continue
                except FileNotFoundError:
                    pass

            files, file_warnings, file_count = _download_submission_files(
                drive=drive,
                submission=classroom_submission,
                destination_dir=raw_files_dir,
            )
            warnings.extend(file_warnings)
            downloaded_files += file_count

            submission = Submission(
                submission_id=submission_id,
                assignment_id=course_work_id,
                course_id=course_id,
                student_id=anonymize_id(classroom_submission.get("userId", submission_id)),
                files=files,
                pulled_at=datetime.now(timezone.utc),
                source="google_classroom",
                classroom_alternate_link=classroom_submission.get("alternateLink"),
                classroom_state=classroom_submission.get("state"),
            )
            write_submission(submission, artifacts_root)
            imported += 1
            submission_ids.append(submission_id)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return ClassroomSyncSummary(
        course_id=course_id,
        course_work_id=course_work_id,
        imported=imported,
        skipped=skipped,
        downloaded_files=downloaded_files,
        warnings=warnings,
        submission_ids=submission_ids,
    )


def mass_grade_assignment(
    course_id: str,
    course_work_id: str,
    artifacts_root: Path = ARTIFACTS_ROOT,
    credentials_path: Path = Path("credentials.json"),
    token_path: Path = Path("token.json"),
    force_sync: bool = False,
    force_regrade: bool = False,
    publish_grades: bool = False,
    assign_grades: bool = False,
    return_submissions: bool = False,
    states: list[str] | None = None,
) -> MassGradeSummary:
    scopes = GRADE_PASSBACK_SCOPES if publish_grades or return_submissions else READ_SCOPES
    classroom, drive = build_services(scopes, credentials_path, token_path)
    synced = sync_assignment_with_services(
        classroom=classroom,
        drive=drive,
        course_id=course_id,
        course_work_id=course_work_id,
        artifacts_root=artifacts_root,
        force=force_sync,
        states=states,
    )

    graded = 0
    failed = 0
    published = 0
    returned = 0
    warnings = list(synced.warnings)
    results: list[GradingResult] = []

    for submission_id in synced.submission_ids:
        grading_path = artifacts_root / "grading" / f"{submission_id}.json"
        if grading_path.exists() and not force_regrade:
            result = GradingResult.model_validate_json(grading_path.read_text(encoding="utf-8"))
            results.append(result)
        else:
            try:
                run_extraction(submission_id, artifacts_root)
                result = run_grading(submission_id, artifacts_root)
                results.append(result)
                graded += 1
            except Exception as exc:
                failed += 1
                warnings.append(f"{submission_id}: grading failed: {exc}")
                continue

        if publish_grades:
            try:
                publish_grade(
                    classroom=classroom,
                    course_id=course_id,
                    course_work_id=course_work_id,
                    submission_id=submission_id,
                    result=result,
                    assign_grade=assign_grades,
                )
                published += 1
            except Exception as exc:
                warnings.append(f"{submission_id}: grade passback failed: {exc}")

        if return_submissions:
            try:
                return_submission(classroom, course_id, course_work_id, submission_id)
                returned += 1
            except Exception as exc:
                warnings.append(f"{submission_id}: return failed: {exc}")

    return MassGradeSummary(
        synced=synced,
        graded=graded,
        failed=failed,
        published=published,
        returned=returned,
        warnings=warnings,
        results=results,
    )


def publish_grade(
    classroom,
    course_id: str,
    course_work_id: str,
    submission_id: str,
    result: GradingResult,
    assign_grade: bool = False,
) -> None:
    body = {"draftGrade": result.score}
    update_mask = "draftGrade"
    if assign_grade:
        body["assignedGrade"] = result.score
        update_mask = "draftGrade,assignedGrade"

    classroom.courses().courseWork().studentSubmissions().patch(
        courseId=course_id,
        courseWorkId=course_work_id,
        id=submission_id,
        updateMask=update_mask,
        body=body,
    ).execute()


def return_submission(classroom, course_id: str, course_work_id: str, submission_id: str) -> None:
    classroom.courses().courseWork().studentSubmissions().return_(
        courseId=course_id,
        courseWorkId=course_work_id,
        id=submission_id,
        body={},
    ).execute()


def _download_submission_files(drive, submission: dict, destination_dir: Path) -> tuple[list[SubmissionFile], list[str], int]:
    files: list[SubmissionFile] = []
    warnings: list[str] = []
    downloaded = 0
    attachments = submission.get("assignmentSubmission", {}).get("attachments", [])

    for attachment in attachments:
        drive_file = attachment.get("driveFile")
        if not drive_file:
            continue

        drive_id = drive_file.get("id")
        if not drive_id:
            warnings.append(f"{submission.get('id')}: skipped Drive attachment without an id.")
            continue

        title = drive_file.get("title") or drive_id
        try:
            metadata = drive.files().get(fileId=drive_id, fields="id,name,mimeType").execute()
            mime_type = metadata.get("mimeType", "application/octet-stream")
            title = metadata.get("name") or title
            download_mime_type, suffix = GOOGLE_EXPORT_MIME_TYPES.get(mime_type, (mime_type, Path(title).suffix))
            safe_name = _safe_filename(f"{drive_id}_{Path(title).stem}{suffix}")
            destination = destination_dir / safe_name
            if not destination.exists():
                _download_drive_file(drive, drive_id, mime_type, destination)
                downloaded += 1
            files.append(
                SubmissionFile(
                    drive_id=drive_id,
                    mime_type=download_mime_type,
                    filename=safe_name,
                    path=str(destination),
                )
            )
        except Exception as exc:
            warnings.append(f"{submission.get('id')}: failed to download {title}: {exc}")

    return files, warnings, downloaded


def _download_drive_file(drive, drive_id: str, mime_type: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mime_type in GOOGLE_EXPORT_MIME_TYPES:
        export_mime_type, _ = GOOGLE_EXPORT_MIME_TYPES[mime_type]
        request = drive.files().export_media(fileId=drive_id, mimeType=export_mime_type)
    else:
        request = drive.files().get_media(fileId=drive_id)

    with io.FileIO(str(destination), "wb") as handle:
        downloader = MediaIoBaseDownload(handle, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in value)
