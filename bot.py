# -*- coding: utf-8 -*-

"""
Telegram Bot for Downloading Videos from YouTube and Instagram.

This bot uses the Telethon library to interact with Telegram and yt-dlp
to extract download links from various video platforms. It operates on an
asynchronous queue system to handle multiple requests efficiently without
downloading files to the server first.
"""

import os
import re
import asyncio
import logging
import uuid
import time

from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo
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
    TIKTOK_COOKIE = os.environ.get("TIKTOK_COOKIE")
    INSTAGRAM_COOKIE = os.environ.get("INSTAGRAM_COOKIE")
    PINTEREST_COOKIE = os.environ.get("PINTEREST_COOKIE") # Pinterest uchun yangi cookie o'zgaruvchisi
    BOT_USERNAME = os.environ.get("BOT_USERNAME", "@Allsavervide0bot")
except (ValueError, TypeError):
    log.critical("API_ID, API_HASH yoki TELEGRAM_TOKEN muhit o'zgaruvchilarida topilmadi yoki noto'g'ri formatda.")
    exit(1)

# --- Telethon klientini yaratish ---
client = TelegramClient('bot_session', API_ID, API_HASH)

# --- Global o'zgaruvchilar ---
# Yuklab olish uchun navbat (bir vaqtda bir nechta so'rovni boshqarish uchun)
download_queue = asyncio.Queue()

# --- Qo'llab-quvvatlanadigan URL manzillari uchun Regex (regular expressions) ---
SUPPORTED_URL_RE = re.compile(
    r'https?://(?:www\.)?(?:'
    r'instagram\.com/(?:p|reel|tv|stories)/[a-zA-Z0-9_-]+'
    r'|'
    r'(?:vm\.)?tiktok\.com/.*'
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
    elif 'tiktok.com' in lower_url:
        cookie_data = TIKTOK_COOKIE
        cookie_file_path = f'tiktok_cookies_{uuid.uuid4()}.txt'
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
        # Xabar o'zgarmagan bo'lsa, telethon xatolik beradi, shuni ushlab qolamiz.
        pass
    except Exception as e:
        log.warning(f"Xabarni tahrirlashda kutilmagan xatolik: {e}")


# ### ASOSIY YAXSHILANGAN FUNKSIYA ###
async def process_and_send(event, url, ydl_opts, initial_message=None):
    """
    Videoni serverga yuklamasdan, to'g'ridan-to'g'ri havolasini olib,
    Telegram orqali foydalanuvchiga yuboradi.
    
    Args:
        event: Telethon'ning Message yoki CallbackQuery hodisasi.
        url (str): Yuklanadigan video havolasi.
        ydl_opts (dict): yt-dlp uchun sozlamalar.
        initial_message (Message, optional): Jarayon oxirida o'chirilishi kerak bo'lgan xabar.
                                            (Masalan, "Navbatga qo'yildi" xabari).
    """
    chat_id = event.chat_id
    processing_message = None
    cookie_file = None
    loop = asyncio.get_running_loop()

    try:
        # Jarayon boshlanganini foydalanuvchiga bildirish
        processing_message = await event.reply("⏳ Ma'lumotlar olinmoqda...")

        # Kerakli cookie faylini olish
        cookie_file = get_cookie_for_url(url)
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file

        # Asosiy ish: yt-dlp orqali video ma'lumotlarini olish
        # `run_in_executor` orqali bu bloklovchi operatsiya asyncio event loop'ini to'xtatib qo'ymaydi
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = await loop.run_in_executor(
                None, lambda: ydl.extract_info(url, download=False)
            )

        # Playlistlar uchun faqat birinchi videoni olamiz
        if 'entries' in info_dict and info_dict['entries']:
            info_dict = info_dict['entries'][0]

        # yt-dlp format tanlashdan so'ng to'g'ridan-to'g'ri havolani beradi
        direct_url = info_dict.get('url')

        if not direct_url:
            log.error(f"To'g'ridan-to'g'ri URL topilmadi. Info_dict: {info_dict}")
            await safe_edit_message(processing_message, "❌ Kechirasiz, video uchun yuklab olish havolasi topilmadi. Saytda o'zgarish bo'lgan bo'lishi mumkin yoki bu format mavjud emas.")
            return

        # Videoning metama'lumotlarini olish
        title = info_dict.get('title', 'Nomsiz video')
        thumbnail_url = info_dict.get('thumbnail')
        duration = int(info_dict.get('duration', 0))
        uploader = info_dict.get('uploader', "Noma'lum manba")
        caption_text = f"**{title}**\n\nManba: {uploader}\n\nYuklab berdi: {BOT_USERNAME}"

        await safe_edit_message(processing_message, "✅ Havola topildi. Telegram'ga yuborilmoqda...")

        # Faylni yuborishdagi progressni ko'rsatish uchun funksiya
        last_update_time = 0
        async def upload_progress(current, total):
            nonlocal last_update_time
            # Xabarni har 2 soniyada yangilab turamiz (Telegram limitlariga tushmaslik uchun)
            if time.time() - last_update_time > 2:
                percentage = current * 100 / total
                await safe_edit_message(processing_message, f"📤 Yuborilmoqda... {percentage:.1f}%")
                last_update_time = time.time()

        # Fayl turiga qarab (audio yoki video) kerakli atributlarni qo'shamiz
        attributes = []
        is_audio = 'FFmpegExtractAudio' in str(ydl_opts.get('postprocessors', ''))
        if is_audio:
            attributes.append(DocumentAttributeAudio(duration=duration, title=title, performer=uploader))
        else:
            attributes.append(DocumentAttributeVideo(
                duration=duration, w=info_dict.get('width', 0), h=info_dict.get('height', 0),
                supports_streaming=True
            ))
        
        # Faylni to'g'ridan-to'g'ri URL orqali yuborish
        await client.send_file(
            chat_id,
            file=direct_url,
            caption=caption_text,
            parse_mode='markdown',
            attributes=attributes,
            thumb=thumbnail_url,
            progress_callback=upload_progress
        )
        # Jarayon muvaffaqiyatli tugagach, "Yuborilmoqda..." xabarini o'chiramiz
        await client.delete_messages(chat_id, processing_message)

    except Exception as e:
        log.error(f"Jarayonda xatolik: {e}", exc_info=True)
        # Xatolikni foydalanuvchiga tushunarli tilda ko'rsatish
        error_text = str(e).split(';')[0]
        if "confirm your age" in error_text:
            error_text = "Bu video yosh chekloviga ega. Iltimos, sozlamalardan YOUTUBE_COOKIE'ni to'g'ri kiriting."
        elif "Private video" in error_text or "login is required" in error_text:
            error_text = "Bu shaxsiy (private) video. Uni yuklab bo'lmaydi yoki cookie sozlanmagan."
        elif "HTTP Error 404" in error_text:
            error_text = "Video topilmadi yoki o'chirilgan."
        await safe_edit_message(processing_message, f"❌ Kechirasiz, xatolik yuz berdi.\n\n`{error_text}`")
    finally:
        # Vaqtinchalik cookie faylini o'chirish
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)
        # Instagram'dan kelgan "navbatga qo'yildi" xabarini o'chirish
        if initial_message:
            try:
                await client.delete_messages(chat_id, initial_message)
            except Exception as e:
                log.warning(f"Boshlang'ich xabarni o'chirishda xatolik: {e}")

