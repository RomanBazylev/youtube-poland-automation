import asyncio
import json
import os
import random
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
from PIL import Image

import edge_tts
import requests
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    TextClip,
    VideoFileClip,
    CompositeVideoClip,
    concatenate_audioclips,
    concatenate_videoclips,
    vfx,
    afx,
)

# ── Константы ──────────────────────────────────────────────────────────
TARGET_W, TARGET_H = 1080, 1920
BUILD_DIR = Path("build")
CLIPS_DIR = BUILD_DIR / "clips"
AUDIO_DIR = BUILD_DIR / "audio_parts"
MUSIC_PATH = BUILD_DIR / "music.mp3"

# Голос: русский, ротация для разнообразия
TTS_VOICES = [
    "ru-RU-DmitryNeural",
    "ru-RU-SvetlanaNeural",
]
TTS_RATE_OPTIONS = ["+5%", "+8%", "+10%"]

# Произношение польских слов и терминов для TTS
TTS_PRONUNCIATION_FIXES = {
    "ZUS": "ЗУС",
    "NFZ": "Эн Эф Зэт",
    "PESEL": "пэ́сэль",
    "NIP": "НИП",
    "REGON": "рэ́гон",
    "KRS": "Ка Эр Эс",
    "PIT": "ПИТ",
    "VAT": "ВАТ",
    "Kraków": "Кра́ков",
    "Wrocław": "Вро́цлав",
    "Gdańsk": "Гда́ньск",
    "Poznań": "По́знань",
    "Łódź": "Лодзь",
    "Katowice": "Като́вице",
    "Warszawa": "Варша́ва",
    "Zakopane": "Закопа́нэ",
    "Toruń": "То́рунь",
    "Lublin": "Лю́блин",
    "złoty": "зло́тый",
    "złotych": "зло́тых",
    "zł": "злотых",
    "Karta Polaka": "Ка́рта По́ляка",
    "Karta pobytu": "Ка́рта по́быту",
    "pobyt": "по́быт",
    "meldunek": "мэ́льдунэк",
    "urząd": "у́жонд",
    "gmina": "гми́на",
    "województwo": "воево́дзтво",
    "powiat": "по́вят",
    "Biedronka": "Бедро́нка",
    "Lidl": "Лидл",
    "Żabka": "Жа́бка",
    "Allegro": "Алле́гро",
    "OLX": "О Эл Икс",
    "PKP": "Пэ Ка Пэ",
    "Flixbus": "Фли́ксбус",
}

# Стили подачи
ANGLES = [
    "топ мест, которые обязательно стоит посетить",
    "лайфхак, о котором не знают новоприбывшие",
    "ошибка, которую делают 90% переехавших",
    "честное сравнение: Польша vs ожидания",
    "пошаговая инструкция для новичка",
    "сколько реально стоит жизнь в Польше в 2025 году",
    "что изменилось в законах в 2024-2025 году",
    "секрет, который экономит сотни злотых",
    "история из реальной жизни с полезным выводом",
    "мифы про Польшу, которые пора развеять",
    "бесплатные возможности, о которых мало кто знает",
    "что нужно сделать в первый месяц после переезда",
    "пошаговый чек-лист для переезда в Польшу",
    "личный опыт: как я решал эту проблему",
]

# Темы контента
TOPICS = [
    "легализация и карта побыту",
    "PESEL и регистрация по месту жительства",
    "медицина и NFZ",
    "аренда жилья",
    "работа и трудоустройство",
    "открытие бизнеса",
    "налоги PIT и VAT",
    "пособия на детей (800+)",
    "бесплатное образование",
    "польский язык для начинающих",
    "транспорт и PKP",
    "банковский счёт и финансы",
    "интересные места в Кракове",
    "Варшава — что посмотреть",
    "Вроцлав — секретные локации",
    "Гданьск и побережье Балтики",
    "горы Закопане и Татры",
    "польская кухня и рестораны",
    "шоппинг и скидки",
    "права иностранцев в Польше",
    "страхование в Польше",
    "водительские права и авто",
    "Карта Поляка — как получить",
    "сезонные фестивали и события",
    "природа и национальные парки",
    "переезд с семьёй",
    "интеграция и культурные различия",
]

# Города для рандомизации
CITIES = [
    "Варшава", "Краков", "Вроцлав", "Гданьск", "Познань",
    "Лодзь", "Катовице", "Люблин", "Закопане", "Торунь",
]

