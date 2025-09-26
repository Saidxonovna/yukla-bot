import os
import re
import asyncio
import logging
import uuid
import time
from functools import lru_cache

from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeFilename
from telethon.errors import MessageNotModifiedError
from yt_dlp import YoutubeDL

# --- Logger sozlamalari ---
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)
log = logging.getLogger(__name__)

# --- Serverning "Variables" bo'limidan olinadigan ma'lumotlar ---
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    YOUTUBE_COOKIE = os.environ.get("YOUTUBE_COOKIE")
    INSTAGRAM_COOKIE = os.environ.get("INSTAGRAM_COOKIE")
    NUM_WORKERS = int(os.environ.get("NUM_WORKERS", 3)) # Ishchilar soni
except (TypeError, ValueError):
    log.critical("Iltimos, API_ID, API_HASH va TELEGRAM_TOKEN o'zgaruvchilarini to'g'ri kiriting.")
    exit(1)


# --- Telethon klientini va global o'zgaruvchilarni yaratish ---
client = TelegramClient('bot_session', API_ID, API_HASH)
download_queue = asyncio.Queue()
temp_urls = {} # Callback uchun URLlarni vaqtinchalik saqlaydi
temp_descriptions = {} # Tavsiflarni (description) vaqtinchalik saqlaydi
playlist_info_cache = {} # Playlist ma'lumotlarini keshlash uchun
user_locks = {} # Foydalanuvchi so'rovlarini cheklash uchun

# Qo'llab-quvvatlanadigan URLlar uchun regex
YOUTUBE_RE = re.compile(r'https?://(?:www\.)?(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/|playlist\?list=)).*')
INSTAGRAM_RE = re.compile(r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[a-zA-Z0-9_-]+')

# --- YORDAMCHI FUNKSIYALAR ---

@lru_cache(maxsize=128)
def get_cookie_for_url(url):
    """Havolani tahlil qilib, mos cookie faylini yaratadi va uning nomini qaytaradi."""
    cookie_file_path = None
    cookie_data = None
    lower_url = url.lower()

    if 'youtube.com' in lower_url or 'youtu.be' in lower_url:
        cookie_data = YOUTUBE_COOKIE
        cookie_file_path = f'youtube_cookies_{uuid.uuid4()}.txt'
    elif 'instagram.com' in lower_url:
        cookie_data = INSTAGRAM_COOKIE
        cookie_file_path = f'instagram_cookies_{uuid.uuid4()}.txt'

    if cookie_data and cookie_file_path:
        with open(cookie_file_path, 'w', encoding='utf-8') as f:
            f.write(cookie_data)
        return cookie_file_path
    return None

async def safe_edit_message(message, text, **kwargs):
    """Xabarni xavfsiz tahrirlaydi, 'MessageNotModifiedError' xatosini e'tiborsiz qoldiradi."""
    if not message or message.text == text:
        return
    try:
        await message.edit(text, **kwargs)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        log.warning(f"Xabarni tahrirlashda kutilmagan xatolik: {e}")

async def download_and_send(event, url, ydl_opts):
    """Videoni yuklaydi, yuboradi va tavsif (description) uchun tugma taklif qiladi."""
    chat_id = event.chat_id
    processing_message = None
    cookie_file = None
    file_path = None
    loop = asyncio.get_running_loop()

    try:
        if isinstance(event, events.CallbackQuery.Event):
            processing_message = await event.edit("⏳ Yuklab olish boshlanmoqda...")
        else:
            processing_message = await event.reply("⏳ Yuklab olish boshlanmoqda...")

        cookie_file = get_cookie_for_url(url)
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file

        last_update = 0
        def progress_hook(d):
            nonlocal last_update
            if d['status'] == 'downloading':
                current_time = time.time()
                if current_time - last_update > 3:
                    percentage = d.get('_percent_str', '0.0%')
                    speed = d.get('_speed_str', '0 B/s')
                    eta = d.get('_eta_str', '00:00')
                    progress_text = f"📥 **Yuklanmoqda...**\n\n`{percentage} | {speed} | {eta}`"
                    asyncio.run_coroutine_threadsafe(safe_edit_message(processing_message, progress_text, parse_mode='markdown'), loop)
                    last_update = current_time

        ydl_opts['progress_hooks'] = [progress_hook]

        with YoutubeDL(ydl_opts) as ydl:
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            file_path = ydl.prepare_filename(info_dict)

            if not file_path or not os.path.exists(file_path):
                await safe_edit_message(processing_message, "❌ Kechirasiz, videoni yuklab bo'lmadi.")
                return

        await safe_edit_message(processing_message, "✅ **Yuklab olindi. Endi yuboraman...**", parse_mode='markdown')

        title = info_dict.get('title', 'Nomsiz video')
        uploader = info_dict.get('uploader', 'Noma\'lum manba')
        caption_text = f"**{title}**\n\nManba: {uploader}\n\nYuklab berildi: @Allsavervide0bot" # <-- O'zingizni bot userneumingizni yozing

        async def upload_progress(current, total):
            percentage = current * 100 / total
            await safe_edit_message(processing_message, f"✅ **Yuborilmoqda...**\n`{percentage:.1f}%`", parse_mode='markdown')

        await client.send_file(
            chat_id,
            file_path,
            caption=caption_text,
            attributes=[DocumentAttributeFilename(os.path.basename(file_path))],
            parse_mode='markdown',
            progress_callback=upload_progress
        )
        await client.delete_messages(chat_id, processing_message)
        
        description = info_dict.get('description')
        if description and description.strip():
            unique_id = str(uuid.uuid4())
            temp_descriptions[unique_id] = description
            buttons = [Button.inline("📝 Post matnini olish", data=f"get_desc_{unique_id}")]
            await client.send_message(chat_id, "Postning tavsifini (description) olishni xohlaysizmi?", buttons=buttons)

    except Exception as e:
        log.error(f"Yuklashda xatolik: {e}")
        error_text = str(e)
        if "File is larger than max-filesize" in error_text:
            error_text = "Video hajmi 1 GB dan katta. Iltimos, kichikroq videoni tanlang."
        elif "Sign in to confirm" in error_text or "Login required" in error_text:
            error_text = "Cookie'lar eskirgan yoki noto'g'ri. Iltimos, ularni yangilang."
        
        error_full_text = f"❌ Kechirasiz, xatolik yuz berdi.\n\n`{error_text}`"
        if processing_message:
            await safe_edit_message(processing_message, error_full_text, parse_mode='markdown')
        else:
            await event.reply(error_full_text, parse_mode='markdown')
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)


