from datetime import datetime
from typing import List, Dict


def simplify_time(timestamp_str: str) -> str:
    """
    Simplify timestamp to HH:MM (if today) or MM-DD HH:MM (if earlier).
    """
    try:
        dt = datetime.fromisoformat(timestamp_str)
        now = datetime.now()
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        else:
            return dt.strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return ""


def format_history(messages: List[Dict], max_length: int, image_mode: str = "placeholder") -> str:
    """
    Format chat history into a unified XML structure with compression for repeated messages.

    Format:
    <msg role="user" name="nickname(id)" time="HH:MM" count="N">[image]. Message content</msg>
    """
    if not messages:
        return ""

    # Pre-process for compression: Group consecutive identical messages
    # We iterate and build a list of (msg_data, count) tuples
    grouped_msgs = []

    current_group = None

    for msg in messages:
        # Normalize fields for comparison
        user_id = str(msg.get("user_id", ""))
        role = msg.get("role", "unknown")
        content = msg.get("message", "")
        # For simplicity, we consider it a repeat if user, role, content, and image status match.
        # We construct a comparison key
        has_image = msg.get("has_image", False)

        # Determine image marker for comparison/output
        image_marker = ""
        if has_image and image_mode != "none":
            if image_mode == "description" and msg.get("image_description"):
                image_marker = f"[image: {msg.get('image_description')}] "
            else:
                image_marker = "[image] "

        full_content = f"{image_marker}{content}"

        # We use the timestamp of the *first* message in the group

        if current_group:
            # Check if match
            prev_msg, count = current_group
            prev_user_id = str(prev_msg.get("user_id", ""))
            prev_role = prev_msg.get("role", "")
            prev_content_raw = prev_msg.get("message", "")
            prev_has_image = prev_msg.get("has_image", False)

            # Reconstruct content logic for prev to compare
            prev_image_marker = ""
            if prev_has_image and image_mode != "none":
                if image_mode == "description" and prev_msg.get("image_description"):
                    prev_image_marker = f"[image: {prev_msg.get('image_description')}] "
                else:
                    prev_image_marker = "[image] "
            prev_full_content = f"{prev_image_marker}{prev_content_raw}"

            if user_id == prev_user_id and role == prev_role and full_content == prev_full_content:
                # It's a match, increment count
                current_group = (prev_msg, count + 1)
                continue
            else:
                # Not a match, push current_group and start new
                grouped_msgs.append(current_group)
                current_group = (msg, 1)
        else:
            current_group = (msg, 1)

    if current_group:
        grouped_msgs.append(current_group)

    # Now format the grouped messages
    total_length = 0
    final_lines = []

    # Process in reverse to handle length limit, then reverse back
    for msg, count in reversed(grouped_msgs):
        role = msg.get("role", "user")
        user_id = msg.get("user_id", "")
        nickname = msg.get("nickname", "user")
        timestamp = msg.get("timestamp", "")
        content = msg.get("message", "")

        # Simplified time
        time_str = simplify_time(timestamp)

        # Image marker
        has_image = msg.get("has_image", False)
        image_marker = ""
        if has_image and image_mode != "none":
            if image_mode == "description" and msg.get("image_description"):
                image_marker = f"[image: {msg.get('image_description')}] "
            else:
                image_marker = "[image] "

        full_content = f"{image_marker}{content}"

        # Build XML attributes
        # <msg role="user" name="nickname(id)" time="time_str" count="N">content</msg>

        # Attributes
        name_attr = f"{nickname}({user_id})"
        attrs = [f'role="{role}"', f'name="{name_attr}"']
        if time_str:
            attrs.append(f'time="{time_str}"')
        if count > 1:
            attrs.append(f'count="{count}"')

        attr_str = " ".join(attrs)

        line = f"<{role} {attr_str}>{full_content}</{role}>"

        # Check length limit
        # We are building from newest to oldest
        line_len = len(line) + 1  # newline
        if max_length > 0 and total_length + line_len > max_length:
            break

        final_lines.insert(0, line)
        total_length += line_len

    return "\n".join(final_lines)