# Запросы для Pexels
PEXELS_QUERIES = [
    "Poland city",
    "Krakow old town",
    "Warsaw skyline",
    "Polish food",
    "European street",
    "mountain landscape Poland",
    "Baltic sea beach",
    "European architecture",
    "travel Europe",
    "city life Europe",
]


@dataclass
class ScriptPart:
    text: str


@dataclass
class VideoMetadata:
    title: str
    description: str
    tags: List[str]


def ensure_dirs() -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def _clean_build_dir() -> None:
    """Удаляет build/ перед каждым запуском, чтобы не использовать старые файлы."""
    if BUILD_DIR.is_dir():
        shutil.rmtree(BUILD_DIR)
        print("[CLEAN] Removed old build directory")


_DESCRIPTION_FOOTER = (
    "\n\n---\n"
    "Подписывайся на «Я в Польше» — новый ролик каждый день! 🔔\n"
    "Задавай вопросы в комментариях 👇"
)

_CORE_TAGS = [
    "shorts", "польша", "явпольше", "переезд", "легализация",
    "жизнь в польше", "европа", "эмиграция", "советы",
]


def _enrich_metadata(meta: VideoMetadata) -> VideoMetadata:
    """Обогащает метаданные для SEO."""
    title = meta.title
    if "#shorts" not in title.lower():
        title = title.rstrip() + " #shorts"
    title = title[:100]

    desc = meta.description.rstrip()
    if _DESCRIPTION_FOOTER not in desc:
        desc += _DESCRIPTION_FOOTER

    merged_tags = list(dict.fromkeys(meta.tags + _CORE_TAGS))[:20]

    return VideoMetadata(title=title, description=desc, tags=merged_tags)


# Фразы-наполнители, которые делают контент слабым
_FILLER_PATTERNS = [
    "мой день начинается", "я не ожидал", "это невероятно", "это было круто",
    "ты не поверишь", "это удивительно", "я был в шоке", "это работает",
    "попробуй сам", "ты должен это знать", "слушай внимательно",
    "сейчас расскажу", "давай разберёмся", "многие не знают",
]


def _validate_script(parts: List[ScriptPart]) -> bool:
    """Проверяет качество сценария."""
    if len(parts) < 8:
        print(f"[QUALITY] Rejected: too few parts ({len(parts)}, need >=8)")
        return False

    avg_words = sum(len(p.text.split()) for p in parts) / len(parts)
    if avg_words < 7:
        print(f"[QUALITY] Rejected: avg words too low ({avg_words:.1f}, need >=7)")
        return False

    filler_count = 0
    for part in parts:
        text_lower = part.text.lower()
        for filler in _FILLER_PATTERNS:
            if filler in text_lower:
                filler_count += 1
                print(f"[QUALITY] Filler detected: '{part.text}'")
                break
    if filler_count > 2:
        print(f"[QUALITY] Rejected: too many fillers ({filler_count})")
        return False

    # Минимум 35% фраз с конкретикой (цифры, названия, действия)
    concrete_markers = re.compile(
        r'\d|злот|евро|рубл|месяц|недел|год|день|час|'
        r'адрес|документ|паспорт|виз|карт[аеу]|заявлен|'
        r'регистрац|прописк|страхов|пособ|налог|'
        r'зайди|оформи|подай|получи|открой|зарегистрируй|найди|позвони|напиши|проверь|'
        r'бесплатн|скидк|стоит|цена|зарплат|аренд|'
        r'варшав|краков|вроцлав|гданьск|познань|польш|'
        r'песель|нфз|зус|мельдунэк|побыту|уженд|гмин',
        re.IGNORECASE,
    )
    concrete_count = sum(1 for p in parts if concrete_markers.search(p.text))
    ratio = concrete_count / len(parts)
    if ratio < 0.35:
        print(f"[QUALITY] Rejected: not enough concrete content ({ratio:.0%}, need >=35%)")
        return False

    # Проверка связности — хотя бы 20% фраз содержат переходные слова
    transition_markers = re.compile(
        r'после этого|следующий|а вот|кстати|поэтому|'
        r'но главное|в итоге|например|а если|'
        r'первое|второе|третье|четвёртое|пятое|'
        r'для этого|потом|затем|дальше|также|'
        r'и ещё|кроме того|помимо|важно|главное',
        re.IGNORECASE,
    )
    transition_count = sum(1 for p in parts if transition_markers.search(p.text))
    t_ratio = transition_count / len(parts)
    # Мягкая проверка — только для информации, не реджектим
    if t_ratio < 0.15:
        print(f"[QUALITY] Note: low transition words ({t_ratio:.0%}), but accepting")

    print(f"[QUALITY] Passed: {len(parts)} parts, avg {avg_words:.1f} words, {ratio:.0%} concrete, {t_ratio:.0%} transitions")
    return True