async def worker():
    """Navbatdan vazifalarni olib, ularni qayta ishlaydi."""
    while True:
        try:
            event, url, ydl_opts = await download_queue.get()
            user_id = event.sender_id
            
            await download_and_send(event, url, ydl_opts)
            
            if user_id in user_locks:
                del user_locks[user_id]
                
        except Exception as e:
            log.error(f"Worker'da xatolik: {e}")
        finally:
            download_queue.task_done()


# --- HANDLERLAR ---

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply("Assalomu alaykum! Video yuklash uchun YouTube yoki Instagram havolasini yuboring.")

@client.on(events.NewMessage(pattern=r'https?://\S+'))
async def main_handler(event):
    user_id = event.sender_id
    
    if user_id in user_locks:
        return await event.reply("⚠️ Sizning oldingi so'rovingiz hali tugamadi. Iltimos, uning yakunlanishini kuting.")

    user_locks[user_id] = True
    url = event.text.strip()
    
    try:
        if not YOUTUBE_RE.match(url) and not INSTAGRAM_RE.match(url):
            return await event.reply("Kechirasiz, men faqat YouTube va Instagram havolalarini qo'llab-quvvatlayman.")

        if 'list=' in url or '/playlist?' in url:
            if url in playlist_info_cache and time.time() - playlist_info_cache[url]['timestamp'] < 3600:
                 info_dict = playlist_info_cache[url]['data']
            else:
                wait_msg = await event.reply("🔗 Playlist tahlil qilinmoqda, iltimos kuting...")
                cookie_file = get_cookie_for_url(url)
                ydl_opts = {'extract_flat': True, 'playlistend': 10, 'cookiefile': cookie_file}
                with YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
                if cookie_file and os.path.exists(cookie_file):
                    os.remove(cookie_file)
                playlist_info_cache[url] = {'data': info_dict, 'timestamp': time.time()}
                await wait_msg.delete()

            playlist_title = info_dict.get('title', 'Nomsiz playlist')
            entries = info_dict.get('entries', [])

            if not entries:
                return await event.reply("❌ Bu playlistda video topilmadi.")

            buttons = []
            for i, entry in enumerate(entries):
                if i >= 10: break
                video_id = entry['id']
                video_title = entry.get('title', f"Video {i+1}")
                unique_id = str(uuid.uuid4())
                temp_urls[unique_id] = f"https://www.youtube.com/watch?v={video_id}"
                
                button_text = video_title[:60] + '…' if len(video_title) > 60 else video_title
                buttons.append([Button.inline(button_text, data=f"video_{unique_id}")])
            
            await client.send_message(
                event.chat_id,
                f"**{playlist_title}** playlistidan videoni tanlang (birinchi {len(buttons)} ta):",
                buttons=buttons, parse_mode='markdown'
            )
        elif INSTAGRAM_RE.match(url):
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': 'downloads/%(id)s.%(ext)s',
                'noplaylist': True,
                'max_filesize': 1024 * 1024 * 1024,
            }
            await download_queue.put((event, url, ydl_opts))
            
        else:
            unique_id = str(uuid.uuid4())
            temp_urls[unique_id] = url
            
            buttons = [
                [Button.inline("🎥 Video (720p)", data=f"quality_720_{unique_id}")],
                [Button.inline("🎥 Video (480p)", data=f"quality_480_{unique_id}")],
                [Button.inline("🎵 Faqat audio (MP3)", data=f"quality_audio_{unique_id}")]
            ]
            await event.reply("Yuklab olish formatini tanlang:", buttons=buttons)

    except Exception as e:
        log.error(f"Main handlerda xatolik: {e}", exc_info=True)
        await event.reply("❌ Havolani tahlil qilishda xatolik yuz berdi. Iltimos, boshqa havolani urinib ko'ring.")
        if user_id in user_locks:
            del user_locks[user_id]

