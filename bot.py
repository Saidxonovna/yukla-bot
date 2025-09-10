import logging
import os
import asyncio
import re
import time
import httpx
from yt_dlp import YoutubeDL

from telethon import TelegramClient, events, Button
from telethon.errors import MessageNotModifiedError

# Log yozishni sozlash
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)

# --- Railway'ning "Variables" bo'limidan olinadigan ma'lumotlar ---
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
except (ValueError, TypeError):
    logging.critical("API_ID, API_HASH yoki BOT_TOKEN topilmadi!")
    exit(1)

# Telethon klientini yaratish
client = TelegramClient('bot_session', API_ID, API_HASH)

# --- ZAXIRA REJASI UCHUN IKKITA COBALT API MANZILI ---
COBALT_APIS = [
    "https://api.cobalt.tools/api/json",
    "https://co.wuk.sh/api/json"
]


# --- YORDAMCHI FUNKSIYALAR ---
def clean_url(url):
    """Havolani standart formatga keltiradi."""
    yt_match = re.search(r'(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
    if yt_match: return f'https://www.youtube.com/watch?v={yt_match.group(1)}'
    insta_match = re.search(r'(?:instagram\.com/(?:p|reel)/)([a-zA-Z0-9_-]+)', url)
    if insta_match: return f'https://www.instagram.com/p/{insta_match.group(1)}/'
    tiktok_match = re.search(r'(tiktok\.com/.*/video/\d+)', url)
    if tiktok_match: return f'https://{tiktok_match.group(1)}'
    return url

async def safe_edit_message(message, text, **kwargs):
    """Xabarni xavfsiz tahrirlaydi."""
    if not message or getattr(message, 'text', None) == text: return
    try: await message.edit(text, **kwargs)
    except MessageNotModifiedError: pass
    except Exception as e: logging.warning(f"Xabarni tahrirlashda xatolik: {e}")


# --- "C REJA": TO'G'RIDAN-TO'G'RI YUKLASH FUNKSIYASI ---
async def fallback_yt_dlp_download(event, url, processing_message, info_dict):
    """Agar Cobalt ishlamasa, yt-dlp orqali to'g'ridan-to'g'ri yuklaydi."""
    await safe_edit_message(processing_message, "⚠️ Asosiy servis ishlamadi. Zaxira usuliga o'tilmoqda...")
    file_path = None
    try:
        last_update = 0
        def progress_hook(d):
            nonlocal last_update
            if d['status'] == 'downloading':
                current_time = time.time()
                if current_time - last_update > 3:
                    percentage = d['_percent_str']
                    speed = d['_speed_str']
                    progress_text = f"📥 **Serverga yuklanmoqda (Zaxira)...**\n`{percentage} | {speed}`"
                    asyncio.run_coroutine_threadsafe(
                        safe_edit_message(processing_message, progress_text),
                        asyncio.get_event_loop()
                    )
                    last_update = current_time

        ydl_opts = {
            'format': 'best[ext=mp4][height<=720]/bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': '%(title)s.%(ext)s', 'noplaylist': True,
            'progress_hooks': [progress_hook],
            'socket_timeout': 30, 'max_filesize': 1024 * 1024 * 1024
        }
        with YoutubeDL(ydl_opts) as ydl:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: ydl.download([url]))
            file_path = ydl.prepare_filename(info_dict)

        if not file_path or not os.path.exists(file_path):
            await safe_edit_message(processing_message, "❌ Zaxira usulida ham yuklab bo'lmadi.")
            return

        await safe_edit_message(processing_message, "✅ Zaxira usulida yuklandi! Yuborilmoqda...")
        await client.send_file(
            event.chat_id, file_path, caption=f"**{info_dict.get('title', 'Video')}**\n\n@Allsavervide0bot orqali yuklandi (Zaxira usuli)"
        )
        await processing_message.delete()

    except Exception as e:
        logging.error(f"Zaxira usulida xatolik: {e}")
        await safe_edit_message(processing_message, f"❌ Zaxira usulida ham xatolik: `{e}`")
    finally:
        if file_path and os.path.exists(file_path): os.remove(file_path)


# --- ASOSIY YUKLASH FUNKSIYASI (GIBRID USUL) ---
async def hybrid_download(event, url):
    processing_message = await event.reply("⏳ Havola qayta ishlanmoqda...")
    info_dict = None
    try:
        await safe_edit_message(processing_message, "ℹ️ Video ma'lumotlari olinmoqda...")
        with YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True}) as ydl:
            info_dict = ydl.extract_info(url, download=False)
    except Exception as e:
        logging.warning(f"yt-dlp orqali ma'lumot olib bo'lmadi: {e}")

    data = None
    last_error = "Barcha yuklash servislari javob bermadi."

    for api_url in COBALT_APIS:
        try:
            await safe_edit_message(processing_message, f"🌎 Yuklash servisidan video so'ralmoqda ({COBALT_APIS.index(api_url) + 1}-urinish)...")
            payload = {"url": url, "vQuality": "720"}
            async with httpx.AsyncClient(timeout=90) as client_http:
                response = await client_http.post(api_url, json=payload, headers={"Accept": "application/json"})
                response.raise_for_status()
                data = response.json()
            if data and data.get("status") == "stream": break
            else: last_error = data.get('text', 'Noma\'lum xato.')
        except Exception as e:
            logging.warning(f"{api_url} ishlamadi: {e}")
            last_error = f"Servisga ulanishda muammo: {e.__class__.__name__}"
    
    if data and data.get("status") == "stream":
        await safe_edit_message(processing_message, "✅ Video topildi, Telegram'ga yuborilmoqda...")
        video_title = info_dict.get('title', 'Yuklab olingan video') if info_dict else "Video"
        await client.send_file(
            event.chat_id, file=data["url"], caption=f"**{video_title}**\n\n@Allsavervide0bot orqali yuklandi"
        )
        await processing_message.delete()
    else:
        # --- AGAR COBALT ISHLAMASA, "C REJA"NI ISHGA TUSHIRISH ---
        if 'youtube.com' in url or 'youtu.be' in url:
            logging.info(f"Cobalt ishlamadi. YouTube uchun zaxira usuliga o'tilmoqda.")
            if info_dict:
                await fallback_yt_dlp_download(event, url, processing_message, info_dict)
            else:
                await safe_edit_message(processing_message, "❌ Xatolik: Video ma'lumotlarini olib bo'lmadi.")
        else:
            await safe_edit_message(processing_message, f"❌ Xatolik: {last_error}")


# --- ASOSIY HANDLERLAR ---
@client.on(events.NewMessage(pattern=re.compile(r'https?://\S+')))
async def main_handler(event):
    url_match = re.search(r'https?://\S+', event.text)
    if not url_match: return
    
    cleaned_url = clean_url(url_match.group(0))
    await hybrid_download(event, cleaned_url)

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply("Assalomu alaykum! Video havolasini yuboring.")

# --- ASOSIY ISHGA TUSHIRISH FUNKSIYASI ---
async def main():
    await client.start(bot_token=BOT_TOKEN)
    logging.info("Bot 'C Reja' bilan muvaffaqiyatli ishga tushdi...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())