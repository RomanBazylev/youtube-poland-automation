import asyncio
import json
import os
import random
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
from PIL import Image
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

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
HISTORY_PATH = BUILD_DIR / "topic_history.json"
MAX_HISTORY = 10

# Голос: русский, ротация для разнообразия
TTS_VOICES = [
    "ru-RU-DmitryNeural",
    "ru-RU-SvetlanaNeural",
]
TTS_RATE_OPTIONS = ["+5%", "+8%", "+10%"]

# Произношение польских слов и терминов для TTS
TTS_PRONUNCIATION_FIXES = {
    # Города
    "Kraków": "Кра́ков",
    "Кракове": "Кра́кове",
    "Wrocław": "Вро́цлав",
    "Gdańsk": "Гда́ньск",
    "Poznań": "По́знань",
    "Łódź": "Лодзь",
    "Katowice": "Като́вице",
    "Warszawa": "Варша́ва",
    "Zakopane": "Закопа́нэ",
    "Toruń": "То́рунь",
    "Lublin": "Лю́блин",
    "Sopot": "Со́пот",
    "Malbork": "Ма́льборк",
    "Wieliczka": "Вели́чка",
    "Kazimierz": "Кази́меж",
    "Kazimierz Dolny": "Кази́меж До́льны",
    "Białowieża": "Беловежа",
    "Mazury": "Мазу́ры",
    # Кухня — блюда
    "pierogi": "перо́ги",
    "пероги": "перо́ги",
    "żurek": "жу́рек",
    "журек": "жу́рек",
    "bigos": "би́гос",
    "бигос": "би́гос",
    "obwarzanek": "обважа́нэк",
    "обважанек": "обважа́нэк",
    "zapiekanka": "запека́нка",
    "sernik": "сэ́рник",
    "сэрник": "сэ́рник",
    "szarlotka": "шарло́тка",
    "pączki": "по́нчки",
    "pączek": "по́нчек",
    "gołąbki": "голо́мпки",
    "голомпки": "голо́мпки",
    "oscypek": "осци́пек",
    "осципек": "осци́пек",
    "flaczki": "фля́чки",
    "kielbasa": "кел-ба́са",
    "placki ziemniaczane": "пла́цки земня́чанэ",
    "żubrówka": "жубру́вка",
    "miód pitny": "мюд пи́тны",
    "rogal świętomarciński": "ро́гал свенто-марци́ньски",
    # Кухня — места еды
    "mleczny bar": "мле́чны бар",
    "млечный бар": "мле́чны бар",
    "cukiernia": "цуке́рня",
    "kawiarnia": "кавя́рня",
    "restauracja": "рэстаура́цья",
    # Культура и места
    "Wawel": "Ва́вэль",
    "Вавель": "Ва́вэль",
    "Sukiennice": "Суке́нницэ",
    "Сукенницэ": "Суке́нницэ",
    "Rynek": "Ры́нэк",
    "Stare Miasto": "Ста́рэ Мя́сто",
    "Старе Място": "Ста́рэ Мя́сто",
    "Chopin": "Шопе́н",
    "Шопен": "Шопе́н",
    "Kopernik": "Копе́рник",
    "Коперник": "Копе́рник",
    "Вигилия": "Виги́лия",
    "Wigilia": "Виги́лия",
    "Andrzejki": "Анджэ́йки",
    "Анджейки": "Анджэ́йки",
    "Tłusty Czwartek": "Тлу́сты Чва́ртэк",
    "Тлусты Чвартек": "Тлу́сты Чва́ртэк",
    "Kopiec Kościuszki": "Ко́пец Кощу́шки",
    "Костюшко": "Кощу́шко",
    # Природа
    "Tatry": "Та́тры",
    "Морское Око": "Мо́рскэ О́ко",
    "Morskie Oko": "Мо́рскэ О́ко",
    "Bieszczady": "Бещя́ды",
    "Бещады": "Бещя́ды",
    # Транспорт / магазины
    "PKP": "Пэ Ка Пэ",
    "Flixbus": "Фли́ксбус",
    "Biedronka": "Бедро́нка",
    "Żabka": "Жа́бка",
    "Allegro": "Алле́гро",
    # Валюта
    "złoty": "зло́тый",
    "złotych": "зло́тых",
    "zł": "злотых",
}

