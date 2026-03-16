"""
Long-form video generator: retells articles from poland-consult.com.
Pipeline: sitemap → pick article → scrape → extract facts (LLM) →
          generate script (LLM) → edge-tts → Pexels clips → ffmpeg → upload
"""

import asyncio
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree

import edge_tts
import requests
from bs4 import BeautifulSoup

# ── Constants ──────────────────────────────────────────────────────────
BUILD_DIR = Path("build")
CLIPS_DIR = BUILD_DIR / "clips"
AUDIO_PATH = BUILD_DIR / "voiceover.mp3"
MUSIC_PATH = BUILD_DIR / "music.mp3"
METADATA_PATH = BUILD_DIR / "metadata.json"
OUTPUT_PATH = BUILD_DIR / "output_poland_long.mp4"
USED_ARTICLES_PATH = Path("used_articles.json")

TARGET_W, TARGET_H = 1280, 720
FPS = 30
FFMPEG_PRESET = "medium"
FFMPEG_CRF = "23"

SITEMAP_URLS = [
    "https://poland-consult.com/post-sitemap.xml",
    "https://poland-consult.com/post-sitemap2.xml",
    "https://poland-consult.com/post-sitemap3.xml",
    "https://poland-consult.com/post-sitemap4.xml",
]

ALLOWED_PREFIXES = [
    "/praca/", "/eu/pl/nalogi/", "/biznes/", "/polezno-znat/",
    "/vnzh-i-pmzh/", "/eu/pl/zasilki/", "/eu/pl/uchodzcy/",
]
EXCLUDED_PREFIXES = [
    "/gazetki/", "/novosti/", "/coronavirus/", "/uk/",
    "/eu/germany/", "/eu/cz/", "/usa/",
]

TTS_VOICES = ["ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural"]
TTS_RATE = "+3%"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

PEXELS_QUERIES = [
    "Poland city aerial", "Krakow old town", "Warsaw skyline",
    "European office work", "document paperwork", "Polish food market",
    "European street cafe", "immigration office queue", "passport visa document",
    "European architecture church", "Poland nature forest autumn",
    "family home interior", "business meeting handshake", "office desk laptop",
    "European market stalls", "train station Europe travel",
    "hospital health clinic", "money coins euros", "apartment interior modern",
    "city park Europe autumn", "university lecture hall", "court law justice",
    "tax calculator finance", "handshake agreement", "moving boxes new home",
    "construction site building", "bank interior finance", "supermarket shopping",
    "children school education", "elderly couple walking park",
]

TTS_PRONUNCIATION_FIXES = {
    "Kraków": "Кра́ков", "Wrocław": "Вро́цлав", "Gdańsk": "Гда́ньск",
    "Poznań": "По́знань", "Łódź": "Лодзь", "Katowice": "Като́вице",
    "Warszawa": "Варша́ва", "Zakopane": "Закопа́нэ", "Toruń": "То́рунь",
    "Lublin": "Лю́блин", "Sopot": "Со́пот", "Wieliczka": "Вели́чка",
    "Wawel": "Ва́вэль", "Chopin": "Шопе́н", "Kopernik": "Копе́рник",
    "złotych": "зло́тых", "złoty": "зло́тый", "zł": "злотых",
    "PKP": "Пэ Ка Пэ", "NFZ": "Эн Эф Зэт", "ZUS": "Зэ У Эс",
    "PESEL": "ПЕ́СЕЛЬ", "NIP": "Эн И Пэ", "PIT": "Пэ И Тэ",
    "poland-consult.com": "поланд консалт точка ком",
}

MUSIC_URLS = [
    "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Komiku/Its_time_for_adventure/Komiku_-_05_-_Friends.mp3",
    "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Podington_Bear/Daydream/Podington_Bear_-_Daydream.mp3",
    "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/ccCommunity/Chad_Crouch/Arps/Chad_Crouch_-_Shipping_Lanes.mp3",
]

_DESCRIPTION_FOOTER = (
    "\n\n---\n"
    "По материалам poland-consult.com\n"
    "Подписывайся на «Я в Польше» — новый ролик каждую неделю! 🔔\n"
    "Задавай вопросы в комментариях 👇"
)

_CORE_TAGS = [
    "польша", "явпольше", "путешествия", "европа",
    "иммиграция", "жизньвпольше", "полезно",
]


