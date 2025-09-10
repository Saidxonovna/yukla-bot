import logging
import os
import time
import asyncio
import re
from yt_dlp import YoutubeDL, utils as yt_dlp_utils

from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeVideo
from telethon.errors import MessageNotModifiedError

# Log yozishni sozlash (xatoliklarni kuzatish uchun)
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)

# --- Railway'ning "Variables" bo'limidan olinadigan ma'lumotlar ---
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
except (ValueError, TypeError):
    logging.critical("API_ID, API_HASH yoki BOT_TOKEN topilmadi yoki noto'g'ri formatda!")
    exit(1)

# Fayl hajmi uchun cheklov
MAX_FILE_SIZE_LIMIT = 1 * 1024 * 1024 * 1024  # 1 Gigabayt

# Telethon klientini yaratish
client = TelegramClient('bot_session', API_ID, API_HASH)

# --- YUKLASH SOZLAMALARI UCHUN ASOSIY LUG'AT ---
BASE_YDL_OPTS = {
    'format': 'best[ext=mp4][height<=720]/best[ext=mp4]/best',
    'outtmpl': '%(title)s - [%(id)s].%(ext)s',
    'noplaylist': True,
    'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
    'postprocessor_args': ['-movflags', '+faststart'],
    'retries': 5,
    'socket_timeout': 30,
    'nopart': True,
    'no_warnings': True,
}

# --- YORDAMCHI FUNKSIYA ---
async def safe_edit_message(message, text, **kwargs):
    """Xabarni xavfsiz tahrirlaydi."""
    if not message or not hasattr(message, 'text') or message.text == text:
        return
    try:
        await message.edit(text, **kwargs)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        logging.warning(f"Xabarni tahrirlashda kutilmagan xatolik: {e}")

# --- ASOSIY YUKLASH FUNKSIYASI ---
async def download_and_send_video(event, url):
    chat_id = event.chat_id
    processing_message = None
    file_path = None
    
    try:
        if isinstance(event, events.CallbackQuery.Event):
            processing_message = await event.edit("⏳ Havola tekshirilmoqda..")
        else:
            processing_message = await event.reply("⏳ Havola tekshirilmoqda..")
    except Exception as e:
        logging.error(f"Boshlang'ich xabarni yuborishda xatolik: {e}")
        return

    try:
        loop = asyncio.get_running_loop()
        last_update = 0

        def progress_hook(d):
            nonlocal last_update
            if d['status'] == 'downloading':
                current_time = time.time()
                if current_time - last_update > 3 and all(k in d for k in ('_percent_str', '_speed_str', '_eta_str')):
                    progress_text = f"📥 **Serverga yuklanmoqda...**\n`{d['_percent_str']} | {d['_speed_str']} | {d['_eta_str']}`"
                    asyncio.run_coroutine_threadsafe(safe_edit_message(processing_message, progress_text), loop)
                    last_update = current_time

        local_ydl_opts = BASE_YDL_OPTS.copy()
        local_ydl_opts['progress_hooks'] = [progress_hook]

        with YoutubeDL(local_ydl_opts) as ydl:
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            file_path = ydl.prepare_filename(info_dict)

        if not file_path or not os.path.exists(file_path):
            await safe_edit_message(processing_message, "❌ Kechirasiz, videoni yuklab bo'lmadi.")
            return

        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE_LIMIT:
            error_msg = f"❌ Video hajmi juda katta ({file_size / 1024 / 1024:.1f} MB).\nFaqat 1 GB gacha bo'lgan videolarni yuklash mumkin."
            await safe_edit_message(processing_message, error_msg)
            return

        async def upload_progress(current, total):
            await safe_edit_message(processing_message, f"✅ **Telegram'ga yuborilmoqda...**\n`{current * 100 / total:.1f}%`")
        
        duration = int(info_dict.get('duration', 0))
        width = int(info_dict.get('width', 0))
        height = int(info_dict.get('height', 0))
        video_title = info_dict.get('title', 'Nomsiz video')
        final_caption = f"**{video_title}**\n\n@Allsavervide0bot orqali yuklandi"

        await client.send_file(
            chat_id, file_path, caption=final_caption, progress_callback=upload_progress,
            attributes=[DocumentAttributeVideo(duration=duration, w=width, h=height, supports_streaming=True)]
        )
        
        # <<< MUHIM: Video tavsifini (opisaniyasini) olib, yuborish qismi ---
        description = info_dict.get('description')
        if description and description.strip():
            logging.info(f"Tavsif topildi. Uzunligi: {len(description)} belgi. Yuborilmoqda...")
            # Tavsif juda uzun bo'lsa, uni 4096 belgidan bo'lib yuborish
            for i in range(0, len(description), 4096):
                chunk = description[i:i+4096]
                await client.send_message(chat_id, f"**📝 Video tavsifi:**\n\n{chunk}")
        else:
            # Muammoni aniqlash uchun log yozamiz
            logging.info(f"Bu video uchun tavsif topilmadi yoki u bo'sh. URL: {url}")
        
        await processing_message.delete()

    except yt_dlp_utils.DownloadError as e:
        error_str = str(e).lower()
        if any(msg in error_str for msg in ["login", "sign in", "age-restricted", "private"]):
            error_message = "❌ **Himoyalangan video**\nBu video yosh cheklovi yoki maxfiylik sozlamalari tufayli yuklab olinmadi."
        else:
            error_message = f"❌ **Yuklashda xatolik**\n`{str(e)}`"
        await safe_edit_message(processing_message, error_message)
    except Exception as e:
        logging.error(f"Umumiy xatolik: {e}", exc_info=True)
        await safe_edit_message(processing_message, f"❌ Kechirasiz, kutilmagan xatolik yuz berdi.\n`{str(e)}`")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

# --- ASOSIY HANDLERLAR ---
@client.on(events.NewMessage(pattern=re.compile(r'https?://\S+')))
async def main_handler(event):
    url_match = re.search(r'https?://\S+', event.text)
    if not url_match: return
    url = url_match.group(0)

    if "list=" in url or "/playlist?" in url:
        playlist_msg = await event.reply("⏳ Playlist tahlil qilinmoqda...")
        try:
            ydl_opts = {'extract_flat': True, 'playlistend': 10}
            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=False)
            buttons = [
                [Button.inline(entry.get('title', 'Nomsiz video')[:60], data=f"dl_{entry.get('id')}")
                 ] for entry in info_dict.get('entries', []) if entry]
            if not buttons:
                await playlist_msg.edit("❌ Playlist'dan videolarni olib bo'lmadi.")
                return
            await playlist_msg.edit(f"**'{info_dict.get('title')}'** playlisti topildi.\nQuyidagilardan birini tanlang:", buttons=buttons)
        except Exception as e:
            await playlist_msg.edit(f"❌ Playlist'ni o'qishda xatolik: {e}")
    else:
        await download_and_send_video(event, url)

@client.on(events.CallbackQuery(pattern=b"dl_"))
async def button_handler(event):
    video_id = event.data.decode('utf-8').split('_', 1)[1]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    await download_and_send_video(event, video_url)

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply(
        "Assalomu alaykum! Men YouTube va Instagram'dan ommaviy videolar yuklab beraman.\n\n"
        "Shunchaki video havolasini yuboring."
    )

# --- ASOSIY ISHGA TUSHIRISH FUNKSIYASI ---
async def main():
    await client.start(bot_token=BOT_TOKEN)
    logging.info("Bot muvaffaqiyatli ishga tushdi...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
