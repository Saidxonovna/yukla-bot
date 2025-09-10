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

# --- YUKLASH FUNKSIYASI ( қайта фойдаланиш учун алоҳида қилинди) ---
# --- YUKLASH FUNKSIYASI ---
async def download_and_send_video(event, url):
    chat_id = event.chat_id
    processing_message = await client.send_message(chat_id, "⏳ Havola qabul qilindi. Yuklash jarayoni boshlanmoqda...")

    try:
        # ydl_opts ichida 'postprocessor_args' borligini tekshiring
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': '%(title)s - %(id)s.%(ext)s',
            'noplaylist': True,
            'cookiefile': 'cookies.txt',
            # --- MANA SHU QATOR "00:00" MUAMMOSINI HAL QILADI ---
            'postprocessor_args': ['-movflags', '+faststart']
        }

        file_path = None
        with YoutubeDL(ydl_opts) as ydl:
            loop = asyncio.get_event_loop()
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            file_path = ydl.prepare_filename(info_dict)

        # ... (funksiyaning qolgan qismi o'zgarishsiz qoladi) ...
        if not file_path or not os.path.exists(file_path):
            await client.edit_message(processing_message, "❌ Kechirasiz, videoni yuklab bo'lmadi.")
            return

        await client.edit_message(processing_message, "✅ Video yuklandi! Endi Telegramga yuborilmoqda...")
        
        file_name = os.path.basename(file_path)
        start_time = time.time()

        def progress_callback(current, total):
            # Progress callback'ni ichki funksiya qilish, xabarni oson uzatish uchun
            elapsed_time = time.time() - start_time
            if elapsed_time == 0: return
            speed = current / elapsed_time
            percentage = current * 100 / total
            progress_str = "[{:<20}] {:.1f}%".format('=' * int(percentage / 5), percentage)
            if int(elapsed_time) % 3 == 0 or current == total:
                try:
                    asyncio.create_task(
                        client.edit_message(
                            processing_message,
                            f"⬆️ **Yuklanmoqda:** `{file_name}`\n{progress_str}\n"
                            f"`{current/1024/1024:.2f} MB / {total/1024/1024:.2f} MB`"
                        )
                    )
                except: pass

        await client.send_file(
            chat_id,
            file_path,
            caption="Marhamat, videongiz tayyor!",
            progress_callback=progress_callback
        )
        await client.delete_messages(chat_id, processing_message)

    except Exception as e:
        logging.error(f"Xatolik yuz berdi: {e}")
        error_text = str(e)
        if "Sign in to confirm" in error_text:
             error_text = "YouTube cookie'lari eskirgan. Iltimos, ularni yangilang."
        await client.edit_message(
            processing_message,
            f"❌ Kechirasiz, xatolik yuz berdi.\n\n**Texnik ma'lumot:** `{error_text}`"
        )
    finally:
        if 'file_path' in locals() and file_path and os.path.exists(file_path):
            os.remove(file_path)


# --- ASOSIY HANDLER: XABAR KELGANDA ISHLAYDI ---
@client.on(events.NewMessage(pattern=r'https?://\S+'))
async def main_handler(event):
    url = event.text
    
    # 1. PLAYLIST'LARNI ANIQLASH
    if "list=" in url or "/playlist?" in url:
        await event.reply("⏳ Playlist aniqlandi. Videolar ro'yxati olinmoqda, kuting...")
        try:
            ydl_opts = {
                'extract_flat': True,  # Faqat video ma'lumotlarini tezda olish uchun
                'noplaylist': False,     # Playlist'ni o'qishga ruxsat berish
                'playlistend': 10,       # Faqat dastlabki 10 ta videoni olish (ko'p bo'lib ketmasligi uchun)
                'cookiefile': 'cookies.txt'
            }
            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=False)
            
            # 2. KNOPKALARNI YARATISH
            buttons = []
            for entry in info_dict.get('entries', []):
                video_id = entry.get('id')
                title = entry.get('title', 'Nomsiz video')
                # Knopka matni 40 belgidan oshmasligi kerak
                button_text = title[:40] + '...' if len(title) > 40 else title
                # Callback data: 'dl_{video_id}' formatida
                buttons.append([Button.inline(button_text, data=f"dl_{video_id}")])
            
            if not buttons:
                await event.reply("❌ Playlist'dan videolarni olib bo'lmadi.")
                return

            await event.client.send_message(
                event.chat_id,
                "Quyidagi videolardan birini tanlang:",
                buttons=buttons
            )
        except Exception as e:
            await event.reply(f"❌ Playlist'ni o'qishda xatolik: {e}")
    else:
        # Agar oddiy video linki bo'lsa, to'g'ridan-to'g'ri yuklash
        await download_and_send_video(event, url)


# --- YANGI HANDLER: KNOPKA BOSILGANDA ISHLAYDI ---
@client.on(events.CallbackQuery(pattern=b"dl_"))
async def button_handler(event):
    # 'dl_VIDEOID' formatidagi ma'lumotni olish
    video_id = event.data.decode('utf-8').split('_', 1)[1]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Knopka bosilganini bildirish va eski xabarni tahrirlash
    await event.edit("✅ Tanlandi! Video yuklash boshlanmoqda...")
    
    # Asosiy yuklash funksiyasini chaqirish
    await download_and_send_video(event, video_url)


@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply("Assalomu alaykum!")

async def main():
    if 'YOUTUBE_COOKIES' in os.environ:
        logging.info("YouTube cookies topildi, cookies.txt fayliga yozilmoqda...")
        with open('cookies.txt', 'w') as f:
            f.write(os.environ['YOUTUBE_COOKIES'])
    else:
        logging.warning("YOUTUBE_COOKIES muhit o'zgaruvchisi topilmadi.")

    await client.start(bot_token=BOT_TOKEN)
    print("Bot ishga tushdi...")
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