# ── Helpers ────────────────────────────────────────────────────────────
def _clean_build_dir():
    if BUILD_DIR.is_dir():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)


def _run_ffmpeg(cmd: list):
    print(f"[CMD] {' '.join(cmd[:8])}... ({len(cmd)} args)")
    subprocess.run(cmd, check=True)


def _probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True,
    ).strip()
    return float(out)


def _fix_pronunciation(text: str) -> str:
    result = text
    for word, fix in TTS_PRONUNCIATION_FIXES.items():
        result = re.sub(re.escape(word), fix, result, flags=re.IGNORECASE)
    return result


def _groq_call(messages: list, temperature: float = 0.7, max_tokens: int = 4096) -> Optional[str]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    for attempt in range(1, 3):
        try:
            r = requests.post(GROQ_URL, headers=headers, json=body, timeout=90)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            print(f"[WARN] Groq attempt {attempt} failed: {exc}")
            time.sleep(5)
    return None


# ── Article Sourcing ──────────────────────────────────────────────────
def _fetch_sitemap_urls() -> list[str]:
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    all_urls = []
    for sitemap_url in SITEMAP_URLS:
        try:
            r = requests.get(sitemap_url, timeout=30)
            if r.status_code == 404:
                break
            r.raise_for_status()
            root = ElementTree.fromstring(r.content)
            for url_elem in root.findall("sm:url/sm:loc", ns):
                if url_elem.text:
                    all_urls.append(url_elem.text.strip())
        except Exception as exc:
            print(f"[WARN] Sitemap {sitemap_url}: {exc}")
            break
    print(f"[SITEMAP] Fetched {len(all_urls)} URLs")
    return all_urls


def _filter_urls(urls: list[str]) -> list[str]:
    from urllib.parse import urlparse
    filtered = []
    for url in urls:
        path = urlparse(url).path
        if any(path.startswith(ex) for ex in EXCLUDED_PREFIXES):
            continue
        if any(path.startswith(al) for al in ALLOWED_PREFIXES):
            filtered.append(url)
    print(f"[FILTER] {len(filtered)} articles in allowed categories")
    return filtered


def _load_used_articles() -> set:
    if USED_ARTICLES_PATH.is_file():
        try:
            return set(json.loads(USED_ARTICLES_PATH.read_text("utf-8")))
        except Exception:
            pass
    return set()