@client.on(events.CallbackQuery(pattern=b'(quality|video)_'))
async def callback_handler(event):
    user_id = event.sender_id
    
    if user_id in user_locks:
        return await event.answer("⚠️ Oldingi so'rovingiz hali tugamadi!", alert=True)

    user_locks[user_id] = True
    
    await event.answer()
    
    data_parts = event.data.decode('utf-8').split('_', 2)
    action = data_parts[0]
    unique_id = data_parts[-1]
    
    url = temp_urls.get(unique_id)

    if not url:
        if user_id in user_locks: del user_locks[user_id]
        return await event.edit("❌ Kechirasiz, bu so'rovning vaqti tugagan. Iltimos, havolani qaytadan yuboring.")
    
    if unique_id in temp_urls:
        del temp_urls[unique_id]

    ydl_opts = {
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'noplaylist': True,
        'max_filesize': 1024 * 1024 * 1024,
    }

    if action == "quality":
        quality = data_parts[1]
        if quality == "audio":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            ydl_opts['format'] = f'best[ext=mp4][height<={quality}]/best[height<={quality}]'
    
    elif action == "video":
        ydl_opts['format'] = 'best[ext=mp4][height<=720]/best[height<=720]'

    await download_queue.put((event, url, ydl_opts))

@client.on(events.CallbackQuery(pattern=b"get_desc_"))
async def description_handler(event):
    """Post matnini (description) olish tugmasi bosilganda ishlaydi."""
    unique_id = event.data.decode('utf-8').replace('get_desc_', '')
    description = temp_descriptions.get(unique_id)

    if not description:
        await event.answer("Kechirasiz, bu so'rov eskirgan yoki matn topilmadi.", alert=True)
        try:
            await event.edit("So'rov muddati o'tgan.")
        except MessageNotModifiedError:
            pass
        return

    await event.delete()

    for i in range(0, len(description), 4096):
        await event.respond(description[i:i+4096])

    if unique_id in temp_descriptions:
        del temp_descriptions[unique_id]


async def main():
    """Asosiy ishga tushirish funksiyasi."""
    os.makedirs('downloads', exist_ok=True)
    
    log.info(f"{NUM_WORKERS} ta ishchi (worker) ishga tushirilmoqda...")
    for _ in range(NUM_WORKERS):
        asyncio.create_task(worker())
    
    log.info("Bot ishga tushdi...")
    await client.start(bot_token=BOT_TOKEN)
    await client.run_until_disconnected()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot o'chirildi.")
