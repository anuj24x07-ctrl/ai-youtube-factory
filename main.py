import os, json, random, subprocess, asyncio, re
from pathlib import Path
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont

OUT = Path("output")
OUT.mkdir(exist_ok=True)

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PEXELS_KEY = os.environ["PEXELS_API_KEY"]
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

TOPICS = [
    "Why astronauts grow slightly taller in space",
    "The mysterious sound known as the Bloop",
    "How tardigrades survive extreme conditions",
    "Why the Moon is slowly moving away from Earth",
    "The science behind déjà vu",
    "Why deep ocean water can glow blue",
    "How trees communicate through underground fungal networks",
    "What happens to time near a black hole",
    "Why humans get goosebumps",
    "The strange physics of ball lightning"
]

def make_script():
    topic = random.choice(TOPICS)
    prompt = f"""
Create an original, fact-focused YouTube Short script about: {topic}
Audience: general US audience. Language: natural American English.
Duration: 35-50 seconds. No fabricated claims, no sensational falsehoods.
Return ONLY valid JSON with keys:
title (max 65 chars), hook, narration (90-115 words),
visual_search (2-5 simple Pexels search terms),
thumbnail_text (2-4 words), description, tags (array),
fact_check_notes (array of claims that need source verification).
Make the hook compelling but truthful. Avoid copyrighted characters and copied scripts.
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_KEY}"
    r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}],
                                  "generationConfig":{"temperature":0.7}}, timeout=90)
    r.raise_for_status()
    raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    data = json.loads(raw)
    (OUT / "script.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data

def get_pexels_video(queries):
    headers = {"Authorization": PEXELS_KEY}
    for q in queries:
        r = requests.get("https://api.pexels.com/videos/search",
                         headers=headers,
                         params={"query": q, "orientation": "portrait",
                                 "per_page": 5, "size": "medium"}, timeout=45)
        r.raise_for_status()
        videos = r.json().get("videos", [])
        for v in videos:
            choices = sorted(v.get("video_files", []),
                             key=lambda x: (x.get("width", 0) >= 720, x.get("width", 0)),
                             reverse=True)
            for f in choices:
                if f.get("file_type") == "video/mp4" and f.get("link"):
                    return f["link"]
    raise RuntimeError("No suitable Pexels video found. Try another topic/search term.")

def download(url, path):
    with requests.get(url, stream=True, timeout=90) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1024 * 256):
                if chunk:
                    f.write(chunk)

async def make_voice(text, path):
    communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural", rate="+2%")
    await communicate.save(str(path))

def make_thumbnail(text):
    img = Image.new("RGB", (1280, 720), (12, 18, 35))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 92)
    except:
        font = ImageFont.load_default()
    words = text.upper()[:42]
    # Wrap to two lines for legibility
    parts = words.split()
    lines, line = [], ""
    for w in parts:
        candidate = (line + " " + w).strip()
        if len(candidate) > 18 and line:
            lines.append(line); line = w
        else:
            line = candidate
    if line: lines.append(line)
    y = 250
    for ln in lines[:2]:
        box = d.textbbox((0,0), ln, font=font)
        x = (1280 - (box[2]-box[0])) // 2
        d.text((x+4,y+4), ln, font=font, fill=(0,0,0))
        d.text((x,y), ln, font=font, fill=(255,255,255))
        y += 115
    d.text((40,650), "THE UNKNOWN FILES", font=ImageFont.load_default(), fill=(170,190,220))
    img.save(OUT / "thumbnail.jpg", quality=92)

def render(video_url, narration):
    raw_video = OUT / "stock.mp4"
    voice = OUT / "voice.mp3"
    final = OUT / "short.mp4"
    download(video_url, raw_video)
    asyncio.run(make_voice(narration, voice))
    # Loop/crop stock footage to vertical 1080x1920 and fit narration length.
    cmd = [
        "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(raw_video),
        "-i", str(voice), "-vf",
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30",
        "-map", "0:v:0", "-map", "1:a:0", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        str(final)
    ]
    subprocess.run(cmd, check=True)
    raw_video.unlink(missing_ok=True)

def main():
    data = make_script()
    video_url = get_pexels_video(data.get("visual_search", ["science space"]))
    render(video_url, data["narration"])
    make_thumbnail(data.get("thumbnail_text", data["title"]))
    print("Created:", OUT / "short.mp4")
    print("Review script.json and fact_check_notes before publishing.")

if __name__ == "__main__":
    main()
