
import json
import re
import time

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL


# ==========================================
# SETTINGS
# ==========================================

MAX_ATTEMPTS = 4
INITIAL_RETRY_DELAY = 3

GEMINI_TIMEOUT_MS = 90000

MINIMUM_CLIP_SCORE = 7.0
MINIMUM_PAYOFF_SCORE = 7.5
MINIMUM_STORYTELLING_SCORE = 7.0

MIN_CLIP_DURATION = 25
MAX_CLIP_DURATION = 110

MAX_STORY_SEGMENTS = 3
MIN_SEGMENT_DURATION = 5.0

PREFER_CONTINUOUS_STORIES = True

REQUIRED_SCORES = [
    "curiosity",
    "storytelling",
    "payoff",
    "emotion",
    "entertainment",
]

SCORE_WEIGHTS = {
    "curiosity": 0.25,
    "storytelling": 0.25,
    "payoff": 0.20,
    "emotion": 0.15,
    "entertainment": 0.15,
}

VALID_ENDING_TYPES = {
    "resolution",
    "revelation",
    "answer",
    "punchline",
    "conclusion",
}


# ==========================================
# GEMINI
# ==========================================

def _get_client():

    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is missing. Add it to your .env file."
        )

    return genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(
            timeout=GEMINI_TIMEOUT_MS,
        ),
    )


def _extract_json(text):

    if not text:
        raise ValueError("Gemini returned an empty response.")

    text = text.strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    return json.loads(text)


def _is_temporary_error(exc):

    error_message = str(exc).lower()
    error_name = type(exc).__name__.lower()

    temporary_codes = (
        "429",
        "500",
        "502",
        "503",
        "504",
    )

    if any(code in error_message for code in temporary_codes):
        return True

    timeout_indicators = (
        "timeout",
        "timed out",
        "deadline exceeded",
        "readtimeout",
        "connecttimeout",
    )

    if any(
        indicator in error_message or indicator in error_name
        for indicator in timeout_indicators
    ):
        return True

    return False


def _generate_with_retry(client, prompt, task_name):

    for attempt in range(1, MAX_ATTEMPTS + 1):

        started_at = time.monotonic()

        try:

            print(
                f"\n[Gemini] {task_name} "
                f"(attempt {attempt}/{MAX_ATTEMPTS})..."
            )

            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )

            elapsed = time.monotonic() - started_at

            if not response.text:
                raise ValueError(
                    "Gemini returned an empty response."
                )

            print(
                f"[Gemini] Request completed in {elapsed:.1f}s."
            )

            return response.text

        except Exception as exc:

            elapsed = time.monotonic() - started_at

            temporary_error = _is_temporary_error(exc)

            print(
                f"[Gemini] Request failed after {elapsed:.1f}s: "
                f"{type(exc).__name__}: {exc}"
            )

            if not temporary_error or attempt == MAX_ATTEMPTS:
                raise

            delay = INITIAL_RETRY_DELAY * (2 ** (attempt - 1))

            print(
                f"[Gemini] Temporary API error. "
                f"Retrying in {delay} seconds..."
            )

            time.sleep(delay)

    raise RuntimeError(
        "Gemini request failed after all attempts."
    )


# ==========================================
# TRANSCRIPT UTILITIES
# ==========================================

def _normalize_text(text):

    return " ".join(
        re.findall(r"[a-z0-9]+", str(text).lower())
    )


def _valid_transcript_segments(transcript_segments):

    valid = []

    for segment in transcript_segments:

        try:

            start = float(segment["start"])
            end = float(segment["end"])
            text = str(segment.get("text", "")).strip()

            if end <= start or not text:
                continue

            valid.append({
                "start": start,
                "end": end,
                "text": text,
            })

        except (KeyError, TypeError, ValueError):
            continue

    return sorted(valid, key=lambda item: item["start"])


def _get_range_transcript(
    transcript_segments,
    start,
    end,
):

    selected = []

    for segment in transcript_segments:

        if (
            segment["end"] > start
            and segment["start"] < end
        ):

            selected.append(segment["text"])

    return " ".join(selected)


def _get_clip_transcript(
    transcript_segments,
    selected_segments,
):

    parts = []

    for selected in selected_segments:

        text = _get_range_transcript(
            transcript_segments,
            selected["start"],
            selected["end"],
        )

        if text:
            parts.append(text)

    return " ".join(parts)


