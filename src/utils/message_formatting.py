"""Utility functions for formatting CPDLC messages."""

import re


def extract_message_content(raw_content):
    """Remove metadata prefix from CPDLC message content."""
    if not raw_content or not isinstance(raw_content, str):
        return raw_content

    # Handle multiple possible formats:
    # 1. Standard format: /data2/25//WU/ACTUAL MESSAGE HERE
    # 2. Logon format: /data2/19/1/NE/LOGON ACCEPTED
    pattern = r"^/data\d+/\d+(?:/\d+/\w+/|//\w+/)"

    cleaned_content = re.sub(pattern, "", raw_content)
    return cleaned_content


def format_list_text(text):
    """Format message text for compact list display."""
    if not text or not isinstance(text, str):
        return text

    # Replace @ with spaces for a compact list display
    return text.replace("@", " ")


def format_message_text(text):
    """Format message text with proper line breaks for detailed view."""
    if not text or not isinstance(text, str):
        return text

    try:
        # Split by @ characters
        segments = text.split("@")

        # Process segments for better formatting
        formatted_lines = []
        current_line = segments[0].strip() if segments else ""

        for i in range(1, len(segments)):
            segment = segments[i].strip()

            # Skip empty segments
            if not segment:
                continue

            # Handle punctuation
            if current_line and current_line[-1] in ".,":
                # If current line ends with punctuation, it's complete
                formatted_lines.append(current_line)
                current_line = segment
            elif segment and segment[0] in ".,":
                # If segment starts with punctuation, append it to current line
                current_line += segment
                formatted_lines.append(current_line)
                current_line = ""
            else:
                # Normal case - append segments with a space
                if current_line:
                    # Only add a space if there's existing content
                    formatted_lines.append(current_line)
                current_line = segment

        # Add the last line if it has content
        if current_line:
            formatted_lines.append(current_line)

        # Join with newlines
        return "\n".join(formatted_lines)
    except Exception as e:
        # If any error occurs during formatting, return the original text
        # This ensures the function doesn't fail even with unexpected input
        return text