# ── Фоллбек-сценарии (пул) ─────────────────────────────────────────────
_FALLBACK_POOL = [
    # [0] — 5 вещей после переезда
    [
        ScriptPart("Переехал в Польшу? Вот пять вещей, которые нужно сделать в первый же месяц."),
        ScriptPart("Первое — получи ПЕСЕЛЬ. Без него не откроешь счёт в банке и не оформишь карту побыту."),
        ScriptPart("Идёшь в ближайший уженд гмины с паспортом и договором аренды. Занимает двадцать минут."),
        ScriptPart("Второе — зарегистрируйся в НФЗ. Это даёт бесплатную медицину: врач, больница, скорая."),
        ScriptPart("Работодатель обязан тебя застраховать. Проверь, что он платит взносы в ЗУС."),
        ScriptPart("Третье — открой банковский счёт. Без него не получишь зарплату и не оплатишь квартиру."),
        ScriptPart("Рекомендую мБанк или ПКО — у них есть приложения на русском и английском."),
        ScriptPart("Четвёртое — оформи карту побыту, если планируешь остаться дольше трёх месяцев."),
        ScriptPart("Подаёшь документы в воеводский уженд. Стоит 440 злотых, ждать от месяца до полугода."),
        ScriptPart("Пятое — выучи хотя бы базовый польский. Даже пятьдесят слов упрощают жизнь в десять раз."),
        ScriptPart("Сохрани это видео и напиши в комментариях, что было самым сложным после переезда. Подпишись!"),
    ],
    # [1] — Аренда жилья в Польше
    [
        ScriptPart("Ищешь квартиру в Польше? Средняя аренда однушки в Варшаве — от 2500 до 3500 злотых в месяц."),
        ScriptPart("В Кракове и Вроцлаве дешевле — от 1800 злотых. В маленьких городах можно найти за 1200."),
        ScriptPart("Ищи на сайтах О Эл Икс, Ото Дом и в группах на Фейсбуке. Там больше вариантов от хозяев напрямую."),
        ScriptPart("Перед съёмом обязательно подпиши договор найма. Без него тебя не пропишут и не дадут мельдунэк."),
        ScriptPart("Залог обычно равен одной месячной ставке. Вернут при выезде, если квартира в порядке."),
        ScriptPart("Коммуналка отдельно: вода, газ, электричество, вывоз мусора — это ещё 400-700 злотых сверху."),
        ScriptPart("Важно: в договоре должен быть указан срок, сумма и условия расторжения. Читай внимательно."),
        ScriptPart("Совет — приезжай смотреть вживую. Фото часто не совпадают с реальностью."),
        ScriptPart("Напиши в комментариях, сколько ты платишь за аренду и в каком городе. Сохрани видео, пригодится!"),
    ],
    # [2] — Медицина в Польше
    [
        ScriptPart("Заболел в Польше? Если ты работаешь официально, у тебя есть бесплатная медицина через НФЗ."),
        ScriptPart("Первый шаг — зарегистрируйся в поликлинике, по-польски это называется пшыходня."),
        ScriptPart("Выбираешь врача первого контакта — это терапевт, который даёт направления к специалистам."),
        ScriptPart("Запись к терапевту бесплатная, но очередь к специалисту может быть от двух недель до трёх месяцев."),
        ScriptPart("Лекарства по рецепту стоят от 3 до 20 злотых. Без рецепта — полная цена, иногда в пять раз дороже."),
        ScriptPart("Скорая помощь — звони 112. Это бесплатно для всех, даже без страховки."),
        ScriptPart("Если нужен врач быстро, есть частные клиники: Люкс Мед, Ме́дикове́р, Энел Мед. Визит от 150 злотых."),
        ScriptPart("Многие компании дают пакет частной медицины как бонус к зарплате. Спроси у работодателя."),
        ScriptPart("Сохрани видео, чтобы не потерять. Напиши, какой у тебя опыт с польской медициной!"),
    ],
    # [3] — Транспорт в Польше
    [
        ScriptPart("Как передвигаться по Польше и не разориться? Вот проверенные способы экономить на транспорте."),
        ScriptPart("Поезда Пэ Ка Пэ Интерсити — самый удобный способ между городами. Варшава—Краков за 60–120 злотых."),
        ScriptPart("Покупай билеты на сайте заранее — за две-три недели цена вдвое ниже."),
        ScriptPart("Фликсбус — бюджетный вариант. Краков—Вроцлав от 19 злотых, если бронировать рано."),
        ScriptPart("В городах — месячный проездной от 90 до 130 злотых. Экономит, если ездишь каждый день."),
        ScriptPart("Приложение Як До Яде показывает все автобусы и трамваи в реальном времени. Ставь обязательно."),
        ScriptPart("Для такси используй Болт или Убер. Средняя поездка по городу — 15–25 злотых."),
        ScriptPart("Если нужна машина на день — каршеринг Пачшау или Трафикар от 0,70 злотых за минуту."),
        ScriptPart("Подпишись на канал и напиши, каким транспортом пользуешься чаще всего. Сохрани!"),
    ],
]

