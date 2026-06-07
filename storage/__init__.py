# Make storage a package
from .json_storage import (
    write_submission, read_submission,
    write_extracted_content, read_extracted_content,
    write_grading_result, read_grading_result,
    write_assignment_config, read_assignment_config
)