def _save_used_articles(used: set):
    USED_ARTICLES_PATH.write_text(
        json.dumps(sorted(used), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _pick_article(urls: list[str], used: set) -> Optional[str]:
    available = [u for u in urls if u not in used]
    if not available:
        print("[WARN] All articles used, resetting history")
        available = urls
        used.clear()
    if not available:
        return None
    return random.choice(available)


def _scrape_article(url: str) -> tuple[str, str]:
    """Scrape article title and text from poland-consult.com."""
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = ""
    title_tag = soup.find("h1")
    if title_tag:
        title = title_tag.get_text(strip=True)

    content_div = soup.find("div", class_="entry-content")
    if not content_div:
        content_div = soup.find("article")
    if not content_div:
        content_div = soup.find("main")

    if content_div:
        for tag in content_div.find_all(["script", "style", "nav", "aside", "footer"]):
            tag.decompose()
        text = content_div.get_text(separator="\n", strip=True)
    else:
        text = soup.get_text(separator="\n", strip=True)

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    text = "\n".join(lines)
    return title, text


# ── Two-Step LLM Pipeline ────────────────────────────────────────────
def step1_extract_facts(article_title: str, article_text: str) -> Optional[str]:
    """Step 1: Compress article into 7-10 key facts (~500 words)."""
    # Truncate very long articles to fit context window comfortably
    words = article_text.split()
    if len(words) > 8000:
        article_text = " ".join(words[:8000])

    messages = [
        {"role": "system", "content": (
            "Ты — эксперт по иммиграции в Польшу. "
            "Твоя задача — прочитать статью и выделить 7-10 самых важных фактов. "
            "Пиши ТОЛЬКО факты, без вводных фраз. Каждый факт — 1-2 предложения. "
            "Сохраняй конкретику: числа, даты, суммы, названия документов, сроки. "
            "Общий объём — около 500 слов."
        )},
        {"role": "user", "content": (
            f"Заголовок статьи: {article_title}\n\n"
            f"Текст статьи:\n{article_text}\n\n"
            "Выдели 7-10 ключевых фактов из этой статьи."
        )},
    ]
    result = _groq_call(messages, temperature=0.3, max_tokens=2048)
    if result:
        print(f"[STEP1] Extracted facts: {len(result.split())} words")
    return result


def step2_generate_script(facts: str, article_title: str) -> Optional[dict]:
    """Step 2: Generate original YouTube script from extracted facts."""
    messages = [
        {"role": "system", "content": (
            "Ты — русскоязычный блогер, живущий в Польше 5 лет. Канал «Я в Польше». "
            "Пишешь сценарии для YouTube (длинные видео, 8-12 минут). "
            "Стиль: как будто объясняешь другу за кофе — живо, понятным языком, с примерами.\n\n"
            "ПРАВИЛА:\n"
            "- Каждое предложение — максимум 15 слов (для озвучки).\n"
            "- Используй переходные слова: 'кстати', 'а вот интересно', 'теперь о главном', "
            "'важный момент', 'и ещё один нюанс', 'давай разберёмся'.\n"
            "- Все польские термины пиши КИРИЛЛИЦЕЙ.\n"
            "- Конкретика: суммы в злотых, сроки, названия документов.\n"
            "- НЕ копируй исходный текст — перескажи СВОИМИ словами.\n"
            "- Структура: Введение → Основная часть (5-7 разделов) → Итоги → CTA.\n\n"
            "Отвечай ТОЛЬКО валидным JSON."
        )},
        {"role": "user", "content": f"""На основе этих фактов напиши сценарий YouTube-видео (8-12 минут, ~1500-2000 слов).

ТЕМА: {article_title}

ФАКТЫ:
{facts}

СТРУКТУРА:
1. ВВЕДЕНИЕ (2-3 фразы): зацепи зрителя — задай вопрос или назови ключевую проблему.
2. ОСНОВНАЯ ЧАСТЬ (5-7 блоков по 3-5 фраз): раскрой каждый факт подробно, с примерами и пояснениями.
3. ИТОГИ (2-3 фразы): резюмируй главное.
4. CTA (1 фраза): призыв подписаться, задать вопрос в комментариях.

ФОРМАТ JSON:
{{
  "title": "Заголовок видео, до 90 символов, с эмодзи 🇵🇱",
  "description": "Описание 5-8 строк с хештегами",
  "tags": ["польша", "явпольше", ...ещё 10-15 тегов],
  "pexels_queries": ["5-8 английских запросов для поиска видео"],
  "script": "Полный текст сценария. Каждое предложение на отдельной строке."
}}"""},
    ]
    content = _groq_call(messages, temperature=0.8, max_tokens=8192)
    if not content:
        return None
    try:
        content = re.sub(r"^```(?:json)?\s*", "", content.strip())
        content = re.sub(r"\s*```$", "", content.strip())
        data = json.loads(content)
        script = data.get("script", "")
        word_count = len(script.split())
        print(f"[STEP2] Script generated: {word_count} words")
        if word_count < 500:
            print("[WARN] Script too short, retrying...")
            return None
        return data
    except Exception as exc:
        print(f"[WARN] JSON parse failed: {exc}")
        return None


# ── TTS ───────────────────────────────────────────────────────────────
async def _generate_tts(text: str, output_path: Path) -> list[dict]:
    voice = random.choice(TTS_VOICES)
    tts_text = _fix_pronunciation(text)
    comm = edge_tts.Communicate(tts_text, voice, rate=TTS_RATE)
    word_events = []
    with open(output_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_events.append({
                    "text": chunk["text"],
                    "offset": chunk["offset"] / 10_000_000,
                    "duration": chunk["duration"] / 10_000_000,
                })
    print(f"[TTS] {voice}, {len(word_events)} words, file={output_path}")
    return word_events


def generate_tts(text: str) -> tuple[Path, list[dict]]:
    word_events = asyncio.run(_generate_tts(text, AUDIO_PATH))
    return AUDIO_PATH, word_events


# ── Clip Downloading ─────────────────────────────────────────────────
def _download_file(url: str, dest: Path):
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with dest.open("wb") as f:
        for chunk in r.iter_content(32768):
            if chunk:
                f.write(chunk)


def download_clips(extra_queries: list[str] = None, target: int = 35) -> list[Path]:
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        print("[WARN] No PEXELS_API_KEY")
        return []

    queries = list(extra_queries or [])
    base = [q for q in PEXELS_QUERIES if q not in queries]
    random.shuffle(base)
    queries.extend(base)

    headers = {"Authorization": api_key}
    paths = []
    seen_ids = set()
    idx = 0

    for query in queries:
        if len(paths) >= target:
            break
        try:
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                headers=headers,
                params={"query": query, "per_page": 3, "orientation": "landscape"},
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as exc:
            print(f"[WARN] Pexels '{query}': {exc}")
            continue

        for video in resp.json().get("videos", []):
            vid_id = video.get("id")
            if vid_id in seen_ids:
                continue
            seen_ids.add(vid_id)
            hd = [f for f in video.get("video_files", []) if (f.get("height") or 0) >= 720]
            if not hd:
                continue
            best = min(hd, key=lambda f: abs((f.get("height") or 0) - 720))
            idx += 1
            clip_path = CLIPS_DIR / f"clip_{idx:03d}.mp4"
            try:
                _download_file(best["link"], clip_path)
                paths.append(clip_path)
            except Exception:
                pass
            if len(paths) >= target:
                break

    print(f"[CLIPS] Downloaded {len(paths)} clips")
    return paths


def download_music() -> Optional[Path]:
    for url in random.sample(MUSIC_URLS, len(MUSIC_URLS)):
        try:
            _download_file(url, MUSIC_PATH)
            return MUSIC_PATH
        except Exception:
            continue
    return None


# ── FFmpeg Assembly ──────────────────────────────────────────────────
def _prepare_clip(src: Path, dst: Path, duration: int = 5):
    vf = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},fps={FPS}"
    )
    _run_ffmpeg([
        "ffmpeg", "-y", "-i", str(src), "-t", str(duration),
        "-vf", vf, "-an", "-c:v", "libx264",
        "-preset", FFMPEG_PRESET, "-crf", FFMPEG_CRF, str(dst),
    ])


def _fmt_ass_time(seconds: float) -> str:
    total_cs = max(0, int(round(seconds * 100)))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _safe_text(raw: str) -> str:
    text = raw.replace("\\", " ").replace("\n", " ")
    text = text.replace(":", " ").replace(";", " ")
    text = text.replace("'", "").replace('"', "")
    text = re.sub(r"\s+", " ", text).strip()
    return text or " "


def _group_words(word_events: list[dict], max_per_line: int = 6) -> list[dict]:
    if not word_events:
        return []
    lines = []
    buf_words, buf_start, buf_end, buf_kara = [], 0.0, 0.0, []
    for ev in word_events:
        start, dur = ev["offset"], ev["duration"]
        end = start + dur
        if buf_words and (len(buf_words) >= max_per_line or (start - buf_end) > 0.6):
            lines.append({"start": buf_start, "end": buf_end, "text": " ".join(buf_words), "words": list(buf_kara)})
            buf_words, buf_kara = [], []
        if not buf_words:
            buf_start = start
        buf_words.append(ev["text"])
        buf_kara.append({"text": ev["text"], "offset": start, "duration": dur})
        buf_end = end
    if buf_words:
        lines.append({"start": buf_start, "end": buf_end, "text": " ".join(buf_words), "words": list(buf_kara)})
    return lines


def _write_ass(word_events: list[dict], ass_path: Path) -> Path:
    font_size = 42
    margin_v = 80
    primary = "&H0000D4FF"     # Yellow-orange (spoken)
    secondary = "&H00FFFFFF"   # White (upcoming)
    outline = "&H00000000"
    shadow = "&H80000000"

    header = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\n"
        f"PlayResX: {TARGET_W}\nPlayResY: {TARGET_H}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Kara,DejaVu Sans,{font_size},{primary},{secondary},{outline},{shadow},"
        f"1,0,0,0,100,100,1,0,1,3,2,2,30,30,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = _group_words(word_events)
    events = []
    for line in lines:
        start = line["start"]
        end = line["end"] + 0.15
        parts = []
        for w in line["words"]:
            dur_cs = max(5, int(w["duration"] * 100))
            safe = _safe_text(w["text"]).upper()
            parts.append(f"{{\\kf{dur_cs}}}{safe}")
        kara_text = " ".join(parts)
        events.append(f"Dialogue: 0,{_fmt_ass_time(start)},{_fmt_ass_time(end)},Kara,,0,0,0,,{kara_text}")

    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    print(f"[SUBS] {len(events)} lines, {len(word_events)} words → {ass_path}")
    return ass_path


def assemble_video(
    clips: list[Path],
    voiceover: Path,
    word_events: list[dict],
    music: Optional[Path],
) -> Path:
    temp = BUILD_DIR / "temp"
    temp.mkdir(exist_ok=True)

    # Prepare clips
    prepared = []
    for i, clip in enumerate(clips):
        dst = temp / f"prep_{i:03d}.mp4"
        _prepare_clip(clip, dst, duration=5)
        prepared.append(dst)

    # Concatenate
    concat_file = temp / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in prepared),
        encoding="utf-8",
    )
    silent = temp / "silent.mp4"
    _run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(concat_file), "-c", "copy", str(silent)])

    voice_dur = _probe_duration(voiceover)
    clip_dur = _probe_duration(silent)
    final_dur = voice_dur + 1.5

    # Loop video if shorter than voice
    if clip_dur < voice_dur:
        looped = temp / "looped.mp4"
        _run_ffmpeg([
            "ffmpeg", "-y", "-stream_loop", "-1",
            "-i", str(silent), "-t", f"{final_dur:.2f}",
            "-c", "copy", str(looped),
        ])
        silent = looped

    # Write ASS subtitles
    ass_path = _write_ass(word_events, temp / "captions.ass")

    # Pass 1: burn subtitles
    graded = temp / "graded.mp4"
    ass_posix = ass_path.resolve().as_posix()
    ass_escaped = (
        ass_posix.replace("\\", "\\\\").replace(":", "\\:")
        .replace("'", "\\'").replace("[", "\\[").replace("]", "\\]")
    )
    _run_ffmpeg([
        "ffmpeg", "-y", "-i", str(silent),
        "-vf", f"subtitles={ass_escaped}",
        "-t", f"{final_dur:.2f}",
        "-c:v", "libx264", "-preset", FFMPEG_PRESET, "-crf", FFMPEG_CRF,
        "-an", str(graded),
    ])

    # Pass 2: mix audio
    voice_pad = f"apad=whole_dur={final_dur:.2f}"
    cmd = ["ffmpeg", "-y", "-i", str(graded), "-i", str(voiceover)]

    if music and music.exists():
        cmd.extend(["-stream_loop", "-1", "-i", str(music)])
        cmd.extend([
            "-filter_complex",
            (
                f"[1:a]acompressor=threshold=-18dB:ratio=2.5:attack=5:release=120,{voice_pad}[va];"
                "[va]asplit=2[va1][va2];"
                "[2:a]highpass=f=80,lowpass=f=14000,volume=0.14[ma];"
                "[ma][va1]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=250[ducked];"
                "[va2][ducked]amix=inputs=2:duration=first:normalize=0[a]"
            ),
            "-map", "0:v", "-map", "[a]",
        ])
    else:
        cmd.extend([
            "-filter_complex", f"[1:a]{voice_pad}[a]",
            "-map", "0:v", "-map", "[a]",
        ])

    cmd.extend([
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", f"{final_dur:.2f}", "-movflags", "+faststart",
        str(OUTPUT_PATH),
    ])
    _run_ffmpeg(cmd)
    print(f"[VIDEO] voice={voice_dur:.1f}s clips={clip_dur:.1f}s final={final_dur:.1f}s → {OUTPUT_PATH}")
    return OUTPUT_PATH


