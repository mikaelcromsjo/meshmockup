"""
Mini mockup pipeline.
Resolves a YouTube channel, fetches avatar, generates a branded mug mockup via Gemini.
"""

import base64
import os
import sys
from pathlib import Path

import httpx

from dotenv import load_dotenv
load_dotenv()

# ── YouTube ───────────────────────────────────────────────────────────────────

def resolve_channel(channel_url: str, api_key: str) -> dict:
    """Resolve a YouTube @handle or URL to channel metadata."""
    handle = None
    if "@" in channel_url:
        handle = channel_url.split("@")[-1].strip("/").split("/")[0]
    elif "channel/" in channel_url:
        channel_id = channel_url.split("channel/")[-1].strip("/")
        return _resolve_by_id(channel_id, api_key)
    else:
        handle = channel_url.strip("/").split("/")[-1]

    if not handle:
        raise ValueError(f"Could not parse channel from: {channel_url!r}")

    r = httpx.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet", "forHandle": handle, "key": api_key},
        timeout=15,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        raise ValueError(f"Channel not found for handle: @{handle}")
    return _parse_channel(items[0])


def _resolve_by_id(channel_id: str, api_key: str) -> dict:
    r = httpx.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet", "id": channel_id, "key": api_key},
        timeout=15,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        raise ValueError(f"Channel not found for ID: {channel_id}")
    return _parse_channel(items[0])


def _parse_channel(item: dict) -> dict:
    snippet = item.get("snippet", {})
    thumbs = snippet.get("thumbnails", {})
    avatar_url = (
        thumbs.get("maxres", {}).get("url")
        or thumbs.get("high", {}).get("url")
        or thumbs.get("medium", {}).get("url")
    )
    return {
        "channel_id": item.get("id"),
        "title": snippet.get("title", "Unknown"),
        "handle": snippet.get("customUrl", "").lstrip("@"),
        "avatar_url": avatar_url,
    }


def pick_best_avatar(avatar_url: str) -> bytes:
    """Download avatar, replacing any existing size param with =w400."""
    # Strip any existing =sXXX size suffix before appending our own
    base_url = avatar_url.split("=s")[0].split("=w")[0]
    url = f"{base_url}=w400"
    r = httpx.get(url, follow_redirects=True, timeout=30)
    r.raise_for_status()
    return r.content


# ── Gemini ────────────────────────────────────────────────────────────────────

# GEMINI_MODEL = "gemini-2.5-flash-image"
GEMINI_MODEL = "gemini-3.1-flash-image-preview"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
RECITATION_REASONS = ("RECITATION", "IMAGE_RECITATION")
MAX_RETRIES = 3


class GeminiError(Exception):
    def __init__(self, message: str, reason: str = ""):
        super().__init__(message)
        self.reason = reason


def generate_mockup_image(
    token: str,
    channel_name: str,
    avatar_bytes: bytes,
    mockup_bytes: bytes,
) -> bytes:
    """Generate branded mug mockup via Gemini with auto-retry on RECITATION or text response."""
    prompt = f"""You are a professional product mockup designer.

Create a realistic mug product mockup for YouTube creator "{channel_name}".

Instructions:
- Use the provided sample mug as your exact template (angle, lighting, shadows)
- Place the provided creator avatar/icon centered and clearly visible on the mug surface with correct proportions
- Add the text "{channel_name}" underneath the icon in a bold, clean font
- Create an interesting background inspired by "{channel_name}" and the dominant colors of the icon
- Keep it looking like a real professional product photo

IMPORTANT: Respond with an IMAGE ONLY. Do not write any text, explanation, or description."""

    reference_images = [
        {"data": mockup_bytes, "mime_type": "image/png"},
        {"data": avatar_bytes, "mime_type": "image/jpeg"},
    ]

    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            return _call_gemini(token, prompt, reference_images)
        except GeminiError as e:
            if e.reason not in (*RECITATION_REASONS, "TEXT_INSTEAD_OF_IMAGE") or attempt > MAX_RETRIES:
                raise
            last_error = e
            print(f"  Retry {attempt}/{MAX_RETRIES + 1} (reason: {e.reason})...", flush=True)
    raise last_error

    reference_images = [
        {"data": mockup_bytes, "mime_type": "image/png"},
        {"data": avatar_bytes, "mime_type": "image/jpeg"},
    ]

    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            return _call_gemini(token, prompt, reference_images)
        except GeminiError as e:
            if e.reason not in RECITATION_REASONS or attempt > MAX_RETRIES:
                raise
            last_error = e
            print(f"  RECITATION on attempt {attempt}, retrying...", flush=True)
    raise last_error