def _snap_to_transcript_boundaries(
    start,
    end,
    transcript_segments,
):

    overlapping = [
        segment
        for segment in transcript_segments
        if (
            segment["end"] > start
            and segment["start"] < end
        )
    ]

    if not overlapping:
        raise ValueError(
            "Selected range contains no transcript."
        )

    return (
        overlapping[0]["start"],
        overlapping[-1]["end"],
    )


def _quote_is_present(
    quotation,
    transcript_text,
    minimum_words=4,
):

    quote_words = _normalize_text(quotation).split()
    transcript_words = _normalize_text(transcript_text).split()

    if len(quote_words) < minimum_words:
        return False

    size = len(quote_words)

    for index in range(
        len(transcript_words) - size + 1
    ):

        if transcript_words[index:index + size] == quote_words:
            return True

    return False


def _ending_evidence_is_valid(
    evidence,
    final_segment_transcript,
):

    quote_words = _normalize_text(evidence).split()
    transcript_words = _normalize_text(
        final_segment_transcript
    ).split()

    if len(quote_words) < 4 or not transcript_words:
        return False

    size = len(quote_words)

    for index in range(
        len(transcript_words) - size + 1
    ):

        if transcript_words[index:index + size] != quote_words:
            continue

        ending_position = (
            index + size
        ) / len(transcript_words)

        return ending_position >= 0.70

    return False


# ==========================================
# SEGMENT VALIDATION
# ==========================================

def _validate_story_segments(
    raw_segments,
    episode_duration,
    transcript_segments,
):

    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("Missing story segments.")

    if len(raw_segments) > MAX_STORY_SEGMENTS:
        raise ValueError("Too many cuts.")

    validated = []
    previous_end = -1.0

    for index, item in enumerate(raw_segments):

        if not isinstance(item, dict):
            raise ValueError("Invalid segment structure.")

        start = float(item["start"])
        end = float(item["end"])

        if start < 0 or end <= start:
            raise ValueError("Invalid timestamps.")

        if end > episode_duration:
            raise ValueError("Segment exceeds episode duration.")

        if start < previous_end:
            raise ValueError("Segments overlap or are out of order.")

        if index > 0:

            cut_reason = str(
                item.get("cut_reason", "")
            ).strip()

            if len(cut_reason) < 15:
                raise ValueError(
                    "A cut has no meaningful explanation."
                )

        start, end = _snap_to_transcript_boundaries(
            start,
            end,
            transcript_segments,
        )

        if start < previous_end:
            raise ValueError(
                "Snapped segments overlap."
            )

        segment_duration = end - start

        if segment_duration < MIN_SEGMENT_DURATION:
            raise ValueError(
                "Segment is too short."
            )

        validated.append({
            "start": round(start, 3),
            "end": round(end, 3),
        })

        previous_end = end

    total_duration = sum(
        item["end"] - item["start"]
        for item in validated
    )

    if not MIN_CLIP_DURATION <= total_duration <= MAX_CLIP_DURATION:
        raise ValueError(
            f"Final duration is {total_duration:.1f}s."
        )

    return validated


# ==========================================
# SCORING
# ==========================================

def _calculate_score(scores):

    return round(
        sum(
            float(scores[key]) * SCORE_WEIGHTS[key]
            for key in REQUIRED_SCORES
        ),
        2,
    )


# ==========================================
# STORY REVIEW
# ==========================================

