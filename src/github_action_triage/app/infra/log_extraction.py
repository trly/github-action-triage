import io
import zipfile


def extract_failure_excerpt(logs_bytes: bytes, max_lines: int = 100) -> str:
    """Extract a concise excerpt from failure logs.

    Handles both plain text and zipped GitHub log archives.
    Returns the last N lines of the log to capture the failure context.
    Future improvements could use smarter pattern matching to find error messages.
    """
    # GitHub API returns logs as a zip archive
    # Try to extract from zip first
    try:
        with zipfile.ZipFile(io.BytesIO(logs_bytes)) as zf:
            # GitHub typically names the log file inside the zip
            # Get the first (and usually only) file in the archive
            file_list = zf.namelist()
            if not file_list:
                return "[No log files found in archive]"

            # Read the first log file
            with zf.open(file_list[0]) as log_file:
                logs_bytes = log_file.read()
    except zipfile.BadZipFile:
        # Not a zip file, treat as plain text
        pass

    # Decode the log content
    try:
        logs_text = logs_bytes.decode("utf-8")
    except UnicodeDecodeError:
        logs_text = logs_bytes.decode("utf-8", errors="replace")

    lines = logs_text.splitlines()

    # Take the last max_lines to capture the failure context
    excerpt_lines = lines[-max_lines:] if len(lines) > max_lines else lines

    return "\n".join(excerpt_lines)
