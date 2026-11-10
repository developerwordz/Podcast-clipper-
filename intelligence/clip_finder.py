
import json
import re
import time

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL


MAX_ATTEMPTS = 4
INITIAL_RETRY_DELAY = 3


def _get_client():
    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is missing. Add it to your .env file."
        )

    return genai.Client(api_key=GEMINI_API_KEY)


def _extract_json(text):
    if not text:
        raise ValueError("Gemini returned an empty response.")

    text = text.strip()

    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    return json.loads(text)


def _generate_with_retry(client, prompt):
    for attempt in range(1, MAX_ATTEMPTS + 1):

        try:
            print(
                f"[Gemini] Sending analysis request "
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

            if not response.text:
                raise ValueError("Gemini returned an empty response.")

            return response.text

        except Exception as exc:
            error_message = str(exc)

            temporary_error = any(
                code in error_message
                for code in ["429", "500", "502", "503", "504"]
            )

            if not temporary_error or attempt == MAX_ATTEMPTS:
                raise

            delay = INITIAL_RETRY_DELAY * (2 ** (attempt - 1))

            print(
                f"[Gemini] Temporary API error. "
                f"Retrying in {delay} seconds..."
            )

            time.sleep(delay)

    raise RuntimeError("Gemini request failed after all attempts.")


def find_clips(transcript, target_clips=5):

    segments = transcript.get("segments", [])

    if not segments:
        raise ValueError("Transcript contains no segments.")

    duration = float(transcript.get("duration_seconds", 0))

    if duration <= 0:
        duration = max(
            float(segment["end"])
            for segment in segments
        )

    transcript_lines = []

    for segment in segments:
        try:
            start = float(segment["start"])
            end = float(segment["end"])
            text = str(segment["text"]).strip()

            if not text or end <= start:
                continue

            transcript_lines.append(
                f"[{start:.2f} - {end:.2f}] {text}"
            )

        except (KeyError, TypeError, ValueError):
            continue

    if not transcript_lines:
        raise ValueError("Transcript has no valid segments.")

    transcript_text = "\n".join(transcript_lines)

    prompt = f"""
You are an expert short-form podcast video editor.

Analyze this podcast transcript and identify the {target_clips}
strongest moments for YouTube Shorts and Instagram Reels.

EPISODE DURATION: {duration:.2f} seconds.

TRANSCRIPT:
{transcript_text}

SELECTION CRITERIA:
1. Strong opening hook.
2. Interesting, surprising, emotional, or useful content.
3. A coherent standalone idea.
4. A satisfying ending or payoff.
5. Minimal dependence on outside context.

CLIP RULES:
- Prefer clips between 30 and 60 seconds.
- Use the supplied timestamps.
- Never invent dialogue or timestamps.
- Start and end at natural speech boundaries.
- Never exceed the episode duration.
- Avoid overlapping clips.
- Avoid starting halfway through a sentence.
- Prefer quality over quantity.
- Return fewer clips if there are not enough strong moments.

SCORING:
Score each category from 1 to 10:
- hook
- emotion
- storytelling
- standalone

Return ONLY valid JSON in this structure:

{{
    "clips": [
        {{
            "start": 10.0,
            "end": 50.0,
            "hook": "Opening hook",
            "title": "Suggested title",
            "reason": "Why this moment works",
            "scores": {{
                "hook": 9,
                "emotion": 8,
                "storytelling": 9,
                "standalone": 8
            }},
            "overall_score": 8.5
        }}
    ]
}}
"""

    client = _get_client()

    response_text = _generate_with_retry(client, prompt)

    result = _extract_json(response_text)

    if not isinstance(result, dict):
        raise ValueError("Gemini returned an invalid JSON structure.")

    clips = result.get("clips", [])

    if not isinstance(clips, list):
        raise ValueError("Gemini response does not contain a valid clips list.")

    validated = []

    for clip in clips:
        try:
            start = float(clip["start"])
            end = float(clip["end"])
            score = float(clip.get("overall_score", 0))

            if start < 0 or end <= start:
                continue

            if end > duration:
                continue

            if not clip.get("hook") or not clip.get("title"):
                continue

            if not 0 <= score <= 10:
                continue

            clip["start"] = start
            clip["end"] = end
            clip["overall_score"] = score

            validated.append(clip)

        except (KeyError, TypeError, ValueError):
            continue

    validated.sort(
        key=lambda clip: clip["overall_score"],
        reverse=True,
    )

    # Remove overlapping clips, keeping the highest-scoring ones.
    non_overlapping = []

    for clip in validated:
        overlaps = any(
            clip["start"] < existing["end"]
            and clip["end"] > existing["start"]
            for existing in non_overlapping
        )

        if not overlaps:
            non_overlapping.append(clip)

        if len(non_overlapping) >= target_clips:
            break

    print(
        f"[Gemini] Successfully identified "
        f"{len(non_overlapping)} valid clips."
    )

    return non_overlapping