# Стили подачи — яркие, увлекательные форматы
ANGLES = [
    "топ мест, которые обязательно стоит посетить",
    "место, которое обязательно нужно увидеть своими глазами",
    "топ необычных мест, о которых не пишут путеводители",
    "традиция, которая удивляет иностранцев",
    "блюдо, которое нужно попробовать каждому",
    "факт о Польше, который мало кто знает",
    "мифы про Польшу, которые пора развеять",
    "история, от которой мурашки по коже",
    "5 вещей, которые обожают поляки",
    "рецепт, который передают из поколения в поколение",
    "место силы — куда ехать за вдохновением",
    "город, в который влюбляешься с первого взгляда",
    "сравнение: как это делают в Польше и в других странах",
    "сезонное — что происходит в Польше прямо сейчас",
    "легенда, которую рассказывают в каждом польском городе",
    "топ польских десертов, от которых невозможно оторваться",
    "природное чудо Польши, о котором мало кто слышал",
]

# Темы контента — места + культура + кухня + жизнь
TOPICS = [
    # Города и места
    "интересные места в Кракове",
    "Варшава — что посмотреть",
    "Вроцлав — секретные локации",
    "Гданьск и побережье Балтики",
    "горы Закопане и Татры",
    "Мальборк — крупнейший кирпичный замок в мире",
    "Величка — подземный соляной собор",
    "Беловежская пуща — последний первобытный лес Европы",
    "Торунь — город Коперника и пряников",
    "Мазурские озёра — польская жемчужина",
    "Казимеж Дольны — самый живописный городок Польши",
    "природа и национальные парки",
    "Познань — город козликов и рогалей",
    "Лодзь — польский Голливуд и уличное искусство",
    "Сопот — самый длинный деревянный мол в Европе",
    # Культура и традиции
    "польские праздники и традиции: Вигилия, Анджейки, Тлусты Чвартек",
    "польский этикет — что удивляет иностранцев",
    "история Польши — ключевые моменты за 5 минут",
    "интеграция и культурные различия",
    "сезонные фестивали и события",
    "польское искусство и музеи",
    "польская музыка — от Шопена до современности",
    "польский юмор и менталитет",
    "польские суеверия и приметы",
    # Кухня и еда
    "польская кухня — пероги, журек, бигос и другие хиты",
    "уличная еда в Польше — запеканка, обважанек, оськ пшонек",
    "польские десерты — сэрник, шарлотка, пончки",
    "где вкусно и недорого поесть в Польше",
    "польское пиво и пивные фестивали",
    "рынки и базары — где покупать свежие продукты",
    "шоппинг и скидки",
    "польский кофе — культура кавярен",
    # Повседневная жизнь
    "транспорт и PKP — как ездить дёшево",
    "польский язык — смешные слова и ложные друзья переводчика",
    "что удивляет в польском быте после переезда",
]

# Города для рандомизации
CITIES = [
    "Варшава", "Краков", "Вроцлав", "Гданьск", "Познань",
    "Лодзь", "Катовице", "Люблин", "Закопане", "Торунь",
    "Щецин", "Белосток", "Ольштын", "Сопот", "Казимеж Дольны",
]