_FALLBACK_META_POOL = [
    VideoMetadata(
        title="5 вещей сразу после переезда в Польшу 🇵🇱 #shorts",
        description="Переехал в Польшу? Вот 5 шагов, которые нужно сделать в первый месяц.\nСохрани, чтобы не забыть!\n\n#польша #переезд #легализация #явпольше #shorts",
        tags=["польша", "переезд", "легализация", "явпольше", "shorts", "лайфхак", "европа"],
    ),
    VideoMetadata(
        title="Аренда квартиры в Польше — реальные цены 2025 🏠 #shorts",
        description="Сколько стоит аренда в Польше? Варшава, Краков, Вроцлав — реальные цифры.\n\n#польша #аренда #жильё #явпольше #shorts",
        tags=["польша", "аренда", "жильё", "квартира", "явпольше", "shorts", "варшава", "краков"],
    ),
    VideoMetadata(
        title="Бесплатная медицина в Польше — как работает НФЗ 🏥 #shorts",
        description="Работаешь официально? У тебя есть бесплатная медицина. Вот как ей пользоваться.\n\n#польша #медицина #НФЗ #явпольше #shorts",
        tags=["польша", "медицина", "НФЗ", "здоровье", "явпольше", "shorts", "страховка"],
    ),
    VideoMetadata(
        title="Транспорт в Польше — как ездить дёшево 🚆 #shorts",
        description="Поезда, автобусы, такси — как экономить на транспорте в Польше.\n\n#польша #транспорт #экономия #явпольше #shorts",
        tags=["польша", "транспорт", "поезда", "автобусы", "явпольше", "shorts", "экономия"],
    ),
]


def _fallback_script() -> tuple:
    idx = random.randrange(len(_FALLBACK_POOL))
    print(f"[FALLBACK] Using fallback script #{idx}")
    return _FALLBACK_POOL[idx], _enrich_metadata(_FALLBACK_META_POOL[idx])