async def worker():
    """
    Navbatdan (queue) vazifalarni olib, ularni birma-bir qayta ishlaydi.
    Bu bir vaqtda bir nechta foydalanuvchidan kelgan so'rovlarni boshqarishga yordam beradi.
    """
    while True:
        # Navbatdan yangi vazifa olish
        item = await download_queue.get()
        event, url, ydl_opts, initial_message = None, None, None, None

        # Vazifani qismlarga ajratish
        if len(item) == 4:
            event, url, ydl_opts, initial_message = item
        else: # Eskiroq format bilan moslik uchun
            event, url, ydl_opts = item

        try:
            # Asosiy funksiyani chaqirish
            await process_and_send(event, url, ydl_opts, initial_message)
        except Exception as e:
            log.error(f"Worker'da kutilmagan xatolik: {e}", exc_info=True)
        finally:
            # Vazifa bajarilganini navbatga bildirish
            download_queue.task_done()

# --- TELEGRAM HANDLER'LARI ---
# Foydalanuvchi bot bilan qanday muloqot qilishini belgilaydi

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Botga /start komandasi yuborilganda javob beradi."""
    await event.reply(
        "Assalomu alaykum! Men Instagram, TikTok va Pinterest'dan video yuklab bera olaman.\n\n"
        "Shunchaki, kerakli video havolasini menga yuboring."
    )

@client.on(events.NewMessage(pattern=SUPPORTED_URL_RE))
async def general_url_handler(event):
    """Barcha qo'llab-quvvatlanadigan havolalar uchun ishlaydi."""
    # Foydalanuvchiga uning so'rovi qabul qilinganini bildiramiz
    initial_message = await event.reply("✅ So'rovingiz qabul qilindi va navbatga qo'yildi...")
    
    # Standart sozlamalar
    ydl_opts = {
        'noplaylist': True,
        'retries': 5
    }
    # Vazifani navbatga qo'yamiz. `initial_message` ham qo'shiladi,
    # chunki u jarayon oxirida o'chirilishi kerak.
    await download_queue.put((event, event.text.strip(), ydl_opts, initial_message))


async def main():
    """Botni ishga tushiruvchi asosiy funksiya."""
    log.info("Bot ishga tushirilmoqda...")
    
    # Bir vaqtda bir nechta yuklashni amalga oshirish uchun 3 ta worker yaratamiz
    for _ in range(3):
        asyncio.create_task(worker())
    
    # Botni Telegram'ga ulaymiz
    await client.start(bot_token=BOT_TOKEN)
    log.info("Bot muvaffaqiyatli ishga tushdi va buyruqlarni kutmoqda.")
    
    # Bot o'chirilguncha ishlab turadi
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot foydalanuvchi tomonidan to'xtatildi.")

