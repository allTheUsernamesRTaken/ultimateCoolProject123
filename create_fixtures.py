import os
from datetime import datetime
from pathlib import Path
from reportlab.pdfgen import canvas
from schemas.models import Submission, FileRef
from storage import write_submission

def create_fixtures():
    # Setup directories
    raw_files_dir = Path("artifacts/raw_files")
    raw_files_dir.mkdir(parents=True, exist_ok=True)
    
    # Fixture 1: Text PDF
    text_pdf_path = raw_files_dir / "text_fixture.pdf"
    c = canvas.Canvas(str(text_pdf_path))
    c.drawString(100, 750, "This is a dummy text PDF submission.")
    c.drawString(100, 730, "The student has written an essay about the Roman Empire.")
    c.save()
    
    # Fixture 2: Scanned PDF (simulated by drawing an image or just text that is hard to extract? 
    # Actually, if we just don't add text and add an image, pypdf won't find text. We can draw a simple shape instead of an image so reportlab doesn't need an external image file).
    # Since reportlab needs an image file, let's just create a PDF with no text layers, only vectors, or just a very basic shape to simulate a "scan" where pypdf returns empty text.
    scanned_pdf_path = raw_files_dir / "scan_fixture.pdf"
    c2 = canvas.Canvas(str(scanned_pdf_path))
    c2.rect(100, 700, 200, 100, fill=1) # A black rectangle
    c2.save()

    # Create submission JSON fixtures
    sub1 = Submission(
        submission_id="sub-1001",
        assignment_id="assign-001",
        student_id="student-A",
        files=[
            FileRef(drive_id="drive-101", mime_type="application/pdf", filename="text_fixture.pdf")
        ],
        pulled_at=datetime.now(datetime.UTC)
    )
    write_submission(sub1)

    sub2 = Submission(
        submission_id="sub-1002",
        assignment_id="assign-001",
        student_id="student-B",
        files=[
            FileRef(drive_id="drive-102", mime_type="application/pdf", filename="scan_fixture.pdf")
        ],
        pulled_at=datetime.now(datetime.UTC)
    )
    write_submission(sub2)

    print("Fixtures created successfully.")

if __name__ == '__main__':
    create_fixtures()
