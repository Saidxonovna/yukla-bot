# -*- coding: utf-8 -*-

"""
Telegram Bot for Downloading Media from Instagram (Posts, Reels, Stories, Carousels) and Pinterest.

This bot uses the Telethon library to interact with Telegram and yt-dlp
to extract media information. It can handle single videos, images, and posts
with multiple media items (carousels). It sends media directly via URL to
Telegram for speed. For Instagram, it provides an option to fetch the post's
description after the media is sent.
"""

import os
import re
import asyncio
import logging
import uuid
import time

from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributePhoto
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
# Videoning matnini saqlash uchun kesh
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


# ### ASOSIY YUKLASH FUNKSIYASI ###
async def process_and_send(event, url, ydl_opts):
    """
    Media (video, rasm, karusel) ma'lumotlarini olib, to'g'ridan-to'g'ri havola orqali Telegramga yuboradi.
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

        media_items = info_dict.get('entries', [info_dict])
        if not media_items:
            await safe_edit_message(processing_message, "❌ Kechirasiz, bu havola uchun media fayllar topilmadi.")
            return

        if len(media_items) > 1:
            await safe_edit_message(processing_message, f"✅ Postdagi {len(media_items)} ta media fayl topildi. Yuborilmoqda...")
        else:
            await safe_edit_message(processing_message, "✅ Media fayl topildi. Telegram'ga yuborilmoqda...")

        last_sent_message = None
        for i, item in enumerate(media_items):
            is_video = item.get('vcodec') != 'none' and item.get('url')
            # Rasm uchun eng yaxshi sifatdagi `url`ni topish
            is_image = not is_video and (item.get('url') or item.get('thumbnails'))
            
            direct_url = None
            attributes = None
            
            # Sarlavha faqat birinchi media faylga qo'shiladi
            caption_text = ""
            if i == 0:
                title = item.get('title', 'Nomsiz media')
                uploader = item.get('uploader', "Noma'lum manba")
                caption_text = f"**{title}**\n\nManba: {uploader}\nYuklab berdi: {BOT_USERNAME}"

            if is_video:
                formats = item.get('formats', [item])
                video_formats = [f for f in formats if f.get('vcodec') != 'none' and f.get('url')]
                if not video_formats:
                    continue # Videoni o'tkazib yuborish
                
                best_format = sorted(video_formats, key=lambda f: (f.get('height') or 0, f.get('tbr') or 0), reverse=True)[0]
                direct_url = best_format.get('url')
                duration = int(item.get('duration', 0))
                attributes = [DocumentAttributeVideo(
                    duration=duration, w=best_format.get('width', 0), h=best_format.get('height', 0),
                    supports_streaming=True
                )]

            elif is_image:
                # Rasmlar uchun to'g'ridan-to'g'ri 'url' yoki eng sifatli 'thumbnail'ni ishlatamiz
                if 'url' in item:
                    direct_url = item['url']
                else:
                    best_thumbnail = sorted(item.get('thumbnails', []), key=lambda t: t.get('height', 0))[-1]
                    direct_url = best_thumbnail.get('url')
                attributes = [DocumentAttributePhoto()]

            if direct_url:
                try:
                    last_sent_message = await client.send_file(
                        chat_id,
                        file=direct_url,
                        caption=caption_text,
                        parse_mode='markdown',
                        attributes=attributes
                    )
                    await asyncio.sleep(1) # Telegram spam-filtridan o'tish uchun
                except Exception as send_error:
                    log.error(f"Fayl yuborishda xatolik ({direct_url}): {send_error}")
                    await event.reply(f"❌ {i+1}-faylni yuborishda xatolik yuz berdi.")

        await client.delete_messages(chat_id, processing_message)
        
        # --- Matnni olish tugmasini yuborish (FAQAT Instagram uchun) ---
        description = info_dict.get('description') or (media_items[0].get('description') if media_items else '')
        if 'instagram.com' in url.lower() and description and description.strip() and last_sent_message:
            unique_id = str(uuid.uuid4())
            post_data_cache[unique_id] = description
            
            buttons = [Button.inline("Post matnini olish 👇", data=f"get_text_{unique_id}")]
            try:
                # Tugmani oxirgi yuborilgan mediaga javob sifatida yuborish
                await last_sent_message.reply("Video/post tavsifini yuklab olish uchun bosing:", buttons=buttons)
            except (BotMethodInvalidError, AttributeError):
                 await event.reply("Video/post tavsifini yuklab olish uchun bosing:", buttons=buttons)

    except Exception as e:
        log.error(f"Jarayonda xatolik: {e}", exc_info=True)
        error_text = str(e)
        site_name = "Pinterest" if "pinterest" in url or "pin.it" in url else "Instagram"
        if "login is required" in error_text:
            error_text = f"Bu shaxsiy media yoki {site_name.upper()}_COOKIE sozlanmagan/eskirgan."
        elif "HTTP Error 404" in error_text:
            error_text = "Media topilmadi yoki o'chirilgan."
        elif "fetching the webpage" in error_text.lower():
            error_text = "Telegram bu havolani ocha olmadi. Bu vaqtinchalik muammo bo'lishi mumkin."
        else:
            error_text = "Noma'lum xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring."
        if processing_message:
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

# --- TELEGRAM HANDLER'LARI ---
@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """/start komandasiga javob beradi."""
    await event.reply(
        "Assalomu alaykum! Men Instagram (Post, Reel, Story) va Pinterest'dan media yuklab bera olaman.\n\n"
        "Shunchaki, kerakli media havolasini menga yuboring."
    )

@client.on(events.NewMessage(pattern=SUPPORTED_URL_RE))
async def general_url_handler(event):
    """Barcha qo'llab-quvvatlanadigan havolalar uchun ishlaydi."""
    url = event.text.strip()
    ydl_opts = {
        'noplaylist': False, # Karusellarni yuklash uchun False bo'lishi kerak
        'retries': 5, 'quiet': True, 'noprogress': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        }
    }
    await download_queue.put((event, url, ydl_opts))

@client.on(events.CallbackQuery(pattern=b'get_text_'))
async def get_text_callback_handler(event):
    """"Post matnini olish" tugmasi bosilganda ishlaydi."""
    await event.answer()

    unique_id = event.data.decode('utf-8').split('_')[2]
    description = post_data_cache.get(unique_id)

    if not description:
        await event.answer("❌ Matn topilmadi yoki bu so'rov eskirgan.", alert=True)
        return

    try:
        MESSAGE_CHAR_LIMIT = 4096
        text_parts = [description[i:i + MESSAGE_CHAR_LIMIT] for i in range(0, len(description), MESSAGE_CHAR_LIMIT)]

        for part in text_parts:
            await event.client.send_message(
                event.chat_id,
                part,
                reply_to=event.message.reply_to_msg_id
            )
            await asyncio.sleep(0.1)

        await event.edit("✅ Matn yuborildi.", buttons=None)

    except Exception as e:
        log.error(f"Matn yuborishda xatolik: {e}")
        await event.answer("❌ Matnni yuborishda xatolik yuz berdi.", alert=True)


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