def extract_failure_excerpt(logs_bytes: bytes, max_lines: int = 100) -> str:
    """Extract a concise excerpt from failure logs.
    
    Currently returns the last N lines of the log to capture the failure context.
    Future improvements could use smarter pattern matching to find error messages.
    """
    try:
        logs_text = logs_bytes.decode("utf-8")
    except UnicodeDecodeError:
        logs_text = logs_bytes.decode("utf-8", errors="replace")
    
    lines = logs_text.splitlines()
    
    # Take the last max_lines to capture the failure context
    excerpt_lines = lines[-max_lines:] if len(lines) > max_lines else lines
    
    return "\n".join(excerpt_lines)
