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
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    YOUTUBE_COOKIE = os.environ.get("YOUTUBE_COOKIE")
    INSTAGRAM_COOKIE = os.environ.get("INSTAGRAM_COOKIE")
    BOT_USERNAME = os.environ.get("BOT_USERNAME", "@Allsavervide0bot")
except (ValueError, TypeError):
    log.critical("API_ID, API_HASH yoki TELEGRAM_TOKEN muhit o'zgaruvchilarida topilmadi yoki noto'g'ri formatda.")
    exit(1)

# Telethon klientini yaratish
client = TelegramClient('bot_session', API_ID, API_HASH)

# Global navbat va vaqtinchalik URL saqlash joyi
download_queue = asyncio.Queue()
temp_urls = {}

# Qo'llab-quvvatlanadigan URLlar uchun regex
YOUTUBE_RE = re.compile(r'https?://(?:www\.)?(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/|playlist\?list=)).*')
INSTAGRAM_RE = re.compile(r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv|stories)/[a-zA-Z0-9_-]+')


# --- YORDAMCHI FUNKSIYALAR ---

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

async def safe_edit_message(message, text, **kwargs):
    """Xabarni xavfsiz tahrirlaydi."""
    if not message or message.text == text:
        return
    try:
        await message.edit(text, **kwargs)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        log.warning(f"Xabarni tahrirlashda kutilmagan xatolik: {e}")


# ### ASOSIY YAXSHILANGAN FUNKSIYA ###
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

        with YoutubeDL(ydl_opts) as ydl:
            info_dict = await loop.run_in_executor(
                None, lambda: ydl.extract_info(url, download=False)
            )

        # Ba'zi playlistlar yoki kanallarda bir nechta video bo'lishi mumkin
        # Shuning uchun birinchi videoni olamiz
        if 'entries' in info_dict:
            info_dict = info_dict['entries'][0]

        formats = info_dict.get('formats', [info_dict])
        direct_url = None

        # Audio uchun eng yaxshi audioni qidiramiz
        if 'FFmpegExtractAudio' in str(ydl_opts.get('postprocessors', '')):
             for f in sorted(formats, key=lambda f: f.get('abr', 0), reverse=True):
                 if f.get('url') and f.get('acodec') != 'none':
                     direct_url = f.get('url')
                     break
        # Video uchun mos sifatdagi, oldindan birlashtirilgan (pre-merged) formatni qidiramiz
        else:
             height_str = ydl_opts.get('format_note', 'best').replace('p', '')
             try:
                 req_height = int(height_str)
             except (ValueError, TypeError):
                 req_height = 1080 # default
             
             for f in sorted(formats, key=lambda f: f.get('height') or 0, reverse=True):
                 if f.get('url') and f.get('vcodec') != 'none' and f.get('acodec') != 'none' and (f.get('height') or 0) <= req_height:
                      direct_url = f.get('url')
                      break

        if not direct_url:
            # Agar oldindan birlashtirilgan format topilmasa, eng yaxshisini olamiz
            direct_url = info_dict.get('url')

        if not direct_url:
            log.error(f"URL topilmadi. Info_dict: {info_dict}")
            return await safe_edit_message(processing_message, "❌ Kechirasiz, video uchun yuklab olish havolasi topilmadi. Saytda o'zgarish bo'lgan bo'lishi mumkin.")

        title = info_dict.get('title', 'Nomsiz video')
        thumbnail_url = info_dict.get('thumbnail')
        duration = int(info_dict.get('duration', 0))
        uploader = info_dict.get('uploader', 'Noma\'lum manba')
        caption_text = f"**{title}**\n\nManba: {uploader}\n\nYuklab berdi: {BOT_USERNAME}"

        await safe_edit_message(processing_message, "✅ Havola topildi. Telegram'ga yuborilmoqda...")

        # Progress callback
        last_update_time = 0
        async def upload_progress(current, total):
            nonlocal last_update_time
            if time.time() - last_update_time > 2:
                percentage = current * 100 / total
                await safe_edit_message(processing_message, f"✅ Yuborilmoqda... {percentage:.1f}%")
                last_update_time = time.time()

        attributes = []
        is_audio = 'FFmpegExtractAudio' in str(ydl_opts.get('postprocessors', ''))
        if is_audio:
            attributes.append(DocumentAttributeAudio(duration=duration, title=title, performer=uploader))
        else:
            attributes.append(DocumentAttributeVideo(
                duration=duration, w=info_dict.get('width', 0), h=info_dict.get('height', 0),
                supports_streaming=True
            ))

        await client.send_file(
            chat_id, file=direct_url, caption=caption_text, parse_mode='markdown',
            attributes=attributes, thumb=thumbnail_url, progress_callback=upload_progress
        )
        await client.delete_messages(chat_id, processing_message)

    except Exception as e:
        log.error(f"Jarayonda xatolik: {e}", exc_info=True)
        error_text = str(e).split(';')[0]
        if "confirm your age" in error_text:
            error_text = "Bu video yosh chekloviga ega. Iltimos, YOUTUBE_COOKIE'ni sozlang."
        elif "Private video" in error_text:
            error_text = "Bu shaxsiy video. Uni yuklab bo'lmaydi."
        elif "HTTP Error 404" in error_text:
            error_text = "Video topilmadi yoki o'chirilgan."
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
            log.error(f"Worker'da kutilmagan xatolik: {e}", exc_info=True)
        finally:
            download_queue.task_done()

# --- HANDLERLAR ---

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply("Assalomu alaykum! Video yuklash uchun YouTube yoki Instagram havolasini yuboring.")

@client.on(events.NewMessage(pattern=YOUTUBE_RE))
async def youtube_handler(event):
    if 'list=' in event.text or '/playlist?' in event.text:
        return await event.reply("🚧 Kechirasiz, playlistlarni yuklash vaqtincha to'xtatilgan.")
    
    unique_id = str(uuid.uuid4())
    temp_urls[unique_id] = event.text.strip()
    
    buttons = [
        [Button.inline("🎥 Video (720p)", data=f"quality_720_{unique_id}")],
        [Button.inline("🎥 Video (360p)", data=f"quality_360_{unique_id}")],
        [Button.inline("🎵 Faqat audio (MP3)", data=f"quality_audio_{unique_id}")]
    ]
    await event.reply("Yuklab olish formatini tanlang:", buttons=buttons)

@client.on(events.NewMessage(pattern=INSTAGRAM_RE))
async def instagram_handler(event):
    await event.reply("✅ So'rovingiz qabul qilindi va navbatga qo'yildi.")
    ydl_opts = {'noplaylist': True, 'retries': 5}
    await download_queue.put((event, event.text.strip(), ydl_opts))

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
        ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]
    else:
        # Sifatni 'format_note' orqali yuborish
        ydl_opts['format_note'] = f'{quality}p'
        
    await download_queue.put((event, url, ydl_opts))

async def main():
    """Asosiy ishga tushirish funksiyasi."""
    log.info("Bot ishga tushirilmoqda...")
    
    # Worker'lar
    for _ in range(3):
        asyncio.create_task(worker())
    
    await client.start(bot_token=BOT_TOKEN)
    log.info("Bot muvaffaqiyatli ishga tushdi.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot o'chirildi.")