def _call_gemini(token: str, prompt: str, reference_images: list) -> bytes:
    parts = [{"text": prompt}]
    for ref in reference_images:
        parts.append({
            "inlineData": {
                "mimeType": ref["mime_type"],
                "data": base64.b64encode(ref["data"]).decode(),
            }
        })

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }

    r = httpx.post(
        f"{GEMINI_BASE}/{GEMINI_MODEL}:generateContent?key={token}",
        json=payload,
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()

    block = data.get("promptFeedback", {}).get("blockReason")
    if block:
        raise GeminiError(f"Prompt blocked: {block}", reason=block)

    candidates = data.get("candidates", [])
    if not candidates:
        raise GeminiError("No candidates in response", reason="NO_CANDIDATES")

    candidate = candidates[0]
    finish_reason = candidate.get("finishReason", "")

    if finish_reason in RECITATION_REASONS:
        raise GeminiError("Recitation filter triggered", reason=finish_reason)
    if finish_reason == "SAFETY":
        raise GeminiError("Safety filter triggered", reason="SAFETY")

    for part in candidate.get("content", {}).get("parts", []):
        if "inlineData" in part and part["inlineData"].get("data"):
            return base64.b64decode(part["inlineData"]["data"])
        if "text" in part:
            # 👇 Print what Gemini is thinking so we can debug
            print(f"  [Gemini text]: {part['text'][:500]}", flush=True)
            raise GeminiError(
                f"Gemini returned text instead of image: {part['text'][:200]!r}",
                reason="TEXT_INSTEAD_OF_IMAGE",
            )

    raise GeminiError(
        f"No image data in response (finishReason: {finish_reason})",
        reason=finish_reason,
    )

# ── Main pipeline ─────────────────────────────────────────────────────────────

def run(channel_url: str, sample_mockup_path: str) -> tuple:
    """
    Full pipeline: channel URL -> (image_bytes, channel_name)
    """
    gemini_token = os.environ["GEMINI_TOKEN"]
    yt_key = os.environ["YOUTUBE_API_KEY"]

    print(f"[1/3] Resolving channel: {channel_url}", flush=True)
    channel = resolve_channel(channel_url, yt_key)
    name = channel["title"]
    print(f"      -> {name} ({channel['channel_id']})", flush=True)

    if not channel["avatar_url"]:
        raise ValueError(f"No avatar found for: {name}")

    print("[2/3] Fetching images...", flush=True)
    avatar_bytes = pick_best_avatar(channel["avatar_url"])
    mockup_bytes = Path(sample_mockup_path).read_bytes()
    print(f"      -> Avatar: {len(avatar_bytes):,} bytes", flush=True)
    print(f"      -> Mockup template: {len(mockup_bytes):,} bytes", flush=True)

    print("[3/3] Generating with Gemini...", flush=True)
    image_bytes = generate_mockup_image(gemini_token, name, avatar_bytes, mockup_bytes)
    print(f"      -> Done! {len(image_bytes):,} bytes", flush=True)

    return image_bytes, name


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python mini_mockup.py <channel_url> <sample_mug.png> [output.png]")
        sys.exit(1)

    img_bytes, channel_name = run(sys.argv[1], sys.argv[2])
    out = sys.argv[3] if len(sys.argv) > 3 else "output.png"
    Path(out).write_bytes(img_bytes)
    print(f"\n✅ Saved -> {out}  ({channel_name})")
