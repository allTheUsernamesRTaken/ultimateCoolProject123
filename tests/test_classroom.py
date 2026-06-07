from datetime import datetime, timezone

from artifact_io import read_submission, write_grading_result
from ingestion import classroom as classroom_module
from ingestion.classroom import publish_grade, sync_assignment_with_services
from schemas import GradingResult


class FakeExecutable:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeStudentSubmissions:
    def __init__(self, pages):
        self.pages = pages
        self.list_calls = []
        self.patch_calls = []
        self.return_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        page_index = len(self.list_calls) - 1
        return FakeExecutable(self.pages[page_index])

    def patch(self, **kwargs):
        self.patch_calls.append(kwargs)
        return FakeExecutable({"id": kwargs["id"]})

    def return_(self, **kwargs):
        self.return_calls.append(kwargs)
        return FakeExecutable({"id": kwargs["id"], "state": "RETURNED"})


class FakeCourseWork:
    def __init__(self, student_submissions):
        self._student_submissions = student_submissions

    def studentSubmissions(self):
        return self._student_submissions


class FakeCourses:
    def __init__(self, student_submissions):
        self._course_work = FakeCourseWork(student_submissions)

    def courseWork(self):
        return self._course_work


class FakeClassroom:
    def __init__(self, pages):
        self.student_submissions = FakeStudentSubmissions(pages)

    def courses(self):
        return FakeCourses(self.student_submissions)


class FakeDriveFiles:
    def __init__(self, metadata):
        self.metadata = metadata

    def get(self, **kwargs):
        return FakeExecutable(self.metadata[kwargs["fileId"]])


class FakeDrive:
    def __init__(self, metadata):
        self._files = FakeDriveFiles(metadata)

    def files(self):
        return self._files


def test_sync_assignment_downloads_classroom_submissions(tmp_path, monkeypatch):
    pages = [
        {
            "studentSubmissions": [
                {
                    "id": "sub_1",
                    "userId": "student@example.com",
                    "state": "TURNED_IN",
                    "alternateLink": "https://classroom.google.com/sub_1",
                    "assignmentSubmission": {
                        "attachments": [
                            {
                                "driveFile": {
                                    "id": "drive_1",
                                    "title": "answer.txt",
                                }
                            }
                        ]
                    },
                }
            ]
        }
    ]
    classroom = FakeClassroom(pages)
    drive = FakeDrive({"drive_1": {"id": "drive_1", "name": "answer.txt", "mimeType": "text/plain"}})

    def fake_download(_drive, _drive_id, _mime_type, destination):
        destination.write_text("student work", encoding="utf-8")

    monkeypatch.setattr(classroom_module, "_download_drive_file", fake_download)

    summary = sync_assignment_with_services(
        classroom=classroom,
        drive=drive,
        course_id="course_1",
        course_work_id="work_1",
        artifacts_root=tmp_path,
        states=["TURNED_IN"],
    )

    saved = read_submission("sub_1", tmp_path)
    assert summary.imported == 1
    assert summary.downloaded_files == 1
    assert saved.course_id == "course_1"
    assert saved.assignment_id == "work_1"
    assert saved.source == "google_classroom"
    assert saved.classroom_state == "TURNED_IN"
    assert saved.files[0].path.endswith("artifacts") is False
    assert (tmp_path / "raw_files" / saved.files[0].filename).exists()
    assert classroom.student_submissions.list_calls[0]["states"] == ["TURNED_IN"]


def test_sync_assignment_skips_existing_submission(tmp_path, monkeypatch):
    result = GradingResult(
        submission_id="sub_1",
        assignment_id="work_1",
        score=8,
        max_score=10,
        feedback="Good work.",
        confidence=0.9,
    )
    write_grading_result(result, tmp_path)

    pages = [{"studentSubmissions": [{"id": "sub_1", "userId": "student"}]}]
    classroom = FakeClassroom(pages)
    drive = FakeDrive({})

    from artifact_io import write_submission
    from schemas import Submission

    write_submission(
        Submission(
            submission_id="sub_1",
            assignment_id="work_1",
            course_id="course_1",
            student_id="student",
            pulled_at=datetime(2026, 6, 7, 21, 0, tzinfo=timezone.utc),
        ),
        tmp_path,
    )

    summary = sync_assignment_with_services(
        classroom=classroom,
        drive=drive,
        course_id="course_1",
        course_work_id="work_1",
        artifacts_root=tmp_path,
    )

    assert summary.imported == 0
    assert summary.skipped == 1


def test_publish_grade_writes_draft_and_assigned_grade():
    classroom = FakeClassroom([])
    result = GradingResult(
        submission_id="sub_1",
        assignment_id="work_1",
        score=8.5,
        max_score=10,
        feedback="Nice.",
        confidence=0.9,
    )

    publish_grade(
        classroom=classroom,
        course_id="course_1",
        course_work_id="work_1",
        submission_id="sub_1",
        result=result,
        assign_grade=True,
    )

    [call] = classroom.student_submissions.patch_calls
    assert call["courseId"] == "course_1"
    assert call["courseWorkId"] == "work_1"
    assert call["id"] == "sub_1"
    assert call["updateMask"] == "draftGrade,assignedGrade"
    assert call["body"] == {"draftGrade": 8.5, "assignedGrade": 8.5}
