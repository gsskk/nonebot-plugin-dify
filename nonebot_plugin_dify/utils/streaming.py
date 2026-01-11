from typing import Generator


class StreamingBuffer:
    def __init__(self, min_char: int):
        self.buffer = ""
        self.min_char = min_char
        self.in_code_block = False

    def process(self, chunk: str) -> Generator[str, None, None]:
        if not chunk:
            return

        self.buffer += chunk

        # Determine code block state
        # Simple heuristic: count occurrences of ```. If odd, toggle state.
        # This is a basic tracking mechanism.
        backtick_count = chunk.count("```")
        if backtick_count % 2 != 0:
            self.in_code_block = not self.in_code_block

        if self.in_code_block:
            # Inside a code block, do not split.
            return

        # Split on newlines if buffer is long enough
        while "\n" in self.buffer:
            split_index = self.buffer.find("\n")

            # Check length of potential segment
            segment = self.buffer[:split_index].strip()

            if len(segment) >= self.min_char:
                # Valid segment found
                # Also check if it looks like a complete sentence or logical block
                yield segment
                self.buffer = self.buffer[split_index + 1 :]
            else:
                # Segment too short, but we hit a newline.
                # If we have multiple newlines, maybe combine?
                # For now, just keep buffering until next newline or sufficient length.
                # BUT: If we don't consume the newline, we might get stuck loop if we always find the same newline.

                # Correction: If we hit a newline, it's usually a safe split point regardless of length
                # UNLESS it's truly tiny (like empty lines).
                # Requirement says: buffer until combined content exceeds limit.

                # Let's try to look ahead for more newlines?
                # Simpler approach:
                # If current segment < min_char, we want to KEEP it in buffer attached to next line.
                # But we must consume the \n otherwise find("\n") returns same index.

                # Wait, if I consume \n, I lose the separation.
                # Implementation choice: Replace \n with space? Or just keep it?
                # If I keep it in buffer but move past it?

                # Let's refine the logic:
                # We want to yield ONLY when we have enough chars AND a newline (or stream end).

                # If self.buffer is "Hi\n", len=2 < 10.
                # We should NOT yield "Hi".
                # We should wait for more data "Hi\nHow are you\n" -> "Hi\nHow are you".

                # So we can't just use `while '\n' in self.buffer`.
                # We need to find the *first eligible* newline.

                temp_buffer = self.buffer

                # Iterate through all newlines
                start = 0
                found_split = False

                while True:
                    idx = temp_buffer.find("\n", start)
                    if idx == -1:
                        break

                    potential_segment_len = idx

                    if potential_segment_len >= self.min_char:
                        # Found a valid split point at 'idx'
                        segment_to_yield = self.buffer[:idx].strip()
                        if segment_to_yield:
                            yield segment_to_yield

                        self.buffer = self.buffer[idx + 1 :]
                        found_split = True
                        break  # Break inner loop to restart 'while "\n"' check on new buffer

                    # Not long enough, keep searching further in buffer
                    start = idx + 1

                if not found_split:
                    # No suitable newline found in current buffer
                    break

    def flush(self) -> Generator[str, None, None]:
        if self.buffer.strip():
            yield self.buffer.strip()
        self.buffer = ""
