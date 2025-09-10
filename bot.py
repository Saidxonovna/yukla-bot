import logging
import os
import time
import asyncio
from yt_dlp import YoutubeDL
from telethon import TelegramClient, events, Button

# Log yozishni sozlash
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)

# --- Railway'ning "Variables" bo'limidan olinadi ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Telethon klientini yaratish
client = TelegramClient('bot_session', API_ID, API_HASH)


# --- YUKLASH FUNKSIYASI (barcha logikani o'z ichiga oladi) ---
async def download_and_send_video(event, url):
    chat_id = event.chat_id
    processing_message = None
    try:
        if isinstance(event, events.CallbackQuery.Event):
            processing_message = await event.edit("⏳ Havola qabul qilindi. Yuklash jarayoni boshlanmoqda...")
        else:
            processing_message = await event.reply("⏳ Havola qabul qilindi. Yuklash jarayoni boshlanmoqda...")
    except Exception:
        processing_message = await client.send_message(chat_id, "⏳ Havola qabul qilindi. Yuklash jarayoni boshlanmoqda...")

    file_path = None
    try:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': '%(title)s - %(id)s.%(ext)s',
            'noplaylist': True,
            'cookiefile': 'cookies.txt',
            'postprocessor_args': ['-movflags', '+faststart']
        }

        with YoutubeDL(ydl_opts) as ydl:
            loop = asyncio.get_event_loop()
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            file_path = ydl.prepare_filename(info_dict)

        if not file_path or not os.path.exists(file_path):
            await client.edit_message(processing_message, "❌ Kechirasiz, videoni yuklab bo'lmadi.")
            return

        await client.edit_message(processing_message, "✅ Yuborilmoqda...")
        
        # === INSTAGRAM OPISANIYASINI OLISH UCHUN QO'SHILGAN YANGI QISM ===
        description = None
        if "instagram.com" in url.lower():
            description = info_dict.get('description')
        # ===============================================================

        await client.send_file(
            chat_id,
            file_path,
            caption="Video @Allsavervide0bot tomonidan yuklandi !"
        )
        await client.delete_messages(chat_id, processing_message)

        # === AGAR OPISANIYA MAVJUD BO'LSA, ALOHIDA XABAR QILIB YUBORISH ===
        if description and description.strip():
            # Matn uzun bo'lsa, Telegram chegarasiga moslab bo'lib yuborish
            for i in range(0, len(description), 4096):
                await client.send_message(chat_id, f"{description[i:i+4096]}n\**Video @Allsavervide0bot tomonidan yuklandi!**")
        # =================================================================

    except Exception as e:
        logging.error(f"Xatolik yuz berdi: {e}")
        error_text = str(e)
        if "Sign in to confirm" in error_text:
             error_text = "YouTube/Instagram cookie'lari eskirgan. Iltimos, ularni yangilang."
        await client.edit_message(processing_message, f"❌ Kechirasiz, xatolik yuz berdi.\n\n`{error_text}`")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)


# --- ASOSIY HANDLER: XABAR KELGANDA ISHLAYDI ---
@client.on(events.NewMessage(pattern=r'https?://\S+'))
async def main_handler(event):
    url = event.text
    
    if "list=" in url or "/playlist?" in url:
        # Playlist logikasi (o'zgarishsiz)
        await event.reply("⏳ Playlist...")
        # ... (qolgan playlist kodi avvalgidek)
        try:
            ydl_opts = {'extract_flat': True, 'noplaylist': False, 'playlistend': 10, 'cookiefile': 'cookies.txt'}
            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=False)
            buttons = []
            for entry in info_dict.get('entries', []):
                video_id = entry.get('id')
                title = entry.get('title', 'Nomsiz video')
                button_text = title[:45] + '…' if len(title) > 45 else title
                buttons.append([Button.inline(button_text, data=f"dl_{video_id}")])
            if not buttons:
                await event.reply("❌ Playlist'dan videolarni olib bo'lmadi."); return
            await event.client.send_message(event.chat_id, "Quyidagi videolardan birini tanlang:", buttons=buttons)
        except Exception as e:
            await event.reply(f"❌ Playlist'ni o'qishda xatolik: {e}")
    else:
        await download_and_send_video(event, url)


# --- KNOPKA HANDLERI ---
@client.on(events.CallbackQuery(pattern=b"dl_"))
async def button_handler(event):
    video_id = event.data.decode('utf-8').split('_', 1)[1]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    await download_and_send_video(event, video_url)


@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply("Assalomu alaykum! Video yuklash uchun YouTube yoki Instagram havolasini yuboring.")

async def main():
    # O'zgaruvchi nomi yangilandi
    if 'WEBSITE_COOKIES' in os.environ:
        logging.info("Website cookies topildi, cookies.txt fayliga yozilmoqda...")
        with open('cookies.txt', 'w') as f:
            f.write(os.environ['WEBSITE_COOKIES'])
    else:
        logging.warning("WEBSITE_COOKIES muhit o'zgaruvchisi topilmadi.")

    await client.start(bot_token=BOT_TOKEN)
    print("Bot ishga tushdi...")
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