# ── YouTube Upload ───────────────────────────────────────────────────
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


def _get_access_token() -> str:
    resp = requests.post(TOKEN_URL, data={
        "client_id": os.environ["YOUTUBE_CLIENT_ID"],
        "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def upload_video(meta: dict) -> str:
    creds = [os.getenv("YOUTUBE_CLIENT_ID"), os.getenv("YOUTUBE_CLIENT_SECRET"),
             os.getenv("YOUTUBE_REFRESH_TOKEN")]
    if not all(creds):
        print("[SKIP] Upload: missing credentials")
        return ""
    if not OUTPUT_PATH.is_file():
        print(f"[ERROR] Video not found: {OUTPUT_PATH}")
        return ""

    privacy = os.getenv("YOUTUBE_PRIVACY", "public")
    if privacy not in ("public", "unlisted", "private"):
        privacy = "public"

    access_token = _get_access_token()
    body = {
        "snippet": {
            "title": meta.get("title", "Я в Польше")[:100],
            "description": meta.get("description", ""),
            "tags": meta.get("tags", _CORE_TAGS),
            "categoryId": "19",
            "defaultLanguage": "ru",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
        },
    }

    video_data = OUTPUT_PATH.read_bytes()
    init_resp = requests.post(UPLOAD_URL, params={
        "uploadType": "resumable", "part": "snippet,status",
    }, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(len(video_data)),
        "X-Upload-Content-Type": "video/mp4",
    }, json=body, timeout=30)
    init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]

    print(f"[UPLOAD] {len(video_data) / 1024 / 1024:.1f} MB...")
    for attempt in range(1, 4):
        try:
            resp = requests.put(upload_url, headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "video/mp4",
                "Content-Length": str(len(video_data)),
            }, data=video_data, timeout=600)
            resp.raise_for_status()
            video_id = resp.json().get("id", "")
            print(f"[UPLOAD] Done! https://youtube.com/watch?v={video_id}")
            try:
                from analytics import log_upload
                log_upload(video_id, meta.get("title", ""), meta.get("topic", ""), meta.get("tags", []))
            except Exception as exc:
                print(f"[WARN] Analytics: {exc}")
            return video_id
        except Exception as exc:
            print(f"[WARN] Upload attempt {attempt}: {exc}")
            if attempt < 3:
                time.sleep(attempt * 15)
    return ""


