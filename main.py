
import os
import json
import random
import subprocess
import asyncio
import re
import time
from pathlib import Path

import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont


# ==================================================
# CONFIGURATION
# ==================================================

OUT = Path("output")
OUT.mkdir(exist_ok=True)

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PIXABAY_KEY = os.environ["PIXABAY_API_KEY"]

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
PIXABAY_URL = "https://pixabay.com/api/videos/"

CACHE_FILE = OUT / "pixabay_cache.json"
CACHE_SECONDS = 24 * 60 * 60

# Try less-loaded alternatives first.
PREFERRED_MODELS = [
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash"
]

RETRY_STATUS_CODES = [429, 500, 502, 503, 504]

TOPICS = [
    "Why astronauts grow slightly taller in space",
    "The mysterious sound known as the Bloop",
    "How tardigrades survive extreme conditions",
    "Why the Moon is slowly moving away from Earth",
    "The science behind deja vu",
    "Why deep ocean water can glow blue",
    "How trees communicate through underground fungal networks",
    "What happens to time near a black hole",
    "Why humans get goosebumps",
    "The strange physics of ball lightning"
]


# ==================================================
# GEMINI MODEL DISCOVERY
# ==================================================

def get_available_models():

    print("\nChecking available Gemini models...")

    try:
        response = requests.get(
            f"{API_BASE}/models",
            params={"key": GEMINI_KEY},
            timeout=30
        )

        if not response.ok:
            print("Model discovery response:", response.text)
            response.raise_for_status()

        items = response.json().get("models", [])

        available = []

        for item in items:

            name = item.get("name", "").replace("models/", "")
            methods = item.get("supportedGenerationMethods", [])

            if (
                name.startswith("gemini-")
                and "generateContent" in methods
            ):
                available.append(name)

        ordered = []

        custom = os.getenv("GEMINI_MODEL", "").strip()

        if custom and custom in available:
            ordered.append(custom)

        for model in PREFERRED_MODELS:
            if model in available and model not in ordered:
                ordered.append(model)

        for model in available:
            if model not in ordered:
                ordered.append(model)

        if ordered:
            print("Models available:", ", ".join(ordered))
            return ordered

        raise RuntimeError("No supported Gemini models found.")

    except Exception as error:
        print("Model discovery failed:", str(error))
        raise RuntimeError(
            "Could not retrieve Gemini model list. "
            "Check API key and Gemini API access."
        )


# ==================================================
# GEMINI SCRIPT GENERATION
# ==================================================