def call_groq_for_script() -> tuple:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("[WARN] GROQ_API_KEY not set")
        return _fallback_script()

    angle = random.choice(ANGLES)
    topic = random.choice(TOPICS)
    city = random.choice(CITIES)

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    system_prompt = (
        "Ты — русскоязычный блогер, живущий в Польше уже 5 лет. Канал 'Я в Польше'. "
        "Ты пишешь сценарии YouTube Shorts с РЕАЛЬНЫМИ полезными советами.\n\n"
        "ГЛАВНОЕ ПРАВИЛО: каждая следующая фраза ЛОГИЧЕСКИ продолжает предыдущую. "
        "Сценарий = связный рассказ, а НЕ набор случайных фактов. "
        "Фразы идут как шаги одной истории: ситуация → проблема → решение → результат → вывод.\n\n"
        "СВЯЗНОСТЬ: используй переходные слова между фразами: "
        "'после этого', 'следующий шаг', 'а вот тут интересно', 'кстати', 'и ещё важно', "
        "'но главное', 'в итоге', 'поэтому', 'например', 'а если'.\n\n"
        "АКТУАЛЬНОСТЬ: пиши ТОЛЬКО актуальную информацию на 2025 год. "
        "НЕ упоминай устаревшие суммы, отменённые программы или старые законы. "
        "Если не уверен в конкретной цифре — используй диапазон ('от X до Y злотых').\n\n"
        "КОНКРЕТИКА: суммы в злотых, названия документов, реальные адреса, сроки, пошаговые действия. "
        "ЗАПРЕЩЕНЫ пустые фразы: 'Это невероятно', 'Ты не поверишь', 'Это удивительно'.\n\n"
        "ПРОИЗНОШЕНИЕ: польские термины пиши кириллицей: "
        "PESEL → ПЕСЕЛЬ, NFZ → НФЗ, ZUS → ЗУС, Urząd Gminy → уженд гмины, "
        "Karta pobytu → карта побыту, złotych → злотых, meldunek → мельдунэк.\n\n"
        "Отвечай ТОЛЬКО валидным JSON без markdown-обёрток."
    )

    user_prompt = f"""Напиши сценарий YouTube Shorts (45–60 секунд) для канала «Я в Польше».

КОНТЕКСТ:
- Тема: {topic}
- Город: {city}
- Стиль: {angle}
- Год: 2025

СТРУКТУРА СЦЕНАРИЯ (обязательно следуй этому плану):
1. ХУК (1 фраза) — шокирующий факт с цифрой или провокационный вопрос. Цепляет с первой секунды.
2. КОНТЕКСТ (1–2 фразы) — почему это важно, кого касается, когда актуально.
3. ОСНОВНАЯ ЧАСТЬ (5–8 фраз) — пошаговое раскрытие темы. Каждая фраза содержит сумму, срок, адрес, название документа или конкретное действие. Фразы СВЯЗАНЫ друг с другом логически — каждая следующая продолжает предыдущую.
4. ВЫВОД (1 фраза) — итог: что зритель должен запомнить.
5. CTA (1 фраза) — призыв сохранить, подписаться, написать в комментариях.

ТРЕБОВАНИЯ:
- 10–14 фраз всего.
- Каждая фраза = 1–2 предложения, 10–25 слов.
- Обращение на «ты», как друг рассказывает другу.
- Язык — живой разговорный русский. Польские термины — КИРИЛЛИЦЕЙ.
- ТОЛЬКО актуальная информация 2025 года. Никаких устаревших цифр.
- Между фразами обязательны логические связки (после этого, следующий шаг, а вот тут, кстати, поэтому).

ПЛОХО (набор несвязных фраз):
"В Польше вкусная еда." / "ПЕСЕЛЬ нужен для банка." / "Краков красивый город." — ЭТО ЗАПРЕЩЕНО.

ХОРОШО (связный рассказ):
"Приехал в Краков и первым делом пошёл в уженд гмины за ПЕСЕЛем." / "Без него не откроешь счёт в банке — а без счёта не получишь зарплату." / "Поэтому следующий шаг — идёшь в мБанк с ПЕСЕЛем и паспортом."

Формат — строго JSON:
{{
  "title": "Цепляющий заголовок, до 80 символов, с эмодзи 🇵🇱 и #shorts в конце",
  "description": "Описание 3–5 строк с хештегами:\\n- первая строка — о чём видео\\n- вторая — ключевой совет\\n- третья — хештеги (#польша #явпольше #shorts ...)",
  "tags": ["польша", "явпольше", "shorts", ...ещё 10–15 тематических тегов],
  "pexels_queries": ["3–5 коротких англ. запросов для поиска видео на Pexels"],
  "parts": [
    {{ "text": "Связная фраза с конкретным советом, 10-25 слов" }}
  ]
}}"""

    print(f"  Topic: {topic} | City: {city} | Angle: {angle}")

    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.85,
        "max_tokens": 2048,
    }

    def _try_api(payload: dict) -> Optional[requests.Response]:
        for attempt in range(1, 3):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=45)
                r.raise_for_status()
                return r
            except Exception as exc:
                print(f"[WARN] Groq API attempt {attempt} failed: {exc}")
        return None

    def _parse_response(resp: requests.Response) -> Optional[tuple]:
        try:
            content = resp.json()["choices"][0]["message"]["content"]
            content = re.sub(r"^```(?:json)?\s*", "", content.strip())
            content = re.sub(r"\s*```$", "", content.strip())
            data = json.loads(content)
            parts = [ScriptPart(p["text"]) for p in data.get("parts", []) if p.get("text")]
            metadata = VideoMetadata(
                title=data.get("title", "")[:100] or "Я в Польше: советы и лайфхаки #shorts",
                description=data.get("description", "") or "Смотри до конца! #польша #явпольше #shorts",
                tags=data.get("tags", ["польша", "явпольше", "shorts"]),
            )
            llm_queries = data.get("pexels_queries", [])
            if llm_queries:
                global _llm_pexels_queries
                _llm_pexels_queries = [q for q in llm_queries if isinstance(q, str)][:5]
            if _validate_script(parts):
                return parts, _enrich_metadata(metadata)
            print("[WARN] LLM output failed quality check")
        except Exception as exc:
            print(f"[WARN] Parse error: {exc}")
        return None

    # Attempt 1 — основной запрос
    resp = _try_api(body)
    if resp:
        result = _parse_response(resp)
        if result:
            return result

    # Attempt 2 — усиленный промпт, выше температура
    print("[RETRY] Retrying with reinforced prompt...")
    body["messages"].append({
        "role": "user",
        "content": (
            "ВАЖНО: предыдущий ответ не прошёл проверку качества. "
            "Убедись, что:\n"
            "1. Все фразы ЛОГИЧЕСКИ связаны — сценарий читается как ОДНА ИСТОРИЯ, а не список фактов.\n"
            "2. Есть конкретика: суммы, сроки, названия.\n"
            "3. Минимум 10 фраз, каждая 10-25 слов.\n"
            "4. Информация актуальна на 2025 год.\n"
            "Верни JSON в том же формате."
        ),
    })
    body["temperature"] = 1.0
    resp = _try_api(body)
    if resp:
        result = _parse_response(resp)
        if result:
            return result

    return _fallback_script()


