import logging
import os
import time
import asyncio
from yt_dlp import YoutubeDL

from telethon import TelegramClient, events

# Log yozishni sozlash
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)

# --- Muhim! Bularni Railway'ning "Variables" bo'limiga kiritasiz ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Telethon klientini yaratish
# 'bot_session' - bu session fayl nomi, Railway'da har restartda qayta login bo'ladi
client = TelegramClient('bot_session', API_ID, API_HASH)

# Yuklash progressini ko'rsatish uchun funksiya
def progress_callback(current, total, start_time, message, file_name):
    """Fayl yuborilayotganda progressni ko'rsatadi"""
    elapsed_time = time.time() - start_time
    if elapsed_time == 0:
        return
    
    speed = current / elapsed_time
    percentage = current * 100 / total
    progress_str = "[{:<20}] {:.1f}%".format('=' * int(percentage / 5), percentage)
    
    # Xabarni har 2-3 sekundda yangilab turish uchun
    if int(elapsed_time) % 3 == 0 or current == total:
        try:
            asyncio.create_task(
                client.edit_message(
                    message,
                    f"⬆️ **Yuklanmoqda:** `{file_name}`\n{progress_str}\n"
                    f"`{current/1024/1024:.2f} MB / {total/1024/1024:.2f} MB`\n"
                    f"**Tezlik:** `{speed/1024:.1f} KB/s`"
                )
            )
        except:
            pass # Xabar o'zgarmagan bo'lsa xatolik bermaslik uchun


# /start buyrug'i uchun
@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply(
        "Assalomu alaykum!\n\nMen katta hajmdagi videolarni yuklovchi botman. Menga istalgan video havolasini (linkini) yuboring."
    )

# Matnli xabarlar (havolalar) uchun
@client.on(events.NewMessage(pattern=r'https?://\S+'))
async def video_handler(event):
    url = event.text
    chat_id = event.chat_id
    
    # Jarayon boshlanganini bildirish
    processing_message = await event.reply("⏳ Havola qabul qilindi. Yuklash jarayoni boshlanmoqda...")

    try:
        # yt-dlp sozlamalari (50MB cheklovi olib tashlangan)
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': '%(title)s.%(ext)s',
            'noplaylist': True,
        }

        file_path = None
        with YoutubeDL(ydl_opts) as ydl:
            loop = asyncio.get_event_loop()
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            file_path = ydl.prepare_filename(info_dict)

        if not file_path or not os.path.exists(file_path):
            await client.edit_message(processing_message, "❌ Kechirasiz, videoni yuklab bo'lmadi.")
            return

        # Videoni yuborish
        await client.edit_message(processing_message, "✅ Video yuklandi! Endi Telegramga yuborilmoqda...")
        
        file_name = os.path.basename(file_path)
        start_time = time.time()

        # Asosiy yuborish funksiyasi
        await client.send_file(
            chat_id,
            file_path,
            caption="Marhamat, videongiz tayyor!",
            progress_callback=lambda current, total: progress_callback(current, total, start_time, processing_message, file_name)
        )
        
        # Jarayon tugagach xabarni o'chirish
        await client.delete_messages(chat_id, processing_message)

    except Exception as e:
        logging.error(f"Xatolik yuz berdi: {e}")
        await client.edit_message(
            processing_message,
            f"❌ Kechirasiz, xatolik yuz berdi.\n\n**Texnik ma'lumot:** `{str(e)}`"
        )
    finally:
        # Yuklangan faylni serverdan o'chirish (Juda muhim!)
        if file_path and os.path.exists(file_path):
            os.remove(file_path)


async def main():
    # Bot sifatida tizimga kirish
    await client.start(bot_token=BOT_TOKEN)
    print("Bot ishga tushdi va xabarlarni kutmoqda...")
    # Botni o'chirmasdan ishlashini ta'minlash
    await client.run_until_disconnected()


if __name__ == '__main__':
    # Asinxron dasturni ishga tushirish
    asyncio.run(main())
    
