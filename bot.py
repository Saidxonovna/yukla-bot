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
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,  # Eng muhimi: faqat ma'lumot olish
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

        # <<< MUHIM: Bu ishonchli va rasmiy Cobalt API manzili
        api_url = "https://api.cobalt.tools/api/json"

        payload = {"url": url, "vQuality": "720"}

        async with httpx.AsyncClient(timeout=90) as client_http:
            response = await client_http.post(api_url, json=payload, headers={"Accept": "application/json"})
            response.raise_for_status()
            data = response.json()

        if data.get("status") == "stream":
            video_url = data["url"]
            # Ma'lumotlar yt-dlp'dan muvaffaqiyatli olingan bo'lsa, o'shani ishlatamiz
            video_title = info_dict.get('title', 'Yuklab olingan video') if info_dict else "Yuklab olingan video"
            description = info_dict.get('description') if info_dict else None

            await safe_edit_message(processing_message, "✅ Video topildi, Telegram'ga yuborilmoqda...")

            await client.send_file(
                chat_id,
                file=video_url,
                caption=f"**{video_title}**\n\n@Allsavervide0bot orqali yuklandi"
            )

            # Agar tavsif mavjud bo'lsa, uni alohida yuborish
            if description and description.strip():
                logging.info(f"Tavsif topildi, {len(description)} belgi yuborilmoqda...")
                for i in range(0, len(description), 4096):
                    chunk = description[i:i+4096]
                    await client.send_message(chat_id, f"**📝 Video tavsifi:**\n\n{chunk}")

            await processing_message.delete()
        else:
            error_text = data.get('text', 'Noma\'lum xato. Bu havolani yuklab bo\'lmaydi.')
            await safe_edit_message(processing_message, f"❌ Xatolik: {error_text}")

    except httpx.HTTPStatusError:
        await safe_edit_message(processing_message, "❌ Video yuklash servisida vaqtinchalik muammo bor. Iltimos, keyinroq urinib ko'ring.")
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
    url = url_match.group(0)

    if "list=" in url or "/playlist?" in url:
        await event.reply("Playlist'larni yuklash qo'llab-quvvatlanmaydi. Iltimos, alohida video havolasini yuboring.")
        return

    await hybrid_download(event, url)

@client.on(events.CallbackQuery())
async def button_handler(event):
    await event.answer("Bu tugma eskirgan.", alert=True)

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply(
        "Assalomu alaykum! Men YouTube va Instagram'dan videolar yuklab beraman.\n\n"
        "Shunchaki video havolasini yuboring."
    )

# --- ASOSIY ISHGA TUSHIRISH FUNKSIYASI ---
async def main():
    await client.start(bot_token=BOT_TOKEN)
    logging.info("Bot gibrid usulda muvaffaqiyatli ishga tushdi...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())