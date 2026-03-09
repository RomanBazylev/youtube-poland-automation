# YouTube «Я в Польше» Shorts Automation

Автоматический генератор YouTube Shorts для канала «Я в Польше» — советы по переезду, легализации, интересным местам и жизни в Польше. Запускается на GitHub Actions каждые 4 часа.

## Что делает

1. **Генерирует сценарий** через Groq LLM — реальные советы с суммами в злотых, названиями документов, пошаговыми инструкциями
2. **Скачивает стоковые видео** с Pexels + Pixabay (города Польши, архитектура, природа)
3. **Озвучивает** через edge-tts (ru-RU-DmitryNeural) с пофразовой синхронизацией
4. **Собирает видео 9:16** — Ken Burns zoom, жирные субтитры, фоновая музыка
5. **Загружает на YouTube** через OAuth2 Data API v3
6. **Контроль качества** — валидирует сценарий (отбрасывает слабый контент)

## Темы контента

27 тем × 12 стилей подачи × 10 городов = **3240 уникальных комбинаций**

**Темы**: легализация, PESEL, NFZ, аренда, работа, бизнес, налоги, пособия, образование, транспорт, банки, достопримечательности (Краков, Варшава, Вроцлав, Гданьск, Закопане...), кухня, шоппинг, права иностранцев, Карта Поляка и др.

**Стили**: топ мест, лайфхаки, ошибки, сравнения, инструкции, стоимость жизни, изменения в законах, экономия, реальные истории, мифы.

## Особенности

- Польские термины транслитерируются в кириллицу прямо в промпте (PESEL → ПЕСЕЛЬ, Urząd → уженд)
- 37 произносительных фиксов для TTS (ZUS, NFZ, города, валюта, магазины)
- Категория YouTube: Travel & Events (19)
- Quality gate: мин. 8 частей, ≥7 слов/фразу, детектор фразо-наполнителей, ≥40% конкретики

## Настройка

### 1. Создай GitHub репо и запуши код

### 2. Добавь Secrets

**Settings → Secrets and variables → Actions:**

| Secret | Обязательно | Описание |
|--------|------------|----------|
| `GROQ_API_KEY` | Да | [console.groq.com](https://console.groq.com) |
| `PEXELS_API_KEY` | Да | [pexels.com/api](https://www.pexels.com/api/) |
| `PIXABAY_API_KEY` | Нет | [pixabay.com/api](https://pixabay.com/api/docs/) |
| `YOUTUBE_CLIENT_ID` | Для загрузки | Google Cloud OAuth2 |
| `YOUTUBE_CLIENT_SECRET` | Для загрузки | Google Cloud OAuth2 |
| `YOUTUBE_REFRESH_TOKEN` | Для загрузки | От аккаунта канала «Я в Польше» |
| `YOUTUBE_PRIVACY` | Нет | `public` / `unlisted` / `private` |

### 3. YouTube OAuth2

1. Google Cloud Console → YouTube Data API v3 → Enable
2. OAuth 2.0 Client ID (Web application) + redirect URI: `https://developers.google.com/oauthplayground`
3. OAuth Playground → своя credentials → scope `youtube.upload` → войти аккаунтом канала → получить refresh_token
4. Добавить в Secrets

### 4. Запуск

- **Авто**: каждые 4 часа
- **Вручную**: Actions → "Generate Poland Short" → Run workflow
