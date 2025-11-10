import io
import zipfile

from github_action_triage.app.infra.log_extraction import extract_failure_excerpt


def test_extract_failure_excerpt_plain_text():
    """Test extraction from plain text logs."""
    log_content = "\n".join([f"Line {i}" for i in range(1, 151)])
    logs_bytes = log_content.encode("utf-8")
    
    excerpt = extract_failure_excerpt(logs_bytes, max_lines=50)
    
    lines = excerpt.splitlines()
    assert len(lines) == 50
    assert lines[0] == "Line 101"
    assert lines[-1] == "Line 150"


def test_extract_failure_excerpt_zipped_logs():
    """Test extraction from zipped GitHub log archive."""
    log_content = "\n".join([f"Line {i}" for i in range(1, 151)])
    
    # Create a zip archive with log content
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('0_job.txt', log_content.encode('utf-8'))
    
    logs_bytes = zip_buffer.getvalue()
    
    excerpt = extract_failure_excerpt(logs_bytes, max_lines=50)
    
    lines = excerpt.splitlines()
    assert len(lines) == 50
    assert lines[0] == "Line 101"
    assert lines[-1] == "Line 150"


def test_extract_failure_excerpt_empty_zip():
    """Test handling of empty zip archive."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        pass  # Empty zip
    
    logs_bytes = zip_buffer.getvalue()
    
    excerpt = extract_failure_excerpt(logs_bytes)
    
    assert excerpt == "[No log files found in archive]"


def test_extract_failure_excerpt_unicode_error():
    """Test handling of logs with encoding issues."""
    # Create bytes with invalid UTF-8 sequences
    logs_bytes = b"Valid text\n\xff\xfeInvalid UTF-8\nMore text"
    
    excerpt = extract_failure_excerpt(logs_bytes)
    
    assert "Valid text" in excerpt
    assert "More text" in excerpt


def test_extract_failure_excerpt_short_logs():
    """Test extraction when logs are shorter than max_lines."""
    log_content = "\n".join([f"Line {i}" for i in range(1, 11)])
    logs_bytes = log_content.encode("utf-8")
    
    excerpt = extract_failure_excerpt(logs_bytes, max_lines=50)
    
    lines = excerpt.splitlines()
    assert len(lines) == 10
    assert lines[0] == "Line 1"
    assert lines[-1] == "Line 10"


def test_extract_failure_excerpt_multiple_files_in_zip():
    """Test extraction from zip with multiple log files (takes first)."""
    log_content_1 = "First log file content\nLine 2\nLine 3"
    log_content_2 = "Second log file content"
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('0_job.txt', log_content_1.encode('utf-8'))
        zf.writestr('1_job.txt', log_content_2.encode('utf-8'))
    
    logs_bytes = zip_buffer.getvalue()
    
    excerpt = extract_failure_excerpt(logs_bytes)
    
    assert "First log file content" in excerpt
    assert "Second log file content" not in excerpt
