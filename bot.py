# -*- coding: utf-8 -*-

"""
Telegram Bot for Downloading Videos from Instagram and Pinterest.

This bot uses the Telethon library to interact with Telegram and yt-dlp
to extract video information. It sends videos directly via URL to Telegram.
For Instagram, it provides an option to fetch the post's description
after the video is sent.
"""

import os
import re
import asyncio
import logging
import uuid
import time

from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeVideo
from telethon.errors import MessageNotModifiedError, BotMethodInvalidError
from yt_dlp import YoutubeDL

# --- Logger sozlamalari (dastur ishlashini kuzatish va xatoliklarni oson topish uchun) ---
logging.basicConfig(
    format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO
)
log = logging.getLogger(__name__)

# --- O'zgaruvchilarni muhitdan (environment variables) xavfsiz o'qish ---
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    INSTAGRAM_COOKIE = os.environ.get("INSTAGRAM_COOKIE")
    PINTEREST_COOKIE = os.environ.get("PINTEREST_COOKIE")
    BOT_USERNAME = os.environ.get("BOT_USERNAME", "@Allsavervide0bot")
except (ValueError, TypeError):
    log.critical("API_ID, API_HASH yoki TELEGRAM_TOKEN muhit o'zgaruvchilarida topilmadi yoki noto'g'ri formatda.")
    exit(1)

# --- Telethon klientini yaratish ---
client = TelegramClient('bot_session', API_ID, API_HASH)

# --- Global o'zgaruvchilar ---
download_queue = asyncio.Queue()
# Videoning matnini vaqtinchalik saqlash uchun kesh
post_data_cache = {}


# --- Qo'llab-quvvatlanadigan URL manzillari uchun Regex ---
SUPPORTED_URL_RE = re.compile(
    r'https?://(?:www\.)?(?:'
    r'instagram\.com/(?:p|reel|tv|stories)/[a-zA-Z0-9_-]+'
    r'|'
    r'(?:pinterest\.com|pin\.it)/.*'
    r')'
)


# --- YORDAMCHI FUNKSIYALAR ---

def get_cookie_for_url(url):
    """
    Berilgan havolaga mos keladigan cookie ma'lumotini vaqtinchalik faylga yozadi
    va shu faylning nomini qaytaradi.
    """
    cookie_data = None
    lower_url = url.lower()

    if 'instagram.com' in lower_url:
        cookie_data = INSTAGRAM_COOKIE
        cookie_file_path = f'instagram_cookies_{uuid.uuid4()}.txt'
    elif 'pinterest.com' in lower_url or 'pin.it' in lower_url:
        cookie_data = PINTEREST_COOKIE
        cookie_file_path = f'pinterest_cookies_{uuid.uuid4()}.txt'
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
    """
    Xabarni xavfsiz tahrirlaydi, xatoliklarni oldini oladi.
    """
    if not message or message.text == text:
        return
    try:
        await message.edit(text, **kwargs)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        log.warning(f"Xabarni tahrirlashda kutilmagan xatolik: {e}")

async def clear_cache_entry(key, delay_seconds=300):
    """Belgilangan vaqtdan so'ng keshdan ma'lumotni o'chiradi."""
    await asyncio.sleep(delay_seconds)
    if post_data_cache.pop(key, None):
        log.info(f"Keshdan '{key}' kaliti 5 daqiqadan so'ng o'chirildi.")