def _review_candidates(
    client,
    transcript_text,
    candidates,
):

    if not candidates:
        return []

    review_items = []

    for index, clip in enumerate(candidates):

        selected = _get_clip_transcript(
            clip["_transcript_segments"],
            clip["segments"],
        )

        gaps = []

        for gap_index in range(
            len(clip["segments"]) - 1
        ):

            first = clip["segments"][gap_index]
            second = clip["segments"][gap_index + 1]

            gap_text = _get_range_transcript(
                clip["_transcript_segments"],
                first["end"],
                second["start"],
            )

            cut_reasons = clip.get("_cut_reasons", [])
            reason_for_removal = (
                cut_reasons[gap_index]
                if gap_index < len(cut_reasons)
                else (
                    "Intervening dialogue was removed to connect "
                    "the selected story sections."
                )
            )

            gaps.append({
                "between_segments": gap_index + 1,
                "removed_dialogue": gap_text,
                "reason_for_removal": reason_for_removal,
            })

        review_items.append({
            "candidate_index": index,
            "title": clip["title"],
            "hook": clip["hook"],
            "selected_story": selected,
            "removed_gaps": gaps,
            "ending_type": clip["ending_type"],
            "ending_evidence": clip["ending_evidence"],
            "conclusion_summary": clip["conclusion_summary"],
        })

    prompt = f"""
You are a strict narrative editor reviewing proposed short videos.

Your job is to reject clips that are confusing, incomplete,
abruptly cut, or missing their actual conclusion.

You have the FULL ORIGINAL TRANSCRIPT and the proposed
selected dialogue for each clip.

FULL ORIGINAL TRANSCRIPT:
{transcript_text}

PROPOSED CLIPS:
{json.dumps(review_items, ensure_ascii=False)}

For EACH candidate, evaluate:

1. CONTEXT:
Can a viewer understand who and what the story is about?

2. CONTINUITY:
Does the selected dialogue flow naturally?
Does each new section make sense immediately after the previous one?

3. REMOVED MATERIAL:
Read the removed dialogue between cuts.
Was it genuinely irrelevant?
Could it contain necessary context, an explanation, a reaction,
a missing event, or part of the conclusion?

4. PROGRESSION:
Does the story actually develop from beginning to end?

5. CONCLUSION:
Does the selected clip contain the REAL outcome?
Does the speaker finish the story?
Does the ending evidence demonstrate that the story is over,
rather than merely suggesting what might happen next?

6. FINAL CUT:
Does the clip stop after the conclusion?
Is there an unfinished sentence, interrupted answer,
missing reaction, or obvious continuation?

STRICT RULES:

- Do not approve a clip merely because it has an ending quotation.
- A decision to report something is not the same as the final outcome.
- A promise to reveal something is not the revelation.
- A question is not an answer.
- A setup for a punchline is not the punchline.
- A dramatic statement is not necessarily a conclusion.
- If a cut removes necessary dialogue, reject the clip.
- If the story continues after the selected ending, reject it.
- If the ending is ambiguous, reject it.
- If the clip feels stitched together, reject it.
- Do not approve a clip simply because its title sounds interesting.

Approve ONLY when the entire selected clip works as a
standalone story with a genuine ending.

Return ONLY valid JSON:

{{
    "reviews": [
        {{
            "candidate_index": 0,
            "approved": true,
            "context_clear": true,
            "continuity_clear": true,
            "conclusion_complete": true,
            "ending_is_final": true,
            "cut_quality": "natural",
            "reason": "Brief explanation of why the story is complete."
        }}
    ]
}}

If uncertain, reject.
"""

    response_text = _generate_with_retry(
        client,
        prompt,
        "Reviewing story continuity and conclusions",
    )

    result = _extract_json(response_text)

    reviews = result.get("reviews", [])

    if not isinstance(reviews, list):
        raise ValueError("Invalid story review response.")

    return reviews


# ==========================================
# POST-STORY RESOLUTION AUDIT
# ==========================================