# Глобальная переменная для LLM-сгенерированных запросов Pexels
_llm_pexels_queries: List[str] = []


# ── Скачивание клипов ─────────────────────────────────────────────────
def _download_file(url: str, dest: Path) -> None:
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with dest.open("wb") as f:
        for chunk in r.iter_content(chunk_size=32768):
            if chunk:
                f.write(chunk)


def _pexels_best_file(video_files: list) -> Optional[dict]:
    """Pick the best HD file from Pexels video_files list."""
    hd = [f for f in video_files if (f.get("height") or 0) >= 720]
    if hd:
        return min(hd, key=lambda f: abs((f.get("height") or 0) - 1920))
    if video_files:
        return max(video_files, key=lambda f: f.get("height") or 0)
    return None


def download_pexels_clips(target_count: int = 14) -> List[Path]:
    """Download clips using LLM-generated + fallback queries."""
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        return []

    headers = {"Authorization": api_key}
    all_queries = list(_llm_pexels_queries)
    extra = [q for q in PEXELS_QUERIES if q not in all_queries]
    random.shuffle(extra)
    all_queries.extend(extra)
    queries = all_queries[:target_count]
    result_paths: List[Path] = []
    seen_ids: set = set()
    clip_idx = 0

    for query in queries:
        if len(result_paths) >= target_count:
            break
        params = {
            "query": query,
            "per_page": 3,
            "orientation": "portrait",
        }
        try:
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                headers=headers, params=params, timeout=30,
            )
            resp.raise_for_status()
        except Exception as exc:
            print(f"[WARN] Pexels search '{query}' failed: {exc}")
            continue

        for video in resp.json().get("videos", []):
            vid_id = video.get("id")
            if vid_id in seen_ids:
                continue
            seen_ids.add(vid_id)
            best = _pexels_best_file(video.get("video_files", []))
            if not best:
                continue
            clip_idx += 1
            clip_path = CLIPS_DIR / f"pexels_{clip_idx}.mp4"
            try:
                _download_file(best["link"], clip_path)
                result_paths.append(clip_path)
                print(f"    Pexels [{query}] -> clip {clip_idx}")
            except Exception as exc:
                print(f"[WARN] Pexels clip {clip_idx} download failed: {exc}")
            if len(result_paths) >= target_count:
                break

    return result_paths


def download_pixabay_clips(max_clips: int = 3) -> List[Path]:
    api_key = os.getenv("PIXABAY_API_KEY")
    if not api_key:
        return []

    params = {
        "key": api_key,
        "q": random.choice(_llm_pexels_queries or ["Poland city", "European travel", "Krakow"]),
        "per_page": max_clips,
        "safesearch": "true",
        "order": "popular",
    }

    try:
        resp = requests.get(
            "https://pixabay.com/api/videos/",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"[WARN] Pixabay API error: {exc}")
        return []

    data = resp.json()
    result_paths: List[Path] = []

    for idx, hit in enumerate(data.get("hits", [])[:max_clips], start=1):
        videos = hit.get("videos") or {}
        cand = videos.get("large") or videos.get("medium") or videos.get("small")
        if not cand or "url" not in cand:
            continue
        url = cand["url"]
        clip_path = CLIPS_DIR / f"pixabay_{idx}.mp4"
        try:
            _download_file(url, clip_path)
            result_paths.append(clip_path)
        except Exception as exc:
            print(f"[WARN] Failed to download Pixabay clip {idx}: {exc}")

    return result_paths