# Запросы для Pexels — расширенный набор
PEXELS_QUERIES = [
    "Poland city",
    "Krakow old town",
    "Polish food pierogi",
    "Poland castle",
    "Poland nature forest",
    "Warsaw skyline",
    "European street cafe",
    "mountain landscape Poland",
    "Baltic sea beach",
    "European architecture",
    "travel Europe",
    "city life Europe",
    "Polish market food",
    "autumn Europe forest",
    "medieval castle Europe",
    "church interior Europe",
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
    "shorts", "польша", "явпольше", "путешествия", "интересно",
    "европа", "факты", "кухня", "культура",
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

    # Минимум 30% фраз с конкретикой (цифры, места, еда, действия, культура)
    concrete_markers = re.compile(
        r'\d|злот|евро|рубл|месяц|недел|год|день|час|'
        r'адрес|документ|паспорт|виз|карт[аеу]|заявлен|'
        r'регистрац|прописк|страхов|пособ|налог|'
        r'зайди|оформи|подай|получи|открой|зарегистрируй|найди|позвони|напиши|проверь|попробуй|закажи|посети|'
        r'бесплатн|скидк|стоит|цена|зарплат|аренд|'
        r'варшав|краков|вроцлав|гданьск|познань|польш|лодзь|катовиц|люблин|закопан|торунь|сопот|щецин|мальборк|величк|'
        r'песель|нфз|зус|мельдунэк|побыту|уженд|гмин|'
        r'перог|журек|бигос|запеканк|обважан|сэрник|шарлотк|пончк|'
        r'замок|костёл|рынок|музей|парк|озер|гор[аыу]|мор[еяю]|пляж|лес|'
        r'фестивал|традиц|праздник|рождеств|пасх|вигили|'
        r'шопен|коперник|ваенд[аы]|вавел',
        re.IGNORECASE,
    )
    concrete_count = sum(1 for p in parts if concrete_markers.search(p.text))
    ratio = concrete_count / len(parts)
    if ratio < 0.30:
        print(f"[QUALITY] Rejected: not enough concrete content ({ratio:.0%}, need >=30%)")
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
    # [0] — Польская кухня
    [
        ScriptPart("Знаешь, какое блюдо в Польше готовят уже больше пятисот лет? Это перо́ги — польские вареники."),
        ScriptPart("Их лепят с творогом, картошкой, мясом, капустой и даже с черникой — на десерт."),
        ScriptPart("А вот зимой тут все едят жу́рек — кислый суп на ржаной закваске с колбасой и яйцом."),
        ScriptPart("Подают его в хлебной миске, которую можно съесть вместе с супом. Выглядит невероятно."),
        ScriptPart("Кстати, в Кракове обязательно попробуй обважа́нек — солёный бублик с маком, который продают на каждом углу."),
        ScriptPart("Стоит всего два-три злотых, а по вкусу напоминает горячий хрустящий крендель."),
        ScriptPart("На десерт бери сэ́рник — польский чизкейк из творога. В кондитерских порция от восьми злотых."),
        ScriptPart("А в феврале вся Польша сходит с ума по по́нчкам — в Тлусты Чвартек очередь за ними на час."),
        ScriptPart("Напиши в комментариях, какое польское блюдо ты уже пробовал. Подпишись и сохрани!"),
    ],
    # [1] — Краков — места, которых нет в путеводителях
    [
        ScriptPart("Краков — один из красивейших городов Европы. Но самые интересные места тут прячутся от туристов."),
        ScriptPart("Начни с Казимежа — бывшего еврейского квартала. Здесь узкие улочки, граффити и десятки уютных кафе."),
        ScriptPart("Кстати, именно тут снимали Список Шиндлера — а бывшая фабрика Шиндлера теперь музей."),
        ScriptPart("Дальше поднимись на Копец Кощу́шко — насыпной холм с панорамой на весь город и Та́тры вдалеке."),
        ScriptPart("А вот тут интересно: под рыночной площадью есть подземный музей — средневековый Краков под землёй."),
        ScriptPart("Билет стоит около двадцати пяти злотых, но в понедельник бывает бесплатный вход."),
        ScriptPart("Вечером загляни в Забло́це — бывший промышленный район, который стал модным арт-кварталом."),
        ScriptPart("Здесь галереи, крафтовые бары и уличная еда — жизнь кипит до позднего вечера."),
        ScriptPart("Если был в Кра́кове — напиши, что понравилось больше всего. Сохрани и подпишись!"),
    ],
    # [2] — Удивительные факты о Польше
    [
        ScriptPart("Знаешь, что в Польше находится самый большой кирпичный замок в мире? Это Ма́льборк."),
        ScriptPart("Его построили тевтонские рыцари в тринадцатом веке — и он до сих пор стоит целёхонький."),
        ScriptPart("А в городе Вели́чка есть соляная шахта, которой больше семисот лет."),
        ScriptPart("Под землёй — целый собор, вырезанный из соли. Люстры, алтарь, статуи — всё из чистой соли."),
        ScriptPart("Кстати, Польша — родина Копе́рника, того самого, который доказал, что Земля вращается вокруг Солнца."),
        ScriptPart("А Шопе́н, один из величайших композиторов мира, родился под Варшавой."),
        ScriptPart("В То́руне до сих пор пекут пряники по рецептам четырнадцатого века."),
        ScriptPart("Покупаешь в фирменной лавке тёплый пряник с начинкой — и понимаешь, зачем сюда ехать."),
        ScriptPart("И ещё: в Белове́жской пуще живут зубры — последние дикие зубры Европы."),
        ScriptPart("Напиши, какой факт удивил больше всего. Подпишись, чтобы узнать ещё больше о Польше!"),
    ],
    # [3] — Гданьск и побережье Балтики
    [
        ScriptPart("Гда́ньск — город, в котором смешались янтарь, море и тысячелетняя история."),
        ScriptPart("Его старый город был разрушен во Вторую мировую, а потом восстановлен по кирпичику."),
        ScriptPart("Прогуляйся по улице Длу́гой — здесь разноцветные фасады, уличные музыканты и запах вафель."),
        ScriptPart("Кстати, именно тут добывают балтийский янтарь. В лавках на Ма́рьяцкой можно купить украшения от мастеров."),
        ScriptPart("Дальше садись на электричку до Со́пота — это пятнадцать минут до самого длинного деревянного мо́ла в Европе."),
        ScriptPart("По нему можно гулять прямо над морем — четыреста пятьдесят метров чистого кайфа."),
        ScriptPart("А если приехать летом, на пляже Е́лита́ во — белый песок и бирюзовая вода, почти как на юге."),
        ScriptPart("Вечером вернись в Гда́ньск и поужинай в порту. Свежая рыба, холодное пиво и закат над Мотлавой."),
        ScriptPart("Был на Балтике? Напиши, что понравилось! Сохрани видео и подпишись на канал."),
    ],
]

