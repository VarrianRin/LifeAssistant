import os
import logging
import asyncio
from dotenv import load_dotenv
from pathlib import Path
from aiogram import Router, types, F
from aiogram.filters import Command
from yt_dlp import YoutubeDL
from bot.csv_db import save_track

logger = logging.getLogger(__name__)
router = Router()
load_dotenv() 
# Configure paths
DATA_DIR = os.getenv("DATA_DIR", "data")
TRACKS_DIR = os.path.join(DATA_DIR, "tracks")

def _build_ydl_opts(final_path: str) -> dict:
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": final_path,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": ["web"]}},
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }

    # .env →  COOKIES_BROWSER=chrome   или  chrome:nocopy
    raw = (os.getenv("COOKIES_BROWSER") or "").lower().strip()
    if raw:
        if ":" in raw:          # пример  chrome:nocopy
            browser, flag = raw.split(":", 1)
            if flag == "nocopy":
                # (browser, profile=None, nocopy)
                ydl_opts["cookiesfrombrowser"] = (browser, None, "nocopy")
            else:
                # (browser, profile)
                ydl_opts["cookiesfrombrowser"] = (browser, flag)
        else:
            # просто  chrome
            ydl_opts["cookiesfrombrowser"] = (raw,)

    return ydl_opts



def ensure_user_track_dir(user_id: int) -> str:
    """Ensure user's track directory exists and return its path."""
    user_dir = os.path.join(TRACKS_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

MAX_DURATION_SEC = 2 * 60 * 60        # 2 часа

def _meta_opts() -> dict:
    """Опции только для извлечения info, но с теми же cookies."""
    opts = _build_ydl_opts("%(title)s.%(ext)s")  # шаблон не важен
    opts["skip_download"] = True
    return opts


def download_youtube_audio(url: str, output_dir: str) -> tuple[bool, str]:
    try:
        # 1) ── получаем метаданные с cookies ───────────────────────
        with YoutubeDL(_meta_opts()) as ydl:
            info = ydl.extract_info(url, download=False)

        duration = info.get("duration") or 0
        if duration > MAX_DURATION_SEC:
            return False, f"Track is too long ({duration//60} min > {MAX_DURATION_SEC//60} min)."

        # 2) ── формируем имя файла ────────────────────────────────
        safe = "".join(c for c in info["title"][:50] if c.isalnum() or c in " _-").strip()
        final = Path(output_dir, f"{safe}.mp3").as_posix()

        # 3) ── реальное скачивание ────────────────────────────────
        with YoutubeDL(_build_ydl_opts(final)) as ydl:
            ydl.download([url])

        return True, final

    except Exception as e:
        msg = str(e)
        if "Sign in to confirm" in msg:
            return False, "⚠️ YouTube still asks to sign-in. Close browser OR export cookies.txt."
        return False, f"Download failed: {msg}"


@router.message(Command("add_music"))
async def cmd_add_music(message: types.Message):
    """Handle /add_music command to download YouTube audio."""
    try:
        # Get URL from command
        args = message.text.split()
        if len(args) != 2:
            await message.answer(
                "❌ Invalid format. Please use:\n"
                "/add_music [youtube_link]"
            )
            return
        
        url = args[1]
        user_id = message.from_user.id
        
        # Create user's track directory
        user_dir = ensure_user_track_dir(user_id)
        
        

        # Send initial message
        status_msg = await message.answer("⏳ Downloading audio... This may take a while.")
        
        # Download audio
        success, result = await asyncio.to_thread(
            download_youtube_audio,
            url,
            user_dir
        )
        
        if success:
            # Save track info to database
            if save_track(user_id, "pomodoro", url, result):
                await status_msg.edit_text(
                    "✅ Audio downloaded successfully!\n"
                    f"Saved as: {os.path.basename(result)}\n"
                    "You can use this track during pomodoro sessions."
                )
            else:
                await status_msg.edit_text(
                    "✅ Audio downloaded but failed to save track info.\n"
                    f"File saved as: {os.path.basename(result)}"
                )
        else:
            await status_msg.edit_text(f"❌ {result}")
            
    except Exception as e:
        logger.error(f"Error in add_music command: {e}")
        await message.answer("❌ Something went wrong. Please try again later.") 