def download_background_music() -> Optional[Path]:
    if os.getenv("DISABLE_BG_MUSIC") == "1":
        return None

    candidate_urls = [
        "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Komiku/Its_time_for_adventure/Komiku_-_05_-_Friends.mp3",
        "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Podington_Bear/Daydream/Podington_Bear_-_Daydream.mp3",
        "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/ccCommunity/Chad_Crouch/Arps/Chad_Crouch_-_Shipping_Lanes.mp3",
        "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Lobo_Loco/Folkish_things/Lobo_Loco_-_01_-_Acoustic_Dreams_ID_1199.mp3",
    ]

    for url in random.sample(candidate_urls, len(candidate_urls)):
        try:
            _download_file(url, MUSIC_PATH)
            return MUSIC_PATH
        except Exception:
            continue
    return None


# ── TTS (edge-tts, по-фразово) ────────────────────────────────────────
def _fix_pronunciation(text: str) -> str:
    """Заменяет сложные для TTS слова на фонетические эквиваленты."""
    result = text
    for word, replacement in TTS_PRONUNCIATION_FIXES.items():
        result = re.sub(re.escape(word), replacement, result, flags=re.IGNORECASE)
    return result


async def _generate_all_audio(parts: List[ScriptPart]) -> List[Path]:
    """Генерирует все аудио-фразы параллельно."""
    voice = random.choice(TTS_VOICES)
    rate = random.choice(TTS_RATE_OPTIONS)
    print(f"  TTS voice: {voice}, rate: {rate}")
    audio_paths: List[Path] = []
    tasks = []
    for i, part in enumerate(parts):
        out = AUDIO_DIR / f"part_{i}.mp3"
        audio_paths.append(out)
        tts_text = _fix_pronunciation(part.text)
        comm = edge_tts.Communicate(tts_text, voice, rate=rate)
        tasks.append(comm.save(str(out)))
    await asyncio.gather(*tasks)
    return audio_paths


def build_tts_per_part(parts: List[ScriptPart]) -> List[Path]:
    """Генерирует отдельный mp3 для каждой фразы."""
    return asyncio.run(_generate_all_audio(parts))


# ── Сборка видео ──────────────────────────────────────────────────────
def _fit_clip_to_frame(clip: VideoFileClip, duration: float) -> VideoFileClip:
    """Подрезает/зацикливает клип до нужной длительности и кропит в 9:16."""
    if clip.duration > duration + 0.5:
        max_start = clip.duration - duration
        start = random.uniform(0, max_start)
        segment = clip.subclip(start, start + duration)
    else:
        segment = clip.fx(vfx.loop, duration=duration)

    margin = 1.10
    src_ratio = segment.w / segment.h
    target_ratio = TARGET_W / TARGET_H
    if src_ratio > target_ratio:
        segment = segment.resize(height=int(TARGET_H * margin))
    else:
        segment = segment.resize(width=int(TARGET_W * margin))

    segment = segment.crop(
        x_center=segment.w / 2, y_center=segment.h / 2,
        width=TARGET_W, height=TARGET_H,
    )
    return segment


def _apply_ken_burns(clip, duration: float):
    """Медленный zoom для динамики."""
    direction = random.choice(["in", "out"])
    start_scale = 1.0
    end_scale = random.uniform(1.06, 1.12)
    if direction == "out":
        start_scale, end_scale = end_scale, start_scale

    def make_frame(get_frame, t):
        progress = t / max(duration, 0.01)
        scale = start_scale + (end_scale - start_scale) * progress
        frame = get_frame(t)
        h, w = frame.shape[:2]
        new_h, new_w = int(h * scale), int(w * scale)
        img = Image.fromarray(frame)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        arr = np.array(img)
        y_off = (new_h - h) // 2
        x_off = (new_w - w) // 2
        return arr[y_off:y_off + h, x_off:x_off + w]

    return clip.fl(make_frame)


def _make_subtitle(text: str, duration: float) -> list:
    """Субтитр с обводкой."""
    shadow = (
        TextClip(
            text,
            fontsize=72,
            color="black",
            font="DejaVu-Sans-Bold",
            method="caption",
            size=(TARGET_W - 80, None),
            stroke_color="black",
            stroke_width=5,
        )
        .set_position(("center", 0.70), relative=True)
        .set_duration(duration)
    )
    main_txt = (
        TextClip(
            text,
            fontsize=72,
            color="white",
            font="DejaVu-Sans-Bold",
            method="caption",
            size=(TARGET_W - 80, None),
            stroke_color="black",
            stroke_width=3,
        )
        .set_position(("center", 0.70), relative=True)
        .set_duration(duration)
    )
    return [shadow, main_txt]


