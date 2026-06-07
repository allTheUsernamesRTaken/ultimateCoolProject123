import argparse
import hashlib
import io
import os
from datetime import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from schemas.models import Submission, FileRef
from storage import write_submission, read_submission

# Scopes needed
SCOPES = [
    'https://www.googleapis.com/auth/classroom.coursework.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

def get_credentials():
    creds = None
    # The file token.json stores the user's access and refresh tokens
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                print("WARNING: credentials.json not found. Please create one from Google Cloud Console.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def anonymize_id(student_id: str) -> str:
    # Hash the student id to keep it anonymizable
    return hashlib.sha256(student_id.encode('utf-8')).hexdigest()[:12]

def download_file(drive_service, drive_id: str, dest_path: Path):
    if dest_path.exists():
        print(f"File {drive_id} already downloaded at {dest_path}, skipping.")
        return
    
    request = drive_service.files().get_media(fileId=drive_id)
    fh = io.FileIO(str(dest_path), 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    print(f"Downloaded {drive_id} to {dest_path}")

def sync_assignment(course_id: str, assignment_id: str):
    creds = get_credentials()
    if not creds:
        return

    classroom = build('classroom', 'v1', credentials=creds)
    drive = build('drive', 'v3', credentials=creds)

    print(f"Fetching submissions for course {course_id}, assignment {assignment_id}...")
    
    # Create raw_files directory
    raw_files_dir = Path("artifacts/raw_files")
    raw_files_dir.mkdir(parents=True, exist_ok=True)

    page_token = None
    while True:
        results = classroom.courses().courseWork().studentSubmissions().list(
            courseId=course_id,
            courseWorkId=assignment_id,
            pageToken=page_token
        ).execute()

        submissions = results.get('studentSubmissions', [])
        
        if not submissions:
            print("No submissions found.")
            break
            
        for sub in submissions:
            sub_id = sub.get('id')
            student_id = sub.get('userId')
            
            # Idempotency check: see if we already have this submission
            try:
                existing = read_submission(sub_id)
                print(f"Submission {sub_id} already synced, skipping.")
                continue
            except FileNotFoundError:
                pass
            
            anon_student_id = anonymize_id(student_id)
            
            assignment_submission = sub.get('assignmentSubmission', {})
            attachments = assignment_submission.get('attachments', [])
            
            files = []
            for attachment in attachments:
                if 'driveFile' in attachment:
                    drive_file = attachment['driveFile']
                    drive_id = drive_file.get('id')
                    filename = drive_file.get('title')
                    
                    # fetch mimeType from drive API just to be sure, or rely on extension if not available easily
                    # Doing a quick get to find mimetype
                    try:
                        file_meta = drive.files().get(fileId=drive_id, fields='mimeType').execute()
                        mime_type = file_meta.get('mimeType', 'application/octet-stream')
                    except Exception as e:
                        print(f"Error getting mimeType for {drive_id}: {e}")
                        mime_type = 'application/octet-stream'
                        
                    # download file
                    # Append drive_id to filename to avoid collisions
                    safe_filename = f"{drive_id}_{filename}".replace("/", "_").replace("\\", "_")
                    dest_path = raw_files_dir / safe_filename
                    
                    try:
                        download_file(drive, drive_id, dest_path)
                        files.append(FileRef(
                            drive_id=drive_id,
                            mime_type=mime_type,
                            filename=safe_filename
                        ))
                    except Exception as e:
                        print(f"Error downloading {drive_id}: {e}")

            submission_obj = Submission(
                submission_id=sub_id,
                assignment_id=assignment_id,
                student_id=anon_student_id,
                files=files,
                pulled_at=datetime.now(datetime.UTC)
            )
            write_submission(submission_obj)
            print(f"Saved submission {sub_id}")

        page_token = results.get('nextPageToken')
        if not page_token:
            break

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Sync submissions from Google Classroom")
    parser.add_argument("course_id", help="The Google Classroom Course ID")
    parser.add_argument("assignment_id", help="The Google Classroom CourseWork ID (Assignment ID)")
    
    args = parser.parse_args()
    sync_assignment(args.course_id, args.assignment_id)
