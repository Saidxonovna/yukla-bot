# -*- coding: utf-8 -*-

"""
Telegram Bot for Downloading Videos from Instagram and Pinterest.

This bot uses the Telethon library to interact with Telegram and yt-dlp
to extract video information. It downloads the video content into memory
and uploads it directly to Telegram, ensuring reliability.
"""

import os
import re
import asyncio
import logging
import uuid
import time
import httpx
from io import BytesIO

from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeVideo
from telethon.errors import MessageNotModifiedError
from yt_dlp import YoutubeDL

# --- Logger sozlamalari (dastur ishlashini kuzatish va xatoliklarni oson topish uchun) ---
logging.basicConfig(
    format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO
)
log = logging.getLogger(__name__)

# --- O'zgaruvchilarni muhitdan (environment variables) xavfsiz o'qish ---
# Bot ishlashi uchun zarur bo'lgan maxfiy ma'lumotlar
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    # Cookie fayllar yosh cheklovi bo'lgan yoki maxfiy videolarni yuklash uchun kerak
    INSTAGRAM_COOKIE = os.environ.get("INSTAGRAM_COOKIE")
    PINTEREST_COOKIE = os.environ.get("PINTEREST_COOKIE")
    BOT_USERNAME = os.environ.get("BOT_USERNAME", "@Allsavervide0bot")
except (ValueError, TypeError):
    log.critical("API_ID, API_HASH yoki TELEGRAM_TOKEN muhit o'zgaruvchilarida topilmadi yoki noto'g'ri formatda.")
    exit(1)

# --- Telethon klientini yaratish ---
client = TelegramClient('bot_session', API_ID, API_HASH)

# --- Global o'zgaruvchilar ---
# Yuklab olish uchun navbat (bir vaqtda bir nechta so'rovni boshqarish uchun)
download_queue = asyncio.Queue()
# Instagram'dan kelgan va tugma bosilishini kutayotgan so'rovlarni saqlash uchun
pending_instagram_requests = {}


# --- Qo'llab-quvvatlanadigan URL manzillari uchun Regex (regular expressions) ---
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
    va shu faylning nomini qaytaradi. Bu yosh cheklovi bor yoki yopiq
    kontentni yuklash uchun zarur.
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
    Xabarni tahrirlashda xatolik yuzaga kelsa, botning to'xtab qolishining
    oldini oladi. Agar xabar o'zgarmagan bo'lsa, hech narsa qilmaydi.
    """
    if not message or message.text == text:
        return
    try:
        await message.edit(text, **kwargs)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        log.warning(f"Xabarni tahrirlashda kutilmagan xatolik: {e}")


# ### ASOSIY YANGILANGAN FUNKSIYA ###
async def process_and_send(event, url, ydl_opts, initial_message=None, download_caption=False):
    """
    Videoni xotiraga yuklab olib, to'g'ridan-to'g'ri Telegramga fayl
    sifatida yuboradi. Bu usul ancha ishonchli.
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

        await safe_edit_message(processing_message, "✅ Video topildi. Yuklab olinmoqda...")
        
        # Videoni xotiraga yuklash
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(direct_url, timeout=90.0)
            response.raise_for_status()
            video_bytes = response.content
        
        video_stream = BytesIO(video_bytes)
        video_stream.name = f"{info_dict.get('id', 'video')}.mp4"

        # --- Yangilangan caption mantig'i ---
        title = info_dict.get('title', 'Nomsiz video')
        uploader = info_dict.get('uploader', "Noma'lum manba")
        
        base_caption = f"\n\nManba: {uploader}\nYuklab berdi: {BOT_USERNAME}"
        caption_text = f"**{title}**"
        
        # Agar foydalanuvchi matnni ham yuklashni tanlagan bo'lsa
        if download_caption:
            description = info_dict.get('description')
            if description:
                # Telegramning media uchun 1024 belgilik chegarasiga sig'dirish
                max_len = 1024 - len(caption_text) - len(base_caption) - 20 # 20 belgi zaxira uchun
                if len(description) > max_len:
                    description = description[:max_len] + "..."
                caption_text += f"\n\n{description}"
        
        caption_text += base_caption

        thumbnail_url = info_dict.get('thumbnail')
        duration = int(info_dict.get('duration', 0))

        last_update_time = 0
        async def upload_progress(current, total):
            nonlocal last_update_time
            if time.time() - last_update_time > 2:
                percentage = current * 100 / total
                await safe_edit_message(processing_message, f"📤 Yuborilmoqda... {percentage:.1f}%")
                last_update_time = time.time()

        attributes = [DocumentAttributeVideo(
            duration=duration, w=best_format.get('width', 0), h=best_format.get('height', 0),
            supports_streaming=True
        )]
        
        await client.send_file(
            chat_id,
            file=video_stream,
            caption=caption_text,
            parse_mode='markdown',
            attributes=attributes,
            thumb=thumbnail_url,
            progress_callback=upload_progress
        )
        await client.delete_messages(chat_id, processing_message)

    except Exception as e:
        log.error(f"Jarayonda xatolik: {e}", exc_info=True)
        error_text = str(e)
        if "login is required" in error_text:
            site_name = "Pinterest" if "pinterest" in url or "pin.it" in url else "Instagram"
            error_text = f"Bu shaxsiy video. Uni yuklab bo'lmaydi yoki {site_name.upper()}_COOKIE sozlanmagan."
        elif "HTTP Error 404" in error_text:
            error_text = "Video topilmadi yoki o'chirilgan."
        else:
            error_text = "Noma'lum xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring."
        await safe_edit_message(processing_message, f"❌ Kechirasiz, xatolik yuz berdi.\n\n`{error_text}`")
    finally:
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)
        if initial_message:
            try:
                await client.delete_messages(chat_id, initial_message)
            except Exception as e:
                log.warning(f"Boshlang'ich xabarni o'chirishda xatolik: {e}")