def _audit_and_extend_candidates(
    client,
    transcript_segments,
    transcript_text,
    candidates,
    episode_duration,
):

    if not candidates:
        return []

    audit_items = []

    for index, clip in enumerate(candidates):

        selected_text = _get_clip_transcript(
            transcript_segments,
            clip["segments"],
        )

        remaining_text = _get_range_transcript(
            transcript_segments,
            clip["end"],
            episode_duration,
        )

        audit_items.append({
            "candidate_index": index,
            "title": clip["title"],
            "selected_story": selected_text,
            "current_conclusion": clip["conclusion_summary"],
            "current_ending_evidence": clip["ending_evidence"],
            "remaining_episode_after_clip": remaining_text,
            "current_end_timestamp": clip["end"],
        })

    prompt = f"""
You are a documentary fact-checker and narrative investigator.

Determine whether each proposed Short contains a complete story.

FULL ORIGINAL TRANSCRIPT:
{transcript_text}

CANDIDATES:
{json.dumps(audit_items, ensure_ascii=False)}

For each candidate, investigate what happens AFTER its proposed ending.

Determine:
1. Whether the same story continues.
2. Whether a genuine resolution appears later.
3. Whether the selected footage already contains that resolution.
4. If not, the exact timestamps of the later resolution.

IMPORTANT:

A story can be edited from several distant moments in an episode.

DO NOT calculate the duration from the first moment to the last moment.

The final duration is the SUM of the selected footage segments.
Unrelated dialogue between selected segments can be removed.

For example:
- Original story section: 2180-2220
- Later resolution: 2450-2490
- Edited Short duration: 80 seconds, NOT 310 seconds.

Do not require the entire intervening episode to be included.

Do not invent events or use outside knowledge.

TIMESTAMP REQUIREMENTS:

If the resolution is later:
- Give resolution_start.
- Give resolution_end.
- Provide an exact quotation from the resolution.
- The quotation must exist in the supplied transcript.

If the selected clip already contains the resolution:
- Provide exact evidence from inside the selected footage.

Return ONLY valid JSON:

{{
    "audits": [
        {{
            "candidate_index": 0,
            "approved": true,
            "same_story_continues": true,
            "resolution_found": true,
            "already_complete": false,
            "resolution_start": 2450.0,
            "resolution_end": 2490.0,
            "resolution_evidence": "Exact words from the resolution.",
            "outcome_summary": "What actually happened.",
            "reason": "Why this is the genuine resolution."
        }}
    ]
}}

If the story is already complete, set already_complete to true.

If the resolution occurs later, set already_complete to false.

If no genuine resolution can be verified, reject it.
"""

    try:

        response_text = _generate_with_retry(
            client,
            prompt,
            "Auditing complete story resolutions",
        )

        result = _extract_json(response_text)
        audits = result.get("audits", [])

        if not isinstance(audits, list):
            raise ValueError("Invalid audit response.")

    except Exception as exc:

        print(f"[Resolution Audit] Failed: {exc}")
        return []

    audit_lookup = {}

    for audit in audits:

        if not isinstance(audit, dict):
            continue

        try:
            index = int(audit["candidate_index"])
        except (KeyError, TypeError, ValueError):
            continue

        audit_lookup[index] = audit

    approved = []

    for index, clip in enumerate(candidates):

        audit = audit_lookup.get(index)

        if not audit:
            print(
                f"[Resolution Audit] Rejected: "
                f"{clip['title']} — missing audit."
            )
            continue

        if audit.get("approved") is not True:
            print(
                f"[Resolution Audit] Rejected: "
                f"{clip['title']} — "
                f"{audit.get('reason', 'Audit rejected story.')}"
            )
            continue

        if audit.get("resolution_found") is not True:
            print(
                f"[Resolution Audit] Rejected: "
                f"{clip['title']} — no verified resolution."
            )
            continue

        evidence = str(
            audit.get("resolution_evidence", "")
        ).strip()

        outcome = str(
            audit.get("outcome_summary", "")
        ).strip()

        if len(outcome) < 15:
            print(
                f"[Resolution Audit] Rejected: "
                f"{clip['title']} — missing outcome summary."
            )
            continue

        if audit.get("already_complete") is True:

            selected_text = _get_clip_transcript(
                transcript_segments,
                clip["segments"],
            )

            if not _quote_is_present(evidence, selected_text):
                print(
                    f"[Resolution Audit] Rejected: "
                    f"{clip['title']} — resolution evidence "
                    "is not in selected footage."
                )
                continue

            clip["resolution_verified"] = True
            clip["conclusion_summary"] = outcome
            clip["resolution_evidence"] = evidence
            clip["ending_evidence"] = evidence
            clip["ending_type"] = "resolution"
            clip["resolution_review"] = str(
                audit.get("reason", "")
            )

            approved.append(clip)

            print(
                f"[Resolution Audit] Verified existing ending: "
                f"{clip['title']}"
            )

            continue

        try:

            resolution_start = float(
                audit["resolution_start"]
            )

            resolution_end = float(
                audit["resolution_end"]
            )

            if (
                resolution_start < 0
                or resolution_end <= resolution_start
                or resolution_end > episode_duration
            ):
                raise ValueError(
                    "Invalid resolution timestamps."
                )

            current_segments = [
                dict(segment)
                for segment in clip["segments"]
            ]

            last_segment = current_segments[-1]

            if resolution_end <= last_segment["end"]:
                raise ValueError(
                    "Resolution does not extend beyond "
                    "the selected footage."
                )

            snapped_start, snapped_end = (
                _snap_to_transcript_boundaries(
                    resolution_start,
                    resolution_end,
                    transcript_segments,
                )
            )

            resolution_text = _get_range_transcript(
                transcript_segments,
                snapped_start,
                snapped_end,
            )

            if not _quote_is_present(
                evidence,
                resolution_text,
            ):
                raise ValueError(
                    "Resolution quotation is not present "
                    "in the claimed timestamp range."
                )

            if snapped_start <= last_segment["end"]:

                last_segment["end"] = round(
                    max(last_segment["end"], snapped_end),
                    3,
                )

            else:

                if len(current_segments) >= MAX_STORY_SEGMENTS:
                    raise ValueError(
                        "Resolution requires another cut, "
                        "but the maximum segment count "
                        "has already been reached."
                    )

                resolution_duration = snapped_end - snapped_start

                if resolution_duration < MIN_SEGMENT_DURATION:
                    raise ValueError(
                        "Resolution segment is too short."
                    )

                current_segments.append({
                    "start": round(snapped_start, 3),
                    "end": round(snapped_end, 3),
                })

                # Keep one explanation for every gap between source cuts.
                cut_reasons = list(clip.get("_cut_reasons", []))
                cut_reasons.append(
                    "Intervening dialogue is removed because the later "
                    "segment contains the verified resolution of the same story."
                )
                clip["_cut_reasons"] = cut_reasons

            total_duration = sum(
                segment["end"] - segment["start"]
                for segment in current_segments
            )

            if total_duration > MAX_CLIP_DURATION:
                raise ValueError(
                    f"Selected footage totals "
                    f"{total_duration:.1f}s, exceeding "
                    f"the {MAX_CLIP_DURATION}s limit."
                )

            if total_duration < MIN_CLIP_DURATION:
                raise ValueError(
                    "Completed story is too short."
                )

            clip["segments"] = current_segments

            clip["start"] = current_segments[0]["start"]
            clip["end"] = current_segments[-1]["end"]
            clip["duration"] = round(total_duration, 2)

            clip["resolution_verified"] = True
            clip["resolution_evidence"] = evidence
            clip["ending_evidence"] = evidence
            clip["ending_type"] = "resolution"
            clip["conclusion_summary"] = outcome
            clip["resolution_review"] = str(
                audit.get("reason", "")
            )

            approved.append(clip)

            print(
                f"[Resolution Audit] Extended with separate cut: "
                f"{clip['title']}"
                f" | Edited duration: {total_duration:.1f}s"
                f" | Source cuts: {len(current_segments)}"
            )

        except (KeyError, TypeError, ValueError) as exc:

            print(
                f"[Resolution Audit] Rejected: "
                f"{clip['title']} — {exc}"
            )

    print(
        f"\n[Resolution Audit] "
        f"Verified complete stories: {len(approved)}/"
        f"{len(candidates)}"
    )

    return approved


