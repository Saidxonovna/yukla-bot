import logging
import os
import asyncio
import re
import httpx # Faqat shu kutubxona kerak bo'ladi

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

# --- ASOSIY YUKLASH FUNKSIYASI (COBALT API BILAN) ---
async def download_via_cobalt(event, url):
    chat_id = event.chat_id
    processing_message = None

    try:
        # Foydalanuvchiga jarayon boshlanganini bildirish
        if isinstance(event, events.CallbackQuery.Event):
            processing_message = await event.edit("⏳ Havola qayta ishlanmoqda...")
        else:
            processing_message = await event.reply("⏳ Havola qayta ishlanmoqda...")
    except Exception as e:
        logging.error(f"Boshlang'ich xabarni yuborishda xatolik: {e}")
        return

    try:
        # Cobalt API uchun so'rov tayyorlash
        api_url = "https://co.wuk.sh/api/json"
        payload = {
            "url": url,
            "vQuality": "720",  # Sifatni 720p qilib belgilash
            "isNoTTWatermark": True,
            "isAudioOnly": False
        }
        
        # API'ga asinxron so'rov yuborish (maksimal 90 soniya kutish)
        async with httpx.AsyncClient(timeout=90) as client_http:
            response = await client_http.post(api_url, json=payload, headers={"Accept": "application/json"})
            response.raise_for_status() # Agar xatolik bo'lsa (4xx yoki 5xx)
            data = response.json()

        # Cobalt'dan kelgan javobni tahlil qilish
        if data.get("status") == "stream":
            video_url = data["url"]
            video_title = "Yuklab olingan video" # Cobalt nomni bermaydi
            
            await safe_edit_message(processing_message, "✅ Video topildi, Telegram'ga yuborilmoqda...")

            # Telethon to'g'ridan-to'g'ri URL'dan fayl yuboradi. Serverga saqlash shart emas!
            await client.send_file(
                chat_id,
                file=video_url,
                caption=f"**{video_title}**\n\n@Allsavervide0bot orqali yuklandi"
            )
            await processing_message.delete()
            
        else:
            # Agar Cobalt xatolik qaytarsa
            error_text = data.get('text', 'Noma\'lum xato. Ehtimol, bu havolani yuklab bo\'lmaydi.')
            await safe_edit_message(processing_message, f"❌ Xatolik: {error_text}")

    except httpx.HTTPStatusError:
        await safe_edit_message(processing_message, "❌ Video yuklash servisida vaqtinchalik muammo yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")
    except httpx.ReadTimeout:
        await safe_edit_message(processing_message, "❌ Video juda katta bo'lgani uchun yuklash vaqti tugadi.")
    except Exception as e:
        logging.error(f"Umumiy xatolik: {e}", exc_info=True)
        await safe_edit_message(processing_message, "❌ Kechirasiz, kutilmagan xatolik yuz berdi.")

# --- ASOSIY HANDLERLAR ---
@client.on(events.NewMessage(pattern=re.compile(r'https?://\S+')))
async def main_handler(event):
    url_match = re.search(r'https?://\S+', event.text)
    if not url_match: return
    url = url_match.group(0)
    
    # Playlist'lar hozircha qo'llab-quvvatlanmaydi, chunki Cobalt ularni ishlamaydi
    if "list=" in url or "/playlist?" in url:
        await event.reply("Playlist'larni yuklash hozircha mumkin emas. Iltimos, alohida video havolasini yuboring.")
        return

    await download_via_cobalt(event, url)

@client.on(events.CallbackQuery())
async def button_handler(event):
    # Bu versiyada tugmalar ishlatilmagani uchun, shunchaki javob beramiz
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
    logging.info("Bot Cobalt API bilan muvaffaqiyatli ishga tushdi...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
