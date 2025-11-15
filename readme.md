# 🎧 Music Jacker — YouTube & SoundCloud Downloader

Lightweight Flask web app to grab audio/video from YouTube, YouTube Music, SoundCloud and other supported sources. The UI is Tailwind-based, animated, responsive, multilingual, and ships with quick links to news and the Telegram bot.

## ✨ Features
- 🚀 Single links or playlists; MP3/M4A/Opus/MP4 via `yt-dlp` + `ffmpeg`.
- 🌐 Built-in translations (EN, RU, ES, AZ, TR), switchable in the UI.
- 🌓 Modern UI with animated backgrounds, modal overlays, and fixed navigation.
- 🧩 Rich metadata: thumbnails, artist/title inference, and tagged downloads (when `ffmpeg` + `mutagen` available).
- 💡 Configurable via env vars (`LOG_LEVEL`, `FFMPEG_PATH`, etc.) and optional YouTube cookies for restricted content.

## 🧱 Tech Stack
| Layer    | Tech                                     |
|----------|------------------------------------------|
| Backend  | Flask, `yt-dlp`, `ffmpeg`, Python 3      |
| Frontend | Tailwind CSS, custom CSS/JS              |
| Other    | Dockerfile included, dotenv support      |

## 📢 Updates & Community
- Blog with release notes and news about the site and Telegram bot: https://thebitsamuraii23.github.io/miniblog
- Telegram channel: https://t.me/ytdlpdeveloper  
- Telegram bot: https://t.me/ytdlpload_bot

## ⚙️ Quick Start
```bash
git clone https://github.com/thebitsamuraii23/MusicJacker-Site
cd ytmusicdownloadersite
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp youtube.com_cookies.txt.example youtube.com_cookies.txt  # needed only for private/age-restricted content
python app.py
```
The app will run at `http://127.0.0.1:5000/`.

### Environment knobs
- `LOG_LEVEL` (default `INFO`)
- `FFMPEG_PATH` (path to ffmpeg, if not in system PATH)
- `DEFAULT_ARTIST_NAME`, `DEFAULT_ALBUM_NAME`
- `PLAYLIST_DURATION_CHECK_LIMIT`, `DURATION_LIMIT_SECONDS` (10-minute cap by default)

## 🌐 API
- `GET /` — render the main page.
- `POST /api/download_audio` — body `{ "url": "...", "format": "mp3|m4a|opus|mp4" }`; validates duration, downloads/converts, returns file metadata + download URLs.

## 📁 Project Structure
```
app.py                  # Flask app and API
templates/index.html    # Main template
templates/musicjacker-standalone.html # Static standalone variant
static/css/main.css     # Styles
static/js/main.js       # Frontend logic + i18n loader
static/i18n/*.json      # Locale files
user_downloads/         # Per-session temp files
youtube.com_cookies.txt # Optional cookies for yt-dlp
```

## 🛠 Development Notes
- Run `python app.py` for local dev; adjust env vars as needed.
- Add new locales by dropping `<lang>.json` into `static/i18n/` (keys match existing bundles).
- For production, consider Docker + a reverse proxy (Nginx) and persistent storage for logs.

## ⚠️ Disclaimer
This tool is for educational/demo purposes. Ensure you have the rights to download and use any content; respect copyright and platform terms.

---
Created with ❤️ by thebitsamurai. Feel free to fork, improve, and share! 🎶
