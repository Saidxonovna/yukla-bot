import logging
import os
import asyncio
import re
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
    logging.critical("API_ID, API_HASH yoki BOT_TOKEN topilmadi yoki noto'g'ri formatda!")
    exit(1)

# Telethon klientini yaratish
client = TelegramClient('bot_session', API_ID, API_HASH)


# --- YORDAMCHI FUNKSIYALAR ---

def clean_url(url):
    """Havoladan keraksiz parametrlarni olib tashlab, uni standart formatga keltiradi."""
    # YouTube uchun naqshlar (watch, shorts, youtu.be)
    yt_match = re.search(r'(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
    if yt_match:
        video_id = yt_match.group(1)
        return f'https://www.youtube.com/watch?v={video_id}'

    # Instagram uchun naqshlar (p, reel)
    insta_match = re.search(r'(?:instagram\.com/(?:p|reel)/)([a-zA-Z0-9_-]+)', url)
    if insta_match:
        post_id = insta_match.group(1)
        return f'https://www.instagram.com/p/{post_id}/'
    
    # TikTok uchun oddiy tozalash
    tiktok_match = re.search(r'(tiktok\.com/.*/video/\d+)', url)
    if tiktok_match:
        return f'https://{tiktok_match.group(1)}'

    # Agar mos format topilmasa, asl havolani qaytarish
    return url


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


# --- ASOSIY YUKLASH FUNKSIYASI (GIBRID USUL) ---
async def hybrid_download(event, url):
    chat_id = event.chat_id
    processing_message = None
    info_dict = None

    try:
        if isinstance(event, events.CallbackQuery.Event):
            processing_message = await event.edit("⏳ Havola qayta ishlanmoqda...")
        else:
            processing_message = await event.reply("⏳ Havola qayta ishlanmoqda...")
    except Exception as e:
        logging.error(f"Boshlang'ich xabarni yuborishda xatolik: {e}")
        return

    # --- 1-QADAM: yt-dlp orqali faqat ma'lumotlarni olish (yuklamasdan) ---
    try:
        await safe_edit_message(processing_message, "ℹ️ Video ma'lumotlari olinmoqda...")
        ydl_opts_info = {
            'quiet': True, 'no_warnings': True, 'skip_download': True,
        }
        with YoutubeDL(ydl_opts_info) as ydl:
            loop = asyncio.get_running_loop()
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
    except Exception as e:
        logging.warning(f"yt-dlp orqali ma'lumot olib bo'lmadi: {e}")
        await safe_edit_message(processing_message, "⚠️ Video tafsilotlarini olib bo'lmadi, yuklashda davom etilmoqda...")

    # --- 2-QADAM: Cobalt API orqali videoni o'zini olish ---
    try:
        await safe_edit_message(processing_message, "🌎 Yuklash servisidan video so'ralmoqda...")
        api_url = "https://api.cobalt.tools/api/json"
        payload = {"url": url, "vQuality": "720"}

        async with httpx.AsyncClient(timeout=90) as client_http:
            response = await client_http.post(api_url, json=payload, headers={"Accept": "application/json"})
            response.raise_for_status()
            data = response.json()

        if data.get("status") == "stream":
            video_url = data["url"]
            video_title = info_dict.get('title', 'Yuklab olingan video') if info_dict else "Yuklab olingan video"
            description = info_dict.get('description') if info_dict else None

            await safe_edit_message(processing_message, "✅ Video topildi, Telegram'ga yuborilmoqda...")
            await client.send_file(
                chat_id, file=video_url, caption=f"**{video_title}**\n\n@Allsavervide0bot orqali yuklandi"
            )

            if description and description.strip():
                for i in range(0, len(description), 4096):
                    await client.send_message(chat_id, f"**📝 Video tavsifi:**\n\n{description[i:i+4096]}")
            
            await processing_message.delete()
        else:
            error_text = data.get('text', 'Noma\'lum xato. Bu havolani yuklab bo\'lmaydi.')
            await safe_edit_message(processing_message, f"❌ Xatolik: {error_text}")

    except httpx.HTTPStatusError as e:
        error_msg = f"❌ Video yuklash servisida vaqtinchalik muammo bor (Xato: {e.response.status_code})."
        await safe_edit_message(processing_message, error_msg)
    except httpx.ReadTimeout:
        await safe_edit_message(processing_message, "❌ Video hajmi katta bo'lgani uchun yuklash vaqti tugadi.")
    except Exception as e:
        logging.error(f"Umumiy xatolik: {e}", exc_info=True)
        await safe_edit_message(processing_message, "❌ Kechirasiz, kutilmagan xatolik yuz berdi.")


# --- ASOSIY HANDLERLAR ---
@client.on(events.NewMessage(pattern=re.compile(r'https?://\S+')))
async def main_handler(event):
    url_match = re.search(r'https?://\S+', event.text)
    if not url_match: return
    
    # MUHIM: Havolani tozalash
    original_url = url_match.group(0)
    cleaned_url = clean_url(original_url)
    
    logging.info(f"Asl havola: {original_url} -> Tozalangan havola: {cleaned_url}")

    if "list=" in cleaned_url: # Tozalangan havolada ham playlist bo'lishi mumkin
        await event.reply("Playlist'larni yuklash qo'llab-quvvatlanmaydi. Iltimos, alohida video havolasini yuboring.")
        return

    await hybrid_download(event, cleaned_url)


@client.on(events.CallbackQuery())
async def button_handler(event):
    await event.answer("Bu tugma eskirgan.", alert=True)

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply(
        "Assalomu alaykum! Men YouTube, Instagram va TikTok'dan videolar yuklab beraman.\n\n"
        "Shunchaki video havolasini yuboring."
    )

# --- ASOSIY ISHGA TUSHIRISH FUNKSIYASI ---
async def main():
    await client.start(bot_token=BOT_TOKEN)
    logging.info("Bot gibrid usulda (havola tozalash bilan) muvaffaqiyatli ishga tushdi...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())