def make_script():

    topic = random.choice(TOPICS)

    prompt = f"""
Create an original, fact-focused YouTube Short script.

TOPIC: {topic}

AUDIENCE:
General US audience.

LANGUAGE:
Natural American English.

DURATION:
35-50 seconds.

REQUIREMENTS:
- Narration must contain 90-115 words.
- Start with a compelling but truthful hook.
- Use engaging storytelling.
- Do not invent facts, statistics or scientific claims.
- Avoid misleading clickbait.
- Avoid copyrighted characters.
- Do not copy existing scripts.
- Make the ending memorable.

Return ONLY valid JSON with these keys:

{{
  "title": "Maximum 65 characters",
  "hook": "Opening hook",
  "narration": "90-115 word narration",
  "visual_search": ["search term 1", "search term 2"],
  "thumbnail_text": "2-4 words",
  "description": "YouTube description",
  "tags": ["tag1", "tag2"],
  "fact_check_notes": ["claim to verify"]
}}
"""

    models = get_available_models()

    last_error = "No model succeeded."

    for model in models:

        print("\nTrying Gemini model:", model)

        url = f"{API_BASE}/models/{model}:generateContent"

        # Two attempts per model for temporary server problems.
        for attempt in range(2):

            try:

                response = requests.post(
                    url,
                    params={"key": GEMINI_KEY},
                    json={
                        "contents": [
                            {
                                "parts": [
                                    {"text": prompt}
                                ]
                            }
                        ],
                        "generationConfig": {
                            "temperature": 0.7,
                            "responseMimeType": "application/json"
                        }
                    },
                    timeout=120
                )

                if response.status_code in RETRY_STATUS_CODES:

                    last_error = (
                        f"HTTP {response.status_code}: "
                        f"{response.text[:1000]}"
                    )

                    print("Temporary Gemini error:", response.status_code)

                    if attempt == 0:
                        wait = 8
                        print(f"Retrying same model in {wait} seconds...")
                        time.sleep(wait)
                        continue

                    print("Trying another Gemini model...")
                    break

                if response.status_code == 404:

                    last_error = response.text[:1000]
                    print("Model not available. Switching model...")
                    break

                if not response.ok:

                    print("\nGemini API error:", response.status_code)
                    print(response.text[:2000])

                    response.raise_for_status()

                result = response.json()

                candidates = result.get("candidates", [])

                if not candidates:
                    last_error = (
                        "Gemini returned no candidates: "
                        + json.dumps(result)[:1000]
                    )
                    print(last_error)
                    break

                parts = candidates[0].get(
                    "content", {}
                ).get("parts", [])

                raw = "".join(
                    part.get("text", "")
                    for part in parts
                ).strip()

                raw = re.sub(
                    r"^```(?:json)?\s*|\s*```$",
                    "",
                    raw,
                    flags=re.I
                )

                data = json.loads(raw)

                required = [
                    "title",
                    "narration",
                    "visual_search",
                    "thumbnail_text",
                    "description",
                    "tags",
                    "fact_check_notes"
                ]

                for field in required:
                    if field not in data:
                        raise ValueError(
                            f"Missing field: {field}"
                        )

                if not isinstance(data["narration"], str):
                    raise ValueError("Narration must be text.")

                if not isinstance(data["visual_search"], list):
                    raise ValueError("visual_search must be a list.")

                (OUT / "script.json").write_text(
                    json.dumps(
                        data,
                        indent=2,
                        ensure_ascii=False
                    ),
                    encoding="utf-8"
                )

                print("\nScript successfully generated!")
                print("Model used:", model)

                return data

            except requests.HTTPError:
                raise

            except (requests.RequestException, json.JSONDecodeError, ValueError) as error:

                last_error = str(error)
                print("Attempt failed:", last_error)
                break

    raise RuntimeError(
        "All Gemini models failed. Last error: " + last_error
    )


# ==================================================
# PIXABAY CACHE
# ==================================================

def load_cache():

    if not CACHE_FILE.exists():
        return {}

    try:
        return json.loads(
            CACHE_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def save_cache(cache):

    CACHE_FILE.write_text(
        json.dumps(cache, indent=2),
        encoding="utf-8"
    )


# ==================================================
# PIXABAY VIDEO SEARCH
# ==================================================

def search_pixabay(query):

    cache = load_cache()
    now = time.time()

    cached = cache.get(query)

    if cached:
        age = now - cached.get("timestamp", 0)

        if age < CACHE_SECONDS:
            print("Using cached Pixabay results.")
            return cached.get("results", [])

    print("Searching Pixabay:", query)

    response = requests.get(
        PIXABAY_URL,
        params={
            "key": PIXABAY_KEY,
            "q": query,
            "per_page": 10,
            "safesearch": "true",
            "order": "popular"
        },
        timeout=60
    )

    if not response.ok:
        print("Pixabay error:", response.text[:1500])
        response.raise_for_status()

    hits = response.json().get("hits", [])

    results = []

    for hit in hits:

        video_sizes = hit.get("videos", {})
        selected = None

        for size in ["medium", "small", "large", "tiny"]:

            video = video_sizes.get(size)

            if video and video.get("url"):
                selected = video
                break

        if not selected:
            continue

        results.append({
            "url": selected["url"],
            "width": selected.get("width", 0),
            "height": selected.get("height", 0),
            "page_url": hit.get("pageURL", ""),
            "user": hit.get("user", "")
        })

    cache[query] = {
        "timestamp": now,
        "results": results
    }

    save_cache(cache)

    return results


def get_pixabay_video(queries):

    if not queries:
        queries = ["science space"]

    for query in queries:

        results = search_pixabay(query)

        if not results:
            continue

        portrait = [
            item for item in results
            if item["height"] > item["width"]
        ]

        pool = portrait if portrait else results

        selected = random.choice(pool)

        (OUT / "asset_info.json").write_text(
            json.dumps(selected, indent=2),
            encoding="utf-8"
        )

        print("Selected video:", selected.get("page_url", ""))

        return selected["url"]

    raise RuntimeError(
        "No Pixabay videos found. Try different search terms."
    )


# ==================================================
# DOWNLOAD VIDEO
# ==================================================

def download(url, path):

    with requests.get(
        url,
        stream=True,
        timeout=120
    ) as response:

        response.raise_for_status()

        with open(path, "wb") as file:

            for chunk in response.iter_content(
                chunk_size=256 * 1024
            ):
                if chunk:
                    file.write(chunk)

    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("Downloaded video is empty.")


# ==================================================
# AI VOICEOVER
# ==================================================

async def make_voice(text, path):

    communicate = edge_tts.Communicate(
        text,
        voice="en-US-AriaNeural",
        rate="+2%"
    )

    await communicate.save(str(path))


# ==================================================
# THUMBNAIL GENERATOR
# ==================================================

def make_thumbnail(text):

    img = Image.new(
        "RGB",
        (1280, 720),
        (12, 18, 35)
    )

    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            92
        )
    except Exception:
        font = ImageFont.load_default()

    words = str(text).upper()[:42].split()

    lines = []
    line = ""

    for word in words:

        candidate = (line + " " + word).strip()

        if len(candidate) > 18 and line:
            lines.append(line)
            line = word
        else:
            line = candidate

    if line:
        lines.append(line)

    y = 250

    for current_line in lines[:2]:

        box = draw.textbbox(
            (0, 0),
            current_line,
            font=font
        )

        x = (1280 - (box[2] - box[0])) // 2

        draw.text(
            (x + 4, y + 4),
            current_line,
            font=font,
            fill=(0, 0, 0)
        )

        draw.text(
            (x, y),
            current_line,
            font=font,
            fill=(255, 255, 255)
        )

        y += 115

    draw.text(
        (40, 650),
        "THE UNKNOWN FILES",
        font=ImageFont.load_default(),
        fill=(170, 190, 220)
    )

    img.save(
        OUT / "thumbnail.jpg",
        quality=92
    )


