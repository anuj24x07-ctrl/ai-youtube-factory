
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


# =========================
# CONFIGURATION
# =========================

OUT = Path("output")
OUT.mkdir(exist_ok=True)

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PIXABAY_KEY = os.environ["PIXABAY_API_KEY"]

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

CACHE_FILE = OUT / "pixabay_cache.json"
CACHE_HOURS = 24

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


# =========================
# GEMINI SCRIPT GENERATION
# =========================

def make_script():

    topic = random.choice(TOPICS)

    prompt = f"""
Create an original, fact-focused YouTube Short script about:

{topic}

Audience: General US audience.
Language: Natural American English.
Duration: 35-50 seconds.

Requirements:
- Narration must contain 90-115 words.
- Start with a compelling but truthful hook.
- Use clear, engaging storytelling.
- Do not invent facts or statistics.
- Avoid sensational misinformation.
- Avoid copyrighted characters and copied scripts.

Return ONLY valid JSON with these keys:

title (max 65 characters)
hook
narration
visual_search (2-5 simple Pixabay search terms)
thumbnail_text (2-4 words)
description
tags (array)
fact_check_notes (array of claims requiring verification)
"""

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{MODEL}:generateContent"
    )

    response = requests.post(
        url,
        params={"key": GEMINI_KEY},
        json={
            "contents": [
                {"parts": [{"text": prompt}]}
            ],
            "generationConfig": {
                "temperature": 0.7,
                "responseMimeType": "application/json"
            }
        },
        timeout=90
    )

    response.raise_for_status()

    raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]

    raw = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        raw.strip(),
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
            raise ValueError(f"Gemini response missing field: {field}")

    if not isinstance(data["visual_search"], list):
        raise ValueError("visual_search must be a list")

    (OUT / "script.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    return data


# =========================
# PIXABAY CACHE
# =========================

def load_cache():

    if not CACHE_FILE.exists():
        return {}

    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache):

    CACHE_FILE.write_text(
        json.dumps(cache, indent=2),
        encoding="utf-8"
    )


# =========================
# PIXABAY VIDEO SEARCH
# =========================

def search_pixabay(query):

    cache = load_cache()
    now = time.time()

    cached = cache.get(query)

    if cached:
        age = now - cached.get("timestamp", 0)

        if age < CACHE_HOURS * 3600:
            return cached.get("results", [])

    response = requests.get(
        "https://pixabay.com/api/videos/",
        params={
            "key": PIXABAY_KEY,
            "q": query,
            "per_page": 10,
            "safesearch": "true",
            "order": "popular"
        },
        timeout=45
    )

    response.raise_for_status()

    hits = response.json().get("hits", [])

    results = []

    for hit in hits:

        videos = hit.get("videos", {})

        selected = None

        # Prefer medium or small files to reduce download size.
        for size in ["medium", "small", "large", "tiny"]:

            video = videos.get(size)

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

    all_results = []

    for query in queries:

        print("Searching Pixabay:", query)

        results = search_pixabay(query)

        if results:
            all_results.extend(results)

    if not all_results:
        raise RuntimeError(
            "No Pixabay videos found. Try different search terms."
        )

    # Prefer portrait videos where available.
    portrait = [
        item for item in all_results
        if item["height"] > item["width"]
    ]

    selected_pool = portrait if portrait else all_results

    selected = random.choice(selected_pool)

    (OUT / "asset_info.json").write_text(
        json.dumps(selected, indent=2),
        encoding="utf-8"
    )

    return selected["url"]


# =========================
# DOWNLOAD VIDEO
# =========================

def download(url, path):

    with requests.get(
        url,
        stream=True,
        timeout=120
    ) as response:

        response.raise_for_status()

        with open(path, "wb") as file:

            for chunk in response.iter_content(1024 * 256):

                if chunk:
                    file.write(chunk)


# =========================
# AI VOICEOVER
# =========================

async def make_voice(text, path):

    communicate = edge_tts.Communicate(
        text,
        voice="en-US-AriaNeural",
        rate="+2%"
    )

    await communicate.save(str(path))


# =========================
# THUMBNAIL GENERATOR
# =========================

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


# =========================
# SHORT VIDEO RENDERER
# =========================

def render(video_url, narration):

    raw_video = OUT / "stock.mp4"
    voice = OUT / "voice.mp3"
    final = OUT / "short.mp4"

    print("Downloading stock video...")

    download(video_url, raw_video)

    print("Generating AI voiceover...")

    asyncio.run(
        make_voice(narration, voice)
    )

    print("Rendering YouTube Short...")

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

    print("Video rendering completed.")


# =========================
# MAIN
# =========================

def main():

    print("Starting AI YouTube Factory...")

    print("Step 1: Generating script")

    data = make_script()

    print("Title:", data["title"])

    print("Step 2: Searching Pixabay")

    video_url = get_pixabay_video(
        data.get(
            "visual_search",
            ["science space"]
        )
    )

    print("Step 3: Creating video")

    render(
        video_url,
        data["narration"]
    )

    print("Step 4: Creating thumbnail")

    make_thumbnail(
        data.get(
            "thumbnail_text",
            data["title"]
        )
    )

    print("\nSUCCESS!")

    print("Created files:")

    print("- output/short.mp4")
    print("- output/thumbnail.jpg")
    print("- output/script.json")
    print("- output/asset_info.json")

    print("\nReview fact_check_notes before publishing.")


if __name__ == "__main__":
    main()
    