_FALLBACK_META_POOL = [
    VideoMetadata(
        title="Польская кухня — 5 блюд, от которых невозможно оторваться 🥟 #shorts",
        description="Перо́ги, жу́рек, обважа́нек — попробуй и влюбишься!\n\n#польша #кухня #еда #пероги #явпольше #shorts",
        tags=["польша", "кухня", "еда", "пероги", "журек", "явпольше", "shorts", "путешествия"],
    ),
    VideoMetadata(
        title="Краков — места, которых нет в путеводителях 🏰 #shorts",
        description="Казимеж, Копец Кощу́шко, подземный музей — скрытые жемчужины Кра́кова.\n\n#краков #польша #путешествия #явпольше #shorts",
        tags=["краков", "польша", "путешествия", "туризм", "европа", "явпольше", "shorts", "места"],
    ),
    VideoMetadata(
        title="7 фактов о Польше, которые удивляют всех 🇵🇱 #shorts",
        description="Самый большой замок, соляной собор, зубры — Польша полна сюрпризов!\n\n#польша #факты #интересно #явпольше #shorts",
        tags=["польша", "факты", "интересно", "замок", "мальборк", "явпольше", "shorts", "европа"],
    ),
    VideoMetadata(
        title="Гданьск и Балтика — янтарь, море и вафли 🌊 #shorts",
        description="Гда́ньск, Со́пот, янтарь, самый длинный мол — Балтика не хуже юга!\n\n#гданьск #сопот #балтика #польша #явпольше #shorts",
        tags=["гданьск", "сопот", "балтика", "море", "янтарь", "польша", "явпольше", "shorts"],
    ),
]


