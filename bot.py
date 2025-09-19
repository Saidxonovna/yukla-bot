import os
import re
import asyncio
import logging
import uuid
import time
from functools import lru_cache

from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo
from telethon.errors import MessageNotModifiedError
from yt_dlp import YoutubeDL

# Logger sozlamalari (xatoliklarni oson topish uchun)
logging.basicConfig(
    format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO
)
log = logging.getLogger(__name__)

# --- O'zgaruvchilarni muhitdan (environment variables) o'qish ---
# Bu ma'lumotlarni Railway'ning "Variables" bo'limiga joylashtirasiz
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    YOUTUBE_COOKIE = os.environ.get("YOUTUBE_COOKIE")
    INSTAGRAM_COOKIE = os.environ.get("INSTAGRAM_COOKIE")
    BOT_USERNAME = os.environ.get("BOT_USERNAME", "@Allsavervide0bot") # Bot username'ini ham o'zgaruvchi qiling
except (ValueError, TypeError):
    log.critical("API_ID, API_HASH yoki TELEGRAM_TOKEN muhit o'zgaruvchilarida topilmadi yoki noto'g'ri formatda.")
    exit(1)

# Telethon klientini yaratish
client = TelegramClient('bot_session', API_ID, API_HASH)

# Global navbat va vaqtinchalik URL saqlash joyi
download_queue = asyncio.Queue()
temp_urls = {} # Foydalanuvchi tugmani bosguncha URL'ni saqlab turish uchun

# Qo'llab-quvvatlanadigan URLlar uchun regex
YOUTUBE_RE = re.compile(r'https?://(?:www\.)?(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/|playlist\?list=)).*')
INSTAGRAM_RE = re.compile(r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[a-zA-Z0-9_-]+')

# --- YORDAMCHI FUNKSIYALAR ---

@lru_cache(maxsize=128)
def get_cookie_for_url(url):
    """Havolaga mos cookie faylini vaqtincha yaratadi va uning nomini qaytaradi."""
    cookie_data = None
    lower_url = url.lower()

    if 'youtube.com' in lower_url or 'youtu.be' in lower_url:
        cookie_data = YOUTUBE_COOKIE
        cookie_file_path = f'youtube_cookies_{uuid.uuid4()}.txt'
    elif 'instagram.com' in lower_url:
        cookie_data = INSTAGRAM_COOKIE
        cookie_file_path = f'instagram_cookies_{uuid.uuid4()}.txt'
    else:
        return None

    if cookie_data:
        try:
            with open(cookie_file_path, 'w', encoding='utf-8') as f:
                f.write(cookie_data)
            return cookie_file_path
        except IOError as e:
            log.error(f"Cookie faylini yozishda xatolik: {e}")
            return None
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

# ### ASOSIY O'ZGARISH QILINGAN FUNKSIYA ###
async def process_and_send(event, url, ydl_opts):
    """
    Videoni serverga YUKLAMASDAN, to'g'ridan-to'g'ri havolasini olib,
    Telegram orqali yuboradi.
    """
    chat_id = event.chat_id
    processing_message = None
    cookie_file = None
    loop = asyncio.get_running_loop()

    try:
        if isinstance(event, events.CallbackQuery.Event):
            processing_message = await event.edit("⏳ Ma'lumotlar olinmoqda...")
        else:
            processing_message = await event.reply("⏳ Ma'lumotlar olinmoqda...")

        cookie_file = get_cookie_for_url(url)
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file

        # 1. Faqat ma'lumot olish, YUKLAMASLIK (download=False)
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = await loop.run_in_executor(
                None, lambda: ydl.extract_info(url, download=False)
            )

        # 2. To'g'ridan-to'g'ri havolani, sarlavha va boshqa ma'lumotlarni olish
        direct_url = info_dict.get('url')
        if not direct_url:
            return await safe_edit_message(processing_message, "❌ Kechirasiz, video uchun yuklab olish havolasi topilmadi.")

        title = info_dict.get('title', 'Nomsiz video')
        thumbnail_url = info_dict.get('thumbnail')
        duration = info_dict.get('duration', 0)
        uploader = info_dict.get('uploader', 'Noma\'lum manba')
        caption_text = f"**{title}**\n\nManba: {uploader}\n\nYuklab berdi: {BOT_USERNAME}"

        # 3. Fayl yo'li o'rniga TO'G'RIDAN-TO'G'RI HAVOLANI yuborish
        await safe_edit_message(processing_message, "✅ Havola topildi. Telegram'ga yuborilmoqda...")

        # Telegramga yuborish jarayonini ko'rsatish
        last_update_time = 0
        async def upload_progress(current, total):
            nonlocal last_update_time
            current_time = time.time()
            if current_time - last_update_time > 2:
                percentage = current * 100 / total
                await safe_edit_message(processing_message, f"✅ Yuborilmoqda... {percentage:.1f}%")
                last_update_time = current_time

        # Audio yoki video ekanligiga qarab atributlarni to'g'rilash
        attributes = []
        is_audio = 'FFmpegExtractAudio' in str(ydl_opts.get('postprocessors', ''))
        if is_audio:
            attributes.append(DocumentAttributeAudio(duration=duration, title=title, performer=uploader))
        else:
            attributes.append(DocumentAttributeVideo(
                duration=duration,
                w=info_dict.get('width', 0),
                h=info_dict.get('height', 0),
                supports_streaming=True
            ))

        await client.send_file(
            chat_id,
            file=direct_url, # Eng asosiy o'zgarish shu yerda!
            caption=caption_text,
            parse_mode='markdown',
            attributes=attributes,
            thumb=thumbnail_url,
            progress_callback=upload_progress
        )
        await client.delete_messages(chat_id, processing_message)

    except Exception as e:
        log.error(f"Jarayonda xatolik: {e}", exc_info=True)
        error_text = str(e).split(';')[-1] # Xatoning asosiy qismini olish
        if "confirm your age" in error_text:
            error_text = "Bu video yosh chekloviga ega. Iltimos, YOUTUBE_COOKIE'ni sozlang."
        elif "Private video" in error_text:
            error_text = "Bu shaxsiy video. Uni yuklab bo'lmaydi."
        await safe_edit_message(processing_message, f"❌ Kechirasiz, xatolik yuz berdi.\n\n`{error_text}`")
    finally:
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)