# ==========================================
# STORY FINDER
# ==========================================

def find_clips(
    transcript,
    target_clips=5,
):

    transcript_segments = _valid_transcript_segments(
        transcript.get("segments", [])
    )

    if not transcript_segments:
        raise ValueError(
            "Transcript contains no valid segments."
        )

    duration = float(
        transcript.get("duration_seconds", 0)
    )

    if duration <= 0:
        duration = max(
            segment["end"]
            for segment in transcript_segments
        )

    transcript_lines = [
        f"[{segment['start']:.2f} - {segment['end']:.2f}] "
        f"{segment['text']}"
        for segment in transcript_segments
    ]

    transcript_text = "\n".join(transcript_lines)

    prompt = f"""
You are an expert documentary editor and short-form storyteller.

Find exceptional COMPLETE stories in this transcript.

Your job is NOT to find interesting statements.
Your job is to create standalone stories that viewers
can understand from beginning to end.

EPISODE DURATION: {duration:.2f} seconds.

Find up to {target_clips} stories.

FINAL SHORT:
Minimum duration: {MIN_CLIP_DURATION} seconds.
Maximum duration: {MAX_CLIP_DURATION} seconds.

Maximum source segments: {MAX_STORY_SEGMENTS}.

TRANSCRIPT:
{transcript_text}

==================================================
MOST IMPORTANT RULE: COMPLETE THE STORY
==================================================

A clip must contain:

1. A clear opening that introduces the situation.
2. Enough context to understand what is happening.
3. The important events and developments.
4. The actual revelation, outcome, answer or punchline.
5. The speaker finishing the story or thought naturally.

The conclusion must be present in the selected footage.

Do NOT confuse:
- A promise with a revelation.
- A decision with its outcome.
- An accusation with proof.
- A question with an answer.
- A setup with a punchline.
- A reaction with a resolution.

If the story continues beyond the selected footage,
it is NOT complete.

==================================================
CONTINUITY RULES
==================================================

DEFAULT: Prefer ONE continuous source segment.

Only use multiple segments when the speaker genuinely
leaves the story for unrelated material and later returns.

When multiple segments are necessary:

- Use as few cuts as possible.
- Never exceed {MAX_STORY_SEGMENTS} segments.
- Preserve chronological order.
- Every segment must begin at a natural conversational point.
- Every segment must end at a natural conversational point.
- Do not cut in the middle of a sentence.
- Do not cut in the middle of an explanation.
- Do not remove necessary questions or answers.
- Do not remove reactions that make the story understandable.
- Do not skip events needed to understand what happens next.
- Do not join two unrelated statements to manufacture a story.

For every segment after the first, include a cut_reason
explaining exactly why the removed material is unnecessary.

IMPORTANT:
The final video joins selected ranges directly together.
The viewer will not hear the removed dialogue.

Read the dialogue between every proposed cut.
If removing it makes the story confusing, do not make that cut.

==================================================
FIND THE CONCLUSION FIRST
==================================================

Before selecting timestamps, identify:

- What actually happens?
- What is the final outcome?
- What does the speaker reveal?
- What is the last meaningful development?
- Does the speaker finish explaining what happened?

Find the conclusion FIRST.

Then work backwards to find the minimum context and
development needed to understand it.

Do not select a clip just because its opening is interesting.

==================================================
ENDING REQUIREMENTS
==================================================

Every clip must include:

"story_complete": true

"ending_is_final": true

"ending_type": one of:
- resolution
- revelation
- answer
- punchline
- conclusion

"ending_evidence":
An exact quotation of at least four words spoken near
the end of the FINAL selected segment.

"conclusion_summary":
Explain the actual outcome in one or two sentences.

The final selected segment must contain the complete conclusion.

Include the speaker's immediate explanation or reaction
when necessary to make the outcome understandable.

Do not stop immediately after introducing the outcome
if the speaker continues explaining it.

If the conclusion is not available in the transcript,
reject the story.

==================================================
STORY COMPRESSION
==================================================

You may remove:
- Unrelated tangents.
- Repeated information.
- Dead space.
- Entirely unrelated conversations.

You may NOT remove:
- Essential context.
- Important events.
- Necessary explanations.
- The reason something happened.
- The result of an action.
- The actual conclusion.

If a complete story needs 80 seconds, use 80 seconds.

Do not force it into 30 seconds.

If it cannot fit within {MAX_CLIP_DURATION} seconds,
reject it.

==================================================
CONTENT PRIORITIES
==================================================

Prioritize entertaining:
- Unbelievable personal stories.
- Confessions.
- Unexpected encounters.
- Strange experiences.
- Controversies and arguments.
- Disasters and failures.
- Surprising revelations.
- Funny and awkward situations.
- Unexpected consequences.

Do not prioritize education, generic advice,
motivational speeches or explanations without a story.

==================================================
SCORING
==================================================

Rate from 1 to 10:

curiosity: 25%
storytelling: 25%
payoff: 20%
emotion: 15%
entertainment: 15%

Minimum payoff: {MINIMUM_PAYOFF_SCORE}.
Minimum storytelling: {MINIMUM_STORYTELLING_SCORE}.
Minimum weighted score: {MINIMUM_CLIP_SCORE}.

A high score NEVER compensates for an incomplete story.

==================================================
OUTPUT
==================================================

Return ONLY valid JSON:

{{
    "clips": [
        {{
            "segments": [
                {{
                    "start": 120.0,
                    "end": 190.0
                }}
            ],
            "hook": "Exact or faithful opening dialogue",
            "title": "Curiosity-driven title",
            "reason": "Explain the complete story and its payoff.",
            "story_complete": true,
            "ending_is_final": true,
            "ending_type": "resolution",
            "ending_evidence": "Exact words spoken near the end",
            "conclusion_summary": "What actually happened in the end.",
            "scores": {{
                "curiosity": 9,
                "storytelling": 9,
                "payoff": 9,
                "emotion": 8,
                "entertainment": 9
            }}
        }}
    ]
}}

For multiple segments, every segment after the first MUST
also contain "cut_reason".

Return an empty clips array if no complete stories exist.
"""

    client = _get_client()

    response_text = _generate_with_retry(
        client,
        prompt,
        "Finding complete stories",
    )

    result = _extract_json(response_text)

    if not isinstance(result, dict):
        raise ValueError("Gemini returned an invalid JSON structure.")

    clips = result.get("clips", [])

    if not isinstance(clips, list):
        raise ValueError("Gemini returned an invalid clips list.")

    # ======================================
    # FIRST-PASS VALIDATION
    # ======================================

    candidates = []

    rejected_incomplete = 0
    rejected_evidence = 0
    rejected_segments = 0
    rejected_quality = 0

    for clip in clips:

        try:

            if not isinstance(clip, dict):
                continue

            if clip.get("story_complete") is not True:
                rejected_incomplete += 1
                continue

            if clip.get("ending_is_final") is not True:
                rejected_incomplete += 1
                continue

            ending_type = str(
                clip.get("ending_type", "")
            ).lower().strip()

            if ending_type not in VALID_ENDING_TYPES:
                rejected_incomplete += 1
                continue

            conclusion_summary = str(
                clip.get("conclusion_summary", "")
            ).strip()

            if len(conclusion_summary) < 15:
                rejected_incomplete += 1
                continue

            selected_segments = _validate_story_segments(
                clip.get("segments"),
                duration,
                transcript_segments,
            )

            ending_evidence = str(
                clip.get("ending_evidence", "")
            ).strip()

            final_segment = selected_segments[-1]

            final_transcript = _get_range_transcript(
                transcript_segments,
                final_segment["start"],
                final_segment["end"],
            )

            if not _ending_evidence_is_valid(
                ending_evidence,
                final_transcript,
            ):
                rejected_evidence += 1
                continue

            scores = clip.get("scores", {})

            if not isinstance(scores, dict):
                rejected_quality += 1
                continue

            normalized_scores = {}

            for key in REQUIRED_SCORES:

                value = float(scores[key])

                if not 1 <= value <= 10:
                    raise ValueError("Invalid score.")

                normalized_scores[key] = value

            if (
                normalized_scores["payoff"]
                < MINIMUM_PAYOFF_SCORE
                or normalized_scores["storytelling"]
                < MINIMUM_STORYTELLING_SCORE
            ):
                rejected_quality += 1
                continue

            score = _calculate_score(normalized_scores)

            if score < MINIMUM_CLIP_SCORE:
                rejected_quality += 1
                continue

            title = str(clip.get("title", "")).strip()
            hook = str(clip.get("hook", "")).strip()

            if not title or not hook:
                rejected_quality += 1
                continue

            total_duration = sum(
                item["end"] - item["start"]
                for item in selected_segments
            )

            cut_reasons = []

            raw_segments = clip.get("segments", [])

            for item in raw_segments[1:]:
                cut_reasons.append(
                    str(item.get("cut_reason", "")).strip()
                )

            clip["segments"] = selected_segments
            clip["start"] = selected_segments[0]["start"]
            clip["end"] = selected_segments[-1]["end"]
            clip["duration"] = round(total_duration, 2)

            clip["title"] = title
            clip["hook"] = hook
            clip["scores"] = normalized_scores
            clip["overall_score"] = score
            clip["ending_type"] = ending_type
            clip["ending_evidence"] = ending_evidence
            clip["conclusion_summary"] = conclusion_summary

            clip["_transcript_segments"] = transcript_segments
            clip["_cut_reasons"] = cut_reasons

            candidates.append(clip)

        except (KeyError, TypeError, ValueError) as exc:
            rejected_segments += 1

            candidate_title = (
                clip.get("title", "Untitled")
                if isinstance(clip, dict)
                else "Invalid candidate structure"
            )

            print(
                f"\n[Validation] Rejected candidate: {candidate_title}"
            )
            print(
                f"[Validation] Reason: {type(exc).__name__}: {exc}"
            )

            if isinstance(clip, dict):
                print(
                    "[Validation] Raw segments: "
                    f"{clip.get('segments', 'MISSING')}"
                )

            continue

    # ======================================
    # POST-STORY RESOLUTION AUDIT
    # ======================================

    print(
        f"\n[Resolution Audit] Investigating what happens "
        f"after {len(candidates)} proposed stories..."
    )

    candidates = _audit_and_extend_candidates(
        client,
        transcript_segments,
        transcript_text,
        candidates,
        duration,
    )

    # ======================================
    # SECOND-PASS NARRATIVE REVIEW
    # ======================================

    print(
        f"\n[Story Review] Checking {len(candidates)} candidates "
        "for continuity and genuine conclusions..."
    )

    approved = []
    rejected_review = 0

    if candidates:

        try:

            reviews = _review_candidates(
                client,
                transcript_text,
                candidates,
            )

            review_lookup = {}

            for review in reviews:

                if not isinstance(review, dict):
                    continue

                try:
                    index = int(review["candidate_index"])
                except (KeyError, TypeError, ValueError):
                    continue

                review_lookup[index] = review

            for index, clip in enumerate(candidates):

                review = review_lookup.get(index)

                if not review:
                    rejected_review += 1
                    print(
                        f"[Story Review] Rejected: "
                        f"{clip['title']} — no review returned."
                    )
                    continue

                passed = (
                    review.get("approved") is True
                    and review.get("context_clear") is True
                    and review.get("continuity_clear") is True
                    and review.get("conclusion_complete") is True
                    and review.get("ending_is_final") is True
                )

                if not passed:
                    rejected_review += 1
                    print(
                        f"[Story Review] Rejected: "
                        f"{clip['title']} — "
                        f"{review.get('reason', 'Narrative review failed.')}"
                    )
                    continue

                clip["review_reason"] = str(
                    review.get("reason", "")
                )

                approved.append(clip)

                print(
                    f"[Story Review] Approved: {clip['title']}"
                )

        except Exception as exc:

            rejected_review += len(candidates)

            print(
                f"[Story Review] Review failed: {exc}"
            )

    # ======================================
    # RANKING AND OVERLAP FILTER
    # ======================================

    approved.sort(
        key=lambda item: item["overall_score"],
        reverse=True,
    )

    non_overlapping = []

    for clip in approved:

        overlaps = any(
            any(
                new_segment["start"] < old_segment["end"]
                and new_segment["end"] > old_segment["start"]
                for new_segment in clip["segments"]
            )
            for existing in non_overlapping
            for old_segment in existing["segments"]
        )

        if not overlaps:
            non_overlapping.append(clip)

        if len(non_overlapping) >= target_clips:
            break

    # ======================================
    # RESULTS
    # ======================================

    print(
        "\n[Gemini] Story selection finished."
        f"\n[Gemini] Candidates returned: {len(clips)}"
        f"\n[Gemini] Rejected: incomplete stories: {rejected_incomplete}"
        f"\n[Gemini] Rejected: ending evidence: {rejected_evidence}"
        f"\n[Gemini] Rejected: invalid segments: {rejected_segments}"
        f"\n[Gemini] Rejected: quality: {rejected_quality}"
        f"\n[Gemini] Rejected: narrative review: {rejected_review}"
        f"\n[Gemini] Final approved stories: {len(non_overlapping)}"
    )

    for index, clip in enumerate(non_overlapping, 1):

        print(
            f"\n#{index} | Score: {clip['overall_score']}/10"
            f"\nTitle: {clip['title']}"
            f"\nDuration: {clip['duration']:.1f}s"
            f"\nSource segments: {len(clip['segments'])}"
            f"\nEnding: {clip['ending_type']}"
            f"\nConclusion: {clip['conclusion_summary']}"
            f"\nReview: {clip.get('review_reason', '')}"
        )

        for segment_index, segment in enumerate(
            clip["segments"],
            1,
        ):

            print(
                f"  Cut {segment_index}: "
                f"{segment['start']:.2f}s - "
                f"{segment['end']:.2f}s"
            )

    for clip in non_overlapping:
        clip.pop("_transcript_segments", None)
        clip.pop("_cut_reasons", None)

    return non_overlapping