def _fallback_script() -> tuple:
    idx = random.randrange(len(_FALLBACK_POOL))
    print(f"[FALLBACK] Using fallback script #{idx}")
    return _FALLBACK_POOL[idx], _enrich_metadata(_FALLBACK_META_POOL[idx])


def _load_topic_history() -> List[str]:
    """Загружает историю последних использованных тем."""
    if HISTORY_PATH.is_file():
        try:
            return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_topic_history(history: List[str]) -> None:
    """Сохраняет историю тем (последние MAX_HISTORY)."""
    HISTORY_PATH.write_text(
        json.dumps(history[-MAX_HISTORY:], ensure_ascii=False),
        encoding="utf-8",
    )


def _pick_unique_topic() -> tuple:
    """Выбирает тему и стиль, избегая повторов с последними N видео."""
    history = _load_topic_history()
    available = [t for t in TOPICS if t not in history]
    if not available:
        available = TOPICS  # все использованы — сбрасываем
    topic = random.choice(available)
    history.append(topic)
    _save_topic_history(history)
    return topic


def call_groq_for_script() -> tuple:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("[WARN] GROQ_API_KEY not set")
        return _fallback_script()

    angle = random.choice(ANGLES)
    topic = _pick_unique_topic()
    city = random.choice(CITIES)
    current_year = datetime.now().year

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    system_prompt = (
        "Ты — русскоязычный блогер, живущий в Польше уже 5 лет. Канал 'Я в Польше'. "
        "Канал об интересных местах, кухне, культуре, традициях, истории "
        "и удивительных фактах о Польше. Ты рассказываешь ярко, образно и увлекательно — "
        "так, чтобы зритель захотел посетить это место или попробовать это блюдо.\n\n"
        "ГЛАВНОЕ ПРАВИЛО: каждая следующая фраза ЛОГИЧЕСКИ продолжает предыдущую. "
        "Сценарий = связный рассказ, а НЕ набор случайных фактов. "
        "Фразы идут как шаги одного путешествия: зацепка → погружение → детали → кульминация → вывод.\n\n"
        "СВЯЗНОСТЬ: используй переходные слова между фразами: "
        "'а вот тут интересно', 'кстати', 'и ещё', 'но самое крутое', "
        "'дальше', 'а рядом', 'но главное', 'именно поэтому', 'например'.\n\n"
        "СТИЛЬ: как будто ведёшь друга по городу или рассказываешь про блюдо за столом. "
        "Описывай запахи, вкусы, виды, эмоции. Не сухие факты, а живой рассказ.\n\n"
        "КОНКРЕТИКА: конкретные названия мест, блюд, улиц, дат, имён. "
        "Называй реальные рестораны, музеи, районы. Упоминай цены в злотых, века, расстояния. "
        "ЗАПРЕЩЕНЫ пустые фразы: 'Это невероятно', 'Ты не поверишь', 'Это удивительно'.\n\n"
        "ПРОИЗНОШЕНИЕ: ВСЕ польские слова пиши КИРИЛЛИЦЕЙ так, как они звучат: "
        "Kraków → Кра́ков, pierogi → перо́ги, żurek → жу́рек, bigos → би́гос, "
        "obwarzanek → обважа́нэк, Wieliczka → Вели́чка, Kazimierz → Кази́меж, "
        "Wawel → Ва́вэль, Rynek → Ры́нэк, Sukiennice → Суке́нницэ, "
        "Sopot → Со́пот, Malbork → Ма́льборк, oscypek → осци́пек, "
        "gołąbki → голо́мпки, szarlotka → шарло́тка, sernik → сэ́рник, "
        "Chopin → Шопе́н, Kopernik → Копе́рник, "
        "Tłusty Czwartek → Тлу́сты Чва́ртэк, Wigilia → Виги́лия, "
        "złotych → злотых, mleczny bar → мле́чны бар.\n\n"
        "Отвечай ТОЛЬКО валидным JSON без markdown-обёрток."
    )

    user_prompt = f"""Напиши сценарий YouTube Shorts (45–60 секунд) для канала «Я в Польше».

КОНТЕКСТ:
- Тема: {topic}
- Город: {city}
- Стиль: {angle}
- Год: {current_year} (используй самую актуальную информацию)

СТРУКТУРА СЦЕНАРИЯ (обязательно следуй этому плану):
1. ХУК (1 фраза) — интригующий факт, вопрос или удивительная деталь. Цепляет с первой секунды.
2. КОНТЕКСТ (1–2 фразы) — почему это интересно, кого касается.
3. ОСНОВНАЯ ЧАСТЬ (5–8 фраз) — раскрытие темы шаг за шагом. Каждая фраза содержит конкретику: название места, блюда, документа, цену, факт, дату, имя. Фразы СВЯЗАНЫ логически — каждая продолжает предыдущую.
4. ВЫВОД (1 фраза) — итог: что зритель должен запомнить или попробовать.
5. CTA (1 фраза) — призыв сохранить, подписаться, написать в комментариях.

ТРЕБОВАНИЯ:
- 10–14 фраз всего.
- Каждая фраза = 1–2 предложения, 10–25 слов.
- Обращение на «ты», как друг рассказывает другу.
- Язык — живой разговорный русский. Польские термины — КИРИЛЛИЦЕЙ.
- Используй самую актуальную информацию на момент {current_year} года.
- Между фразами обязательны логические связки (после этого, следующий шаг, а вот тут, кстати, поэтому).
- Если тема про место или еду — описывай ярко и вкусно, чтобы хотелось поехать/попробовать.
- Если тема практическая — давай конкретные суммы, сроки, адреса.

ПЛОХО (набор несвязных фраз):
"В Польше вкусная еда." / "ПЕСЕЛЬ нужен для банка." / "Краков красивый город." — ЭТО ЗАПРЕЩЕНО.

ХОРОШО — практическая тема (связный рассказ):
"Приехал в Краков и первым делом пошёл в уженд гмины за ПЕСЕЛем." / "Без него не откроешь счёт в банке." / "Поэтому следующий шаг — идёшь в мБанк с ПЕСЕЛем и паспортом."

ХОРОШО — культурная тема (связный рассказ):
"В Кракове есть место, где пероги готовят по рецепту 1842 года." / "Называется Пероговня на Казимеже — очередь всегда на полчаса." / "Но оно того стоит: рушки с творогом тут подают с топлёным маслом и шкварками."

Формат — строго JSON:
{{
  "title": "Цепляющий заголовок, до 80 символов, с эмодзи 🇵🇱 и #shorts в конце",
  "description": "Описание 3–5 строк с хештегами:\\n- первая строка — о чём видео\\n- вторая — ключевой факт или совет\\n- третья — хештеги (#польша #явпольше #shorts ...)",
  "tags": ["польша", "явпольше", "shorts", ...ещё 10–15 тематических тегов],
  "pexels_queries": ["3–5 коротких англ. запросов для поиска видео на Pexels"],
  "parts": [
    {{ "text": "Связная фраза с конкретикой, 10-25 слов" }}
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
            "2. Есть конкретика: названия мест, блюд, цены, даты, факты.\n"
            "3. Минимум 10 фраз, каждая 10-25 слов.\n"
            f"4. Информация актуальна на {current_year} год.\n"
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