# ── Main Pipeline ────────────────────────────────────────────────────
def main():
    _clean_build_dir()

    # 1. Pick article
    print("[1/7] Fetching sitemap & picking article...")
    all_urls = _fetch_sitemap_urls()
    filtered = _filter_urls(all_urls)
    if not filtered:
        print("[ERROR] No articles found in allowed categories")
        sys.exit(1)

    used = _load_used_articles()
    article_url = _pick_article(filtered, used)
    if not article_url:
        print("[ERROR] No article available")
        sys.exit(1)
    print(f"  Article: {article_url}")

    # 2. Scrape article
    print("[2/7] Scraping article...")
    title, text = _scrape_article(article_url)
    print(f"  Title: {title}")
    print(f"  Text: {len(text.split())} words")
    if len(text.split()) < 100:
        print("[WARN] Article too short, picking another...")
        used.add(article_url)
        _save_used_articles(used)
        article_url = _pick_article(filtered, used)
        if not article_url:
            sys.exit(1)
        title, text = _scrape_article(article_url)

    # 3. Two-step LLM
    print("[3/7] Extracting facts (Step 1)...")
    facts = step1_extract_facts(title, text)
    if not facts:
        print("[ERROR] Failed to extract facts")
        sys.exit(1)

    print("[4/7] Generating script (Step 2)...")
    script_data = None
    for attempt in range(2):
        script_data = step2_generate_script(facts, title)
        if script_data:
            break
        print(f"[RETRY] Script generation attempt {attempt + 2}...")

    if not script_data:
        print("[ERROR] Failed to generate script")
        sys.exit(1)

    script_text = script_data["script"]
    meta = {
        "title": script_data.get("title", title)[:100],
        "description": script_data.get("description", "") + _DESCRIPTION_FOOTER,
        "tags": list(dict.fromkeys(script_data.get("tags", []) + _CORE_TAGS))[:20],
        "topic": title,
    }

    # Save metadata
    METADATA_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Title: {meta['title']}")
    print(f"  Script: {len(script_text.split())} words")

    # 5. TTS
    print("[5/7] Generating voiceover (edge-tts)...")
    audio_path, word_events = generate_tts(script_text)
    voice_dur = _probe_duration(audio_path)
    print(f"  Duration: {voice_dur:.1f}s ({voice_dur/60:.1f} min)")

    # 6. Download clips
    print("[6/7] Downloading video clips...")
    pexels_queries = script_data.get("pexels_queries", [])
    clips = download_clips(extra_queries=pexels_queries, target=40)
    if not clips:
        print("[ERROR] No clips downloaded")
        sys.exit(1)

    music = download_music()

    # 7. Assemble video
    print("[7/7] Assembling video with ffmpeg...")
    assemble_video(clips, audio_path, word_events, music)

    # Upload
    print("[UPLOAD] Uploading to YouTube...")
    video_id = upload_video(meta)

    # Track used article
    used.add(article_url)
    _save_used_articles(used)
    print(f"[DONE] Article tracked. Total used: {len(used)}")

    # Cleanup temp
    temp = BUILD_DIR / "temp"
    if temp.is_dir():
        shutil.rmtree(temp)


if __name__ == "__main__":
    main()