async def worker():
    """
    Navbatdan (queue) vazifalarni olib, ularni birma-bir qayta ishlaydi.
    """
    while True:
        item = await download_queue.get()
        event, url, ydl_opts, initial_message, download_caption = item
        try:
            await process_and_send(event, url, ydl_opts, initial_message, download_caption)
        except Exception as e:
            log.error(f"Worker'da kutilmagan xatolik: {e}", exc_info=True)
        finally:
            download_queue.task_done()

# --- TELEGRAM HANDLER'LARI ---
@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Botga /start komandasi yuborilganda javob beradi."""
    await event.reply(
        "Assalomu alaykum! Men Instagram va Pinterest'dan video yuklab bera olaman.\n\n"
        "Shunchaki, kerakli video havolasini menga yuboring."
    )

@client.on(events.NewMessage(pattern=SUPPORTED_URL_RE))
async def general_url_handler(event):
    """Barcha qo'llab-quvvatlanadigan havolalar uchun ishlaydi."""
    url = event.text.strip()
    
    # Agar havola Instagram'dan bo'lsa, matnni yuklash haqida so'raymiz
    if 'instagram.com' in url.lower():
        unique_id = str(uuid.uuid4())
        pending_instagram_requests[unique_id] = url
        
        buttons = [
            [
                Button.inline("✅ Ha, matn bilan", data=f"insta_yes_{unique_id}"),
                Button.inline("❌ Yo'q, faqat video", data=f"insta_no_{unique_id}")
            ]
        ]
        
        await event.reply("Instagram videosining matnini (description) ham birga yuklansinmi?", buttons=buttons)
        return

    # Boshqa saytlar (Pinterest) uchun to'g'ridan-to'g'ri navbatga qo'yamiz
    initial_message = await event.reply("✅ So'rovingiz qabul qilindi va navbatga qo'yildi...")
    
    ydl_opts = {
        'noplaylist': True,
        'retries': 5,
        'quiet': True,
        'noprogress': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        }
    }
    # Navbatga 5 ta element qo'yamiz (oxirgisi 'download_caption' uchun False)
    await download_queue.put((event, url, ydl_opts, initial_message, False))

@client.on(events.CallbackQuery(pattern=b'insta_'))
async def instagram_callback_handler(event):
    """Instagram uchun tugma bosilganda ishlaydi."""
    
    data = event.data.decode('utf-8').split('_')
    choice = data[1]
    unique_id = data[2]
    
    url = pending_instagram_requests.pop(unique_id, None)

    if not url:
        await event.edit("❌ Bu so'rov muddati tugagan yoki bekor qilingan.")
        return

    # Foydalanuvchiga uning so'rovi qabul qilinganini bildirish uchun tugmali xabarni tahrirlaymiz
    await event.edit("✅ So'rovingiz qabul qilindi va navbatga qo'yildi...")
    
    download_caption = (choice == 'yes')
    
    ydl_opts = {
        'noplaylist': True,
        'retries': 5,
        'quiet': True,
        'noprogress': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        }
    }
    # Navbatga 5 ta element qo'yamiz. 'initial_message' bu tugmali xabar bo'ladi
    # va jarayon oxirida o'chirilishi kerak.
    await download_queue.put((event, url, ydl_opts, event.message, download_caption))


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