async def worker():
    """Navbatdan vazifalarni olib, ularni qayta ishlaydi."""
    while True:
        event, url, ydl_opts = await download_queue.get()
        try:
            await process_and_send(event, url, ydl_opts)
        except Exception as e:
            log.error(f"Worker'da kutilmagan xatolik: {e}")
        finally:
            download_queue.task_done()

# --- HANDLERLAR (Xabarlarni qabul qiluvchilar) ---

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply(
        "Assalomu alaykum! Video yuklash uchun YouTube yoki Instagram havolasini yuboring."
    )

@client.on(events.NewMessage(pattern=YOUTUBE_RE))
async def youtube_handler(event):
    url = event.text.strip()
    # Playlistni aniqlash
    if 'list=' in url or '/playlist?' in url:
        return await event.reply("🚧 Kechirasiz, playlistlarni yuklash vaqtincha to'xtatilgan.")
        # Kelajakda playlistlar mantig'ini shu yerga qo'shish mumkin
    
    # Oddiy YouTube videolari uchun
    unique_id = str(uuid.uuid4())
    temp_urls[unique_id] = url
    
    buttons = [
        [Button.inline("🎥 Video (720p)", data=f"quality_720_{unique_id}")],
        [Button.inline("🎥 Video (360p)", data=f"quality_360_{unique_id}")],
        [Button.inline("🎵 Faqat audio (MP3)", data=f"quality_audio_{unique_id}")]
    ]
    await event.reply("Yuklab olish formatini tanlang:", buttons=buttons)

@client.on(events.NewMessage(pattern=INSTAGRAM_RE))
async def instagram_handler(event):
    url = event.text.strip()
    await event.reply("✅ So'rovingiz qabul qilindi va navbatga qo'yildi.")
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'noplaylist': True,
        'retries': 5,
    }
    await download_queue.put((event, url, ydl_opts))

# Tugmalarni bosishni qabul qiluvchi handler
@client.on(events.CallbackQuery(pattern=b'quality_'))
async def quality_handler(event):
    await event.answer("So'rovingiz qabul qilindi...")
    
    data = event.data.decode('utf-8').split('_', 2)
    quality, unique_id = data[1], data[2]
    url = temp_urls.pop(unique_id, None)

    if not url:
        return await event.edit("❌ Kechirasiz, bu so'rov muddati tugagan.")

    ydl_opts = {'noplaylist': True, 'retries': 5}
    if quality == "audio":
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]
    else:
        ydl_opts['format'] = f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4][height<={quality}]/best'
    
    await download_queue.put((event, url, ydl_opts))

async def main():
    """Asosiy ishga tushirish funksiyasi."""
    log.info("Bot ishga tushirilmoqda...")
    
    # Worker'larni (yuklovchilarni) fon rejimida ishga tushirish
    num_workers = 3
    for _ in range(num_workers):
        asyncio.create_task(worker())
    
    await client.start(bot_token=BOT_TOKEN)
    log.info("Bot muvaffaqiyatli ishga tushdi va xabarlarni qabul qilmoqda.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot o'chirildi.")