def build_video(
    parts: List[ScriptPart],
    clip_paths: List[Path],
    audio_parts: List[Path],
    music_path: Optional[Path],
) -> Path:
    if not clip_paths:
        raise RuntimeError("No video clips downloaded. Provide PEXELS_API_KEY or PIXABAY_API_KEY.")

    part_audios = [AudioFileClip(str(p)) for p in audio_parts]
    durations = [a.duration for a in part_audios]
    total_duration = sum(durations)

    voice = concatenate_audioclips(part_audios)

    if len(clip_paths) >= len(parts):
        chosen_clips = random.sample(clip_paths, len(parts))
    else:
        chosen_clips = clip_paths[:]
        random.shuffle(chosen_clips)
        while len(chosen_clips) < len(parts):
            chosen_clips.append(random.choice(clip_paths))

    source_clips = []
    video_clips = []
    for i, part in enumerate(parts):
        src_path = chosen_clips[i]
        clip = VideoFileClip(str(src_path))
        source_clips.append(clip)
        dur = durations[i]

        fitted = _fit_clip_to_frame(clip, dur)
        fitted = _apply_ken_burns(fitted, dur)

        subtitle_layers = _make_subtitle(part.text, dur)

        composed = CompositeVideoClip(
            [fitted] + subtitle_layers,
            size=(TARGET_W, TARGET_H),
        ).set_duration(dur)
        video_clips.append(composed)

    FADE_DUR = 0.2
    for idx in range(1, len(video_clips)):
        video_clips[idx] = video_clips[idx].crossfadein(FADE_DUR)

    video = concatenate_videoclips(video_clips, method="compose").set_duration(total_duration)

    audio_tracks = [voice]
    bg = None
    if music_path and music_path.is_file():
        bg = AudioFileClip(str(music_path)).volumex(0.13)
        bg = bg.set_duration(total_duration)
        bg = bg.fx(afx.audio_fadeout, min(1.5, total_duration * 0.1))
        audio_tracks.append(bg)

    final_audio = CompositeAudioClip(audio_tracks)
    video = video.set_audio(final_audio).set_duration(total_duration)

    output_path = BUILD_DIR / "output_poland_short.mp4"
    video.write_videofile(
        str(output_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        bitrate="8000k",
        threads=4,
    )

    voice.close()
    if bg is not None:
        bg.close()
    for a in part_audios:
        a.close()
    for vc in video_clips:
        vc.close()
    for sc in source_clips:
        sc.close()
    video.close()

    return output_path


def _save_metadata(meta: VideoMetadata) -> None:
    """Сохраняет метаданные видео в JSON."""
    meta_path = BUILD_DIR / "metadata.json"
    meta_path.write_text(
        json.dumps(
            {"title": meta.title, "description": meta.description, "tags": meta.tags},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  Metadata saved to {meta_path}")


def main() -> None:
    _clean_build_dir()
    ensure_dirs()
    print("[1/5] Generating script...")
    parts, metadata = call_groq_for_script()
    print(f"  Script: {len(parts)} parts")
    print(f"  Title: {metadata.title}")
    total_words = 0
    for i, p in enumerate(parts, 1):
        wc = len(p.text.split())
        total_words += wc
        print(f"  [{i}] ({wc}w) {p.text}")
    est_duration = total_words / 2.3
    print(f"  Estimated duration: ~{est_duration:.0f}s ({total_words} words)")
    _save_metadata(metadata)

    print("[2/5] Downloading video clips...")
    clip_paths = download_pexels_clips()
    clip_paths += download_pixabay_clips()
    print(f"  Downloaded {len(clip_paths)} clips")

    print("[3/5] Generating TTS audio (edge-tts, per-part)...")
    audio_parts = build_tts_per_part(parts)
    for i, ap in enumerate(audio_parts):
        a = AudioFileClip(str(ap))
        print(f"  Part {i+1}: {a.duration:.1f}s")
        a.close()

    print("[4/5] Downloading background music...")
    music_path = download_background_music()

    print("[5/5] Building final video...")
    output = build_video(parts, clip_paths, audio_parts, music_path)
    print(f"Done! Video saved to: {output}")


if __name__ == "__main__":
    main()