# ### ASOSIY YUKLASH FUNKSIYASI ###
async def process_and_send(event, url, ydl_opts, initial_message=None):
    """
    Videoni to'g'ridan-to'g'ri havola orqali Telegramga yuboradi.
    """
    chat_id = event.chat_id
    processing_message = None
    cookie_file = None
    loop = asyncio.get_running_loop()

    try:
        processing_message = await event.reply("⏳ Ma'lumotlar olinmoqda...")
        cookie_file = get_cookie_for_url(url)
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file

        with YoutubeDL(ydl_opts) as ydl:
            info_dict = await loop.run_in_executor(
                None, lambda: ydl.extract_info(url, download=False)
            )

        if 'entries' in info_dict and info_dict['entries']:
            info_dict = info_dict['entries'][0]

        formats = info_dict.get('formats', [info_dict])
        video_formats = [f for f in formats if f.get('vcodec') != 'none' and f.get('url')]
        
        if not video_formats:
            await safe_edit_message(processing_message, "❌ Kechirasiz, bu havola uchun video formatlari topilmadi.")
            return

        best_format = sorted(video_formats, key=lambda f: (f.get('height') or 0, f.get('tbr') or 0), reverse=True)[0]
        direct_url = best_format.get('url')

        if not direct_url:
            await safe_edit_message(processing_message, "❌ Kechirasiz, video uchun yuklab olish havolasi topilmadi.")
            return

        await safe_edit_message(processing_message, "✅ Havola topildi. Telegram'ga yuborilmoqda...")

        title = info_dict.get('title', 'Nomsiz video')
        uploader = info_dict.get('uploader', "Noma'lum manba")
        caption_text = f"**{title}**\n\nManba: {uploader}\nYuklab berdi: {BOT_USERNAME}"

        thumbnail_url = info_dict.get('thumbnail')
        duration = int(info_dict.get('duration', 0))

        last_update_time = 0
        async def upload_progress(current, total):
            nonlocal last_update_time
            if time.time() - last_update_time > 2:
                try:
                    percentage = current * 100 / total
                    await safe_edit_message(processing_message, f"📤 Yuborilmoqda... {percentage:.1f}%")
                except (ZeroDivisionError, TypeError):
                    await safe_edit_message(processing_message, f"📤 Yuborilmoqda...")
                last_update_time = time.time()

        attributes = [DocumentAttributeVideo(
            duration=duration, w=best_format.get('width', 0), h=best_format.get('height', 0),
            supports_streaming=True
        )]
        
        sent_video_message = await client.send_file(
            chat_id, file=direct_url, caption=caption_text, parse_mode='markdown',
            attributes=attributes, thumb=thumbnail_url, progress_callback=upload_progress
        )
        await client.delete_messages(chat_id, processing_message)
        
        # --- Matnni olish tugmasini yuborish (FAQAT Instagram uchun) ---
        description = info_dict.get('description')
        if 'instagram.com' in url.lower() and description and description.strip():
            unique_id = str(uuid.uuid4())
            post_data_cache[unique_id] = description
            
            buttons = [Button.inline("Post matnini olish 👇", data=f"get_text_{unique_id}")]
            try:
                await sent_video_message.reply("Video tavsifini yuklab olish uchun bosing:", buttons=buttons)
            except BotMethodInvalidError:
                # Agar video bilan birga tugma yuborish imkoni bo'lmasa (kanal posti va h.k.)
                await event.reply("Video tavsifini yuklab olish uchun bosing:", buttons=buttons)

            asyncio.create_task(clear_cache_entry(unique_id))

    except Exception as e:
        log.error(f"Jarayonda xatolik: {e}", exc_info=True)
        error_text = str(e)
        site_name = "Pinterest" if "pinterest" in url or "pin.it" in url else "Instagram"
        if "login is required" in error_text:
            error_text = f"Bu shaxsiy video yoki {site_name.upper()}_COOKIE sozlanmagan."
        elif "HTTP Error 404" in error_text:
            error_text = "Video topilmadi yoki o'chirilgan."
        elif "fetching the webpage" in error_text.lower():
            error_text = "Telegram bu havolani ocha olmadi. Bu vaqtinchalik muammo bo'lishi mumkin."
        else:
            error_text = "Noma'lum xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring."
        await safe_edit_message(processing_message, f"❌ Kechirasiz, xatolik yuz berdi.\n\n`{error_text}`")
    finally:
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)
        if initial_message:
            try:
                await client.delete_messages(chat_id, initial_message)
            except Exception:
                pass

async def worker():
    """Navbatdan vazifalarni olib, ularni qayta ishlaydi."""
    while True:
        event, url, ydl_opts, initial_message = await download_queue.get()
        try:
            await process_and_send(event, url, ydl_opts, initial_message)
        except Exception as e:
            log.error(f"Worker'da kutilmagan xatolik: {e}", exc_info=True)
        finally:
            download_queue.task_done()

# --- TELEGRAM HANDLER'LARI ---
@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """/start komandasiga javob beradi."""
    await event.reply(
        "Assalomu alaykum! Men Instagram va Pinterest'dan video yuklab bera olaman.\n\n"
        "Shunchaki, kerakli video havolasini menga yuboring."
    )

@client.on(events.NewMessage(pattern=SUPPORTED_URL_RE))
async def general_url_handler(event):
    """Barcha qo'llab-quvvatlanadigan havolalar uchun ishlaydi."""
    initial_message = await event.reply("✅ So'rovingiz qabul qilindi va navbatga qo'yildi...")
    url = event.text.strip()
    ydl_opts = {
        'noplaylist': True, 'retries': 5, 'quiet': True, 'noprogress': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        }
    }
    await download_queue.put((event, url, ydl_opts, initial_message))

@client.on(events.CallbackQuery(pattern=b'get_text_'))
async def get_text_callback_handler(event):
    """"Post matnini olish" tugmasi bosilganda ishlaydi."""
    unique_id = event.data.decode('utf-8').split('_')[2]
    description = post_data_cache.pop(unique_id, None)

    if not description:
        await event.answer("❌ Bu so'rov muddati tugagan yoki matn topilmadi.", alert=True)
        return

    try:
        # Matnni alohida xabar qilib, videoga javob sifatida yuboramiz
        await event.client.send_message(
            event.chat_id,
            description,
            reply_to=event.message.reply_to_msg_id
        )
        # Tugma bosilgandan so'ng, u joylashgan xabarni o'chiramiz
        await event.delete()
    except Exception as e:
        log.error(f"Matn yuborishda xatolik: {e}")
        await event.answer("❌ Matnni yuborishda xatolik yuz berdi.")

async def main():
    """Botni ishga tushiruvchi asosiy funksiya."""
    log.info("Bot ishga tushirilmoqda...")
    for _ in range(3):
        asyncio.create_task(worker())
    
    await client.start(bot_token=BOT_TOKEN)
    log.info("Bot muvaffaqiyatli ishga tushdi va buyruqlarni kutmoqda.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot foydalanuvchi tomonidan to'xtatildi.")

