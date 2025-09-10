import logging
import os
import time
import asyncio
from yt_dlp import YoutubeDL
from yt_dlp import PinterestDL
from telethon import TelegramClient, events

# Log yozishni sozlash
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)

# --- Railway'ning "Variables" bo'limidan olinadi ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Telethon klientini yaratish
client = TelegramClient('bot_session', API_ID, API_HASH)

# Yuklash progressini ko'rsatish uchun funksiya (o'zgarishsiz)
def progress_callback(current, total, start_time, message, file_name):
    elapsed_time = time.time() - start_time
    if elapsed_time == 0:
        return

    speed = current / elapsed_time
    percentage = current * 100 / total
    progress_str = "[{:<20}] {:.1f}%".format('=' * int(percentage / 5), percentage)

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
            pass

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply(
        "Assalomu alaykum!\n\nMen katta hajmdagi videolarni yuklovchi botman. Menga istalgan video havolasini (linkini) yuboring."
    )

@client.on(events.NewMessage(pattern=r'https?://\S+'))
async def video_handler(event):
    url = event.text
    chat_id = event.chat_id
    
    processing_message = await event.reply("⏳ Havola qabul qilindi. Yuklash jarayoni boshlanmoqda...")

    try:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': '%(title)s.%(ext)s',
            'noplaylist': True,
            'cookiefile': 'cookies.txt',
            # VIDEONING VAQTINI TO'G'RI KO'RSATISH UCHUN QO'SHILDI:
            'postprocessor_args': ['-movflags', '+faststart']
        }

        file_path = None
        with YoutubeDL(ydl_opts) as ydl:
            loop = asyncio.get_event_loop()
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            file_path = ydl.prepare_filename(info_dict)

        if not file_path or not os.path.exists(file_path):
            await client.edit_message(processing_message, "❌ Kechirasiz, videoni yuklab bo'lmadi.")
            return

        await client.edit_message(processing_message, "✅ Video yuklandi! Endi Telegramga yuborilmoqda...")
        
        file_name = os.path.basename(file_path)
        start_time = time.time()

        await client.send_file(
            chat_id,
            file_path,
            caption="Marhamat, videongiz tayyor!",
            progress_callback=lambda current, total: progress_callback(current, total, start_time, processing_message, file_name)
        )
        
        await client.delete_messages(chat_id, processing_message)

    except Exception as e:
        logging.error(f"Xatolik yuz berdi: {e}")
        await client.edit_message(
            processing_message,
            f"❌ Kechirasiz, xatolik yuz berdi.\n\n**Texnik ma'lumot:** `{str(e)}`"
        )
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)


async def main():
    # Bot ishga tushishidan oldin cookie faylni yaratish
    if 'YOUTUBE_COOKIES' in os.environ:
        logging.info("YouTube cookies topildi, cookies.txt fayliga yozilmoqda...")
        with open('cookies.txt', 'w') as f:
            f.write(os.environ['YOUTUBE_COOKIES'])
    else:
        logging.warning("YOUTUBE_COOKIES muhit o'zgaruvchisi topilmadi. Ayrim videolar yuklanmasligi mumkin.")

    await client.start(bot_token=BOT_TOKEN)
    print("Bot ishga tushdi va xabarlarni kutmoqda...")
    await client.run_until_disconnected()


async def main():
    # Bot ishga tushishidan oldin cookie faylni yaratish
    if 'PINTEREST_COOKIES' in os.environ:
        logging.info("PINTEREST cookies topildi, cookies.txt fayliga yozilmoqda...")
        with open('cookies.txt', 'w') as f:
            f.write(os.environ['PINTEREST_COOKIES'])
    else:
        logging.warning("YOUTUBE_COOKIES muhit o'zgaruvchisi topilmadi. Ayrim videolar yuklanmasligi mumkin.")

    await client.start(bot_token=BOT_TOKEN)
    print("Bot ishga tushdi va xabarlarni kutmoqda...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
