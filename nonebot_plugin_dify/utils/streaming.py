from typing import Generator


class StreamingBuffer:
    def __init__(self, min_char: int):
        self.buffer = ""
        self.min_char = min_char
        self.in_code_block = False

    def _is_safe_to_split(self, segment: str) -> bool:
        """
        Check if the segment is safe to split (balanced markdown/brackets).
        """
        # Check for code blocks (should already be handled by process loop, but good to be safe)
        if segment.count("```") % 2 != 0:
            return False

        # Check for Bold (**text**)
        # Note: This is a simple parity check. It works for strictly paired markers.
        if segment.count("**") % 2 != 0:
            return False

        # Check for Inline Code (`text`)
        if segment.count("`") % 2 != 0:
            return False

        # Check for full-width brackets （text）- common in Chinese context
        if segment.count("（") != segment.count("）"):
            return False

        # Check for standard brackets (text)
        if segment.count("(") != segment.count(")"):
            return False

        return True

    def process(self, chunk: str) -> Generator[str, None, None]:
        if not chunk:
            return

        self.buffer += chunk

        # Quick check for code block state to prevent scanning huge blocks unnecessarily
        # This global state tracks if we are GLOBALLY inside a code block across chunks
        # But we also need to handle code blocks starting/ending WITHIN the buffer.

        # Actually, simpler approach:
        # We always scan the CURRENT buffer for the best split point.
        # If the buffer starts inside a code block, we must wait for it to close.

        # Let's refine the logic:
        # We iterate through newlines. For each candidate split point, we check:
        # 1. Is it outside a code block?
        # 2. Is the content up to this point "balanced"?
        # 3. Is it long enough?

        temp_buffer = self.buffer
        start = 0

        # Define punctuation that shouldn't start a line (orphan check)
        # Includes standard and full-width punctuation
        ORPHAN_PUNCTUATION = {
            "?",
            "!",
            ".",
            ",",
            ";",
            ":",
            ")",
            "]",
            "}",
            "？",
            "！",
            "。",
            "，",
            "；",
            "：",
            "）",
            "】",
            "”",
            "’",
            "…",
            "、",
        }

        while True:
            idx = temp_buffer.find("\n", start)
            if idx == -1:
                break

            # Lookahead Check 1: Do not split if the buffer ends exactly at newline.
            # We don't know what comes next, so we must wait for more data to check for punctuation.
            if idx == len(temp_buffer) - 1:
                break

            # Lookahead Check 2: Check if the character after newline is an orphan punctuation
            # We skip whitespace to find the first meaningful char
            next_char_idx = idx + 1
            while next_char_idx < len(temp_buffer) and temp_buffer[next_char_idx].isspace():
                next_char_idx += 1

            if next_char_idx < len(temp_buffer):
                next_char = temp_buffer[next_char_idx]
                if next_char in ORPHAN_PUNCTUATION:
                    # Found orphan punctuation after newline!
                    # Treat this newline as unsafe.
                    start = idx + 1
                    continue
            else:
                # We reached end of buffer while skipping spaces.
                # We still don't know the next meaningful char.
                # Wait for more data.
                break

            # Candidate segment (including the newline check logic from before)
            # Actually, we should look for the *first* Valid split.

            # Check length from start of buffer (since we yield from start)
            # The 'idx' is relative to temp_buffer relative to start... wait.
            # temp_buffer.find return index in temp_buffer.

            split_index = idx
            candidate_segment = temp_buffer[:split_index]  # Exclude newline for checking?
            # Usually we yield the line without newline if we are stripping, or with?
            # Original code: segment = self.buffer[:split_index].strip()

            # But we must ensure the *consumed* part leaves us in a clean state.

            # Re-eval global code block state?
            # The `self.in_code_block` helps if a code block spans MULTIPLE chunks.
            # But detecting it strictly by simple count per chunk is risky if chunk splits inside "```".
            # Assuming chunks don't split tokens like "`" + "``".

            # Let's rely on calculating "balancedness" of the candidate segment combined with current state?
            # No, `_is_safe_to_split` on the candidate segment is self-contained.
            # BUT: if `self.in_code_block` is True, then we are currently IN a block.
            # We need to find "```" to exit.

            # If we are in code block, we only switch out if we find "```".
            # Markdown code blocks can contain anything.

            # Let's count "```" in candidate_segment.
            triple_ticks = candidate_segment.count("```")

            current_in_code_block = self.in_code_block
            if current_in_code_block:
                # We need an ODD number of triple ticks to toggle OUT of code block state
                # to consider this segment complete?
                # Actually, if we are in code block, we only split if the block ENDS in this segment.
                # i.e. we found a closing ```.

                # Effectively: `effective_ticks = (1 if in_block else 0) + triple_ticks`
                # If effective_ticks is even, satisfied.

                if triple_ticks % 2 == 0:
                    # Still in code block (Odd total state). Not safe.
                    # Unless we allow splitting INSIDE code blocks?
                    # Generally streaming code blocks line-by-line is fine!
                    # Actually, usually code blocks ARE split by newline for rendering.
                    # Text-based streaming usually WANTS code blocks line-by-line.

                    # Markdown renderers (like in web UIs) often handle streaming code blocks fine IF they get lines.
                    # Breaking markdown TEXT (bold) is bad. Breaking CODE lines is usually OK.
                    pass
                else:
                    # Toggled state.
                    pass

            # Wait, the user complaint is about markdown formatting in TEXT.
            # Code blocks are usually robust to line splits.
            # So maybe we IGNORE code block state for splitting,
            # UNLESS the user explicitly wants to buffer whole code blocks (which takes forever).
            # The original code had specific logic to NOT split in code blocks.
            # Let's preserve that "don't split inside code block" logic if that was the intent.
            # Intent: "In code block, do not split." -> Means wait for whole block?
            # That delays output a lot.

            # Re-reading original code:
            # if self.in_code_block: return

            # This implies the original author wanted to BUFFER code blocks fully?
            # Or just wait for the next toggle?
            # If I stick to original logic:

            # Check global state update based on what we are about to consume?
            # No, that's complex.

            # Simplification:
            # We want to yield `candidate_segment`.
            # Is it safe?
            # 1. Check local balance (bold, italic, code).
            # 2. Update global code block state only when we actually yield?

            # Let's just correct the 'process' loop to search forward for a SAFE newline.

            segment_payload = candidate_segment.strip()
            # Check length
            if len(segment_payload) < self.min_char:
                # Too short, skip this newline, look for next
                start = idx + 1
                continue

            # Check MD Safety
            # We pass the full raw segment (including leading spaces) to check balance?
            # Or just the payload?
            # Balance checks should be on the content we stick in the UI.
            # If we strip, we might lose context?
            # `** text **  ` -> strip -> `** text **`. Balanced.
            # `** text  ` -> strip -> `** text`. Unbalanced.
            # Seems safe to check stripped or raw. Raw is safer for '`' counts.

            if not self._is_safe_to_split(candidate_segment):
                # Unbalanced! Skip this newline.
                start = idx + 1
                continue

            # Also check code block state?
            # Original code: `backtick_count = chunk.count("```")`... simplistic tracking.
            # Using simple parity check on the candidate segment:
            if self.in_code_block:
                # We are inside. We need to find a closing ``` in this segment to get out.
                # If we don't find it, we are still inside.
                # Should we split inside?
                # If we assume we CAN split inside code blocks (lines), then checking `**` inside code is pointless (it's literal).
                # But `_is_safe_to_split` assumes markdown semantics.
                # Inside code, `**` is just chars.

                # If we decide to allow splitting inside code blocks:
                # We should NOT check `_is_safe_to_split` (it yields false positives/negatives).
                # We just check length.

                # So:
                # If in_code_block:
                #    Check if we exit block (count ```).
                #    If we stay in block -> Just split on newline (ignore safety).
                #    If we exit block -> We are now normal. Check safety of the AFTER part?

                # This is getting complicated.
                # Let's stick to: "Ideally don't split inside code blocks to ensure highlighting works?"
                # Or just fix the TEXT splitting issue.

                # Fix: Just use `_is_safe_to_split`. If it returns False, we don't split.
                # Inside a code block, `**` is rare. `(` `)` are common.
                # `if count('(') != count(')')` will return False often in code.
                # THIS WILL CAUSE INTOLERABLE DELAY in code blocks if we enforce balance!
                # (e.g. `func(a,` -> newline -> `b)`)

                # CONCLUSION: behavior MUST differ inside/outside code blocks.
                pass

            # Count triple ticks in this specific segment to update state
            triple_ticks = candidate_segment.count("```")
            # Determine state change IF we yielded this segment
            will_be_in_code_block = self.in_code_block
            if triple_ticks % 2 != 0:
                will_be_in_code_block = not will_be_in_code_block

            # If we are currently in code block (before this segment ends or toggles)
            # `self.in_code_block` is True.
            # If `self.in_code_block` is True, we should SKIP the balancing check.
            # Because code is often unbalanced line-by-line.

            # BUT, we need to know if we *entered* a code block in this segment.
            # `text... \n ```python\n ...`
            # `candidate_segment` has `text... \n ```python`.
            # `in_code_block` was False.
            # `triple_ticks` = 1.
            # `will_be` = True.

            # We want to be safe in the `text` part.
            # But the `text` part is mixed with code block start.

            # Simplified Logic:
            # 1. Update `in_code_block` state based on the segment we are considering.
            # 2. If we ARE in a code block, skip balance checks (allow line split).
            # 3. If we are NOT in a code block, convert balance checks.

            # Wait, if `candidate_segment` toggles state, which state applies?
            # "Is safe to split" implies the *boundary* (the newline) is a safe place to stop.
            # If we end *inside* a code block (state=True at end), implies we just emitted a line of code.
            # That is safe.
            # If we end *outside* (state=False at end), implies we emitted text or finished a block.
            # We must ensure the text was balanced.

            # So: Check state AT THE END of segment.
            # If `will_be_in_code_block` is True:
            #   Safe to split (it's code).
            # If `False`:
            #   Check `_is_safe_to_split(candidate_segment)`.

            # One Catch: `candidate_segment` might contain `**bold` <Start Code Block> `code` <End Code Block>.
            # State at end is False.
            # `_is_safe_to_split` checks `**`. Returns False. Correct.
            # Checks `code`. Balanced. Correct.

            # Catch 2: `**bold` <Start Code> `code...` (newline inside block).
            # State at end is True.
            # We accept it.
            # But we leave `**` dangling?
            # `**bold ``` code line 1`.
            # If we yield this, the next chunk is `code line 2`.
            # The renderer receives `**bold ``` code line 1`.
            # It sees `**` (open bold). Then ` ``` ` (code block).
            # Markdown rules: code blocks might disable bold parsing?
            # Either way, if we yield the `**` token, we commit to it.
            # If the user intended `**` to wrap the whole code block...
            # `**bold ```...```**`
            # Then splitting mid-code-block breaks the `**` because the first message is unclosed.
            # BUT, Dify/LLMs usually output streaming text.
            # If we split, the UI usually appends.
            # The "strange segmentation" issue is when the newline makes the UI render the first part *prematurely* as a block.
            # `*   **风` -> Rendered as list item with Bold `风` (and unclosed bold).
            # Next msg: `力...` -> Rendered as plain text?
            # If the UI resets context per message chunk (unlikely for stream, but possible if it parses per chunk independently?).
            # If it's a raw stream, splitting shouldn't matter eventually.
            # BUT the user screenshot/description implies "strange segmentation".
            # This implies visual glitches or the final rendering has forced newlines.

            # If the user says "strange segmentation", and logs show `Ready to send TEXT: ...`,
            # it implies the BOT is sending separate messages to the Chat Platform (Telegram/Discord/QQ).
            # Most chat platforms treating each "send" as a Bubble.
            # Ah! NoneBot adapters usually send separate messages if you call `send` multiple times?
            # OR `dify_bot.reply` yields chunks, and `handle_message` calls `send` for EACH chunk?

            # `handlers/message.py`:
            # `async for reply_type, reply_content in dify_bot.reply(...):`
            #     `await final_msg.send(target=target, bot=bot)`

            # YES. EACH CHUNK IS A SEPARATE MESSAGE.
            # In Telegram/QQ, that means separate bubbles.
            # `*   **风` [Bubble 1]
            # `力：** ...` [Bubble 2]
            # Markdown IS NOT SHARED across bubbles.
            # So `**` in Bubble 1 is UNCLOSED. It renders as `**风`.
            # Bubble 2 has `力：**`. Renders as `力：**`.
            # Result: `**风` `力：**`. No bold.

            # THIS IS THE CORE ISSUE.
            # We MUST ensure each bubble is self-contained valid markdown OR we accept that formatting breaks across bubbles.
            # To fix "strange separation", we must buffer until we have a safe "Bubble Boundary".

            # So `will_be_in_code_block` check is NOT enough if we wrap code in bold (rare/invalid?).
            # But definitely:
            # 1. We cannot splitting inside `**` ... `**`.
            # 2. We cannot split inside `(` ... `)`.
            # 3. If we are in a code block, we *can* split bubble?
            #    If we split bubble inside code block:
            #    Msg 1: ```python \n def foo():
            #    Msg 2:     print("hi") \n ```
            #    Bubble 1: Renders as unclosed code block (often works, auto-closed by UI).
            #    Bubble 2: Renders as plain text `print("hi")` ?? Or unclosed code block?
            #    Usually Bubble 2 is just text.
            #    So the code highlighting BREAKS.

            # SO: We Should NOT split inside code blocks EITHER if possible.
            # But code blocks can be huge.
            # If we don't split, we might hit message length limits (Telegram 4096 chars).

            # Compromise:
            # Prioritize correctness.
            # If in code block, accumulate until 1000 chars? Or just wait for end?
            # The current task focuses on the User's specific example: `**` and `（`.
            # So, Strict Balance check is the way.
            # If code block is long, we might buffer a lot.
            # NOTE: `dify_bot.py` or platform adapters often have auto-split for long messages too?
            # Check `config.message_max_length = 200`.
            # Wait, `StreamingBuffer` deals with "stream min char".
            # `handlers/message.py` loop sends EACH chunk.

            # If we create a HUGE chunk, `UniMessage` might split it?
            # Or formatting might be too large.

            # Let's trust that balancing is the right fix for formatting issues.
            # And `StreamingBuffer` should ideally yield "Physical Line" of code if inside code block?
            # No, if we send line-by-line in separate bubbles, code formatting breaks.
            # `Msg1: ```\nCode` -> `Msg2: Code\n````.
            # Msg2 is not formatted.

            # So correct behavior for code is:
            # BUFFER THE WHOLE CODE BLOCK if possible.
            # If it's too big, we are screwed purely by platform limitations anyway.

            # So my logic:
            # `if will_be_in_code_block: continue` (Don't split).
            # `if not _is_safe_to_split: continue` (Don't split).
            # Only split when Safe AND Not in code block.

            # Refined Loop:

            segment_payload = candidate_segment.strip()
            if len(segment_payload) < self.min_char:
                start = idx + 1
                continue

            # Check Code Block Status
            triple_ticks = candidate_segment.count("```")
            # Calculate what the state WOULD be at the end of this segment
            # Starting from `self.in_code_block`
            # Assuming `triple_ticks` toggles it.
            future_in_code_block = self.in_code_block
            if triple_ticks % 2 != 0:
                future_in_code_block = not future_in_code_block

            if future_in_code_block:
                # We would end inside a code block.
                # Don't split. Wait for block to close.
                start = idx + 1
                continue

            # We would end OUTSIDE a code block.
            # Ensure the text is balanced.
            if not self._is_safe_to_split(candidate_segment):
                start = idx + 1
                continue

            # SAFE TO SPLIT
            yield candidate_segment.strip()
            self.buffer = self.buffer[idx + 1 :]

            # Update state properly
            # We just consumed `candidate_segment` + `\n`.
            # Does `\n` affect state? No.
            self.in_code_block = future_in_code_block  # Should be False if we passed check

            # Restart search from 0 in new buffer
            temp_buffer = self.buffer
            start = 0

    def flush(self) -> Generator[str, None, None]:
        if self.buffer.strip():
            yield self.buffer.strip()
        self.buffer = ""
        self.in_code_block = False