# ==================================================
# VIDEO RENDERING
# ==================================================

def render(video_url, narration):

    raw_video = OUT / "stock.mp4"
    voice = OUT / "voice.mp3"
    final = OUT / "short.mp4"

    print("\nDownloading stock footage...")

    download(video_url, raw_video)

    print("\nGenerating AI voiceover...")

    asyncio.run(
        make_voice(narration, voice)
    )

    print("\nRendering vertical video...")

    command = [
        "ffmpeg",
        "-y",

        "-stream_loop", "-1",
        "-i", str(raw_video),

        "-i", str(voice),

        "-vf",
        (
            "scale=1080:1920:"
            "force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            "fps=30"
        ),

        "-map", "0:v:0",
        "-map", "1:a:0",

        "-shortest",

        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",

        "-c:a", "aac",
        "-b:a", "160k",

        "-movflags", "+faststart",

        str(final)
    ]

    subprocess.run(
        command,
        check=True
    )

    raw_video.unlink(missing_ok=True)

    if not final.exists() or final.stat().st_size == 0:
        raise RuntimeError("Final video was not created.")

    print("Video successfully rendered!")


# ==================================================
# MAIN
# ==================================================

def main():

    print("=" * 45)
    print("        AI YOUTUBE FACTORY")
    print("=" * 45)

    print("\nSTEP 1: Generating script")

    data = make_script()

    print("\nTITLE:", data["title"])

    print("\nSTEP 2: Finding stock footage")

    video_url = get_pixabay_video(
        data.get(
            "visual_search",
            ["science space"]
        )
    )

    print("\nSTEP 3: Creating voice and video")

    render(
        video_url,
        data["narration"]
    )

    print("\nSTEP 4: Creating thumbnail")

    make_thumbnail(
        data.get(
            "thumbnail_text",
            data["title"]
        )
    )

    print("\n" + "=" * 45)
    print("              SUCCESS")
    print("=" * 45)

    print("\nGenerated files:")
    print("- output/short.mp4")
    print("- output/thumbnail.jpg")
    print("- output/script.json")
    print("- output/asset_info.json")
    print("- output/pixabay_cache.json")

    print("\nPlease review factual claims and footage before publishing.")


if __name__ == "__main__":
    main()
    
