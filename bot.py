import logging
import os
import time
import asyncio
import re
from yt_dlp import YoutubeDL

from telethon import TelegramClient, events, Button
from telethon.errors import MessageNotModifiedError

# Log yozishni sozlash (xatoliklarni kuzatish uchun)
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)

# --- Railway'ning "Variables" bo'limidan olinadigan ma'lumotlar ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
# IKKITA ALOHIDA COOKIE UCHUN O'ZGARUVCHILAR
YOUTUBE_COOKIE = os.environ.get("YOUTUBE_COOKIE")
INSTAGRAM_COOKIE = os.environ.get("INSTAGRAM_COOKIE")


# Telethon klientini yaratish
client = TelegramClient('bot_session', API_ID, API_HASH)


# --- YORDAMCHI FUNKSIYALAR ---

def get_cookie_for_url(url):
    """Havolani tahlil qilib, mos cookie faylini yaratadi va uning nomini qaytaradi."""
    cookie_file_path = None
    cookie_data = None
    lower_url = url.lower()

    if 'youtube.com' in lower_url or 'youtu.be' in lower_url:
        cookie_data = YOUTUBE_COOKIE
        cookie_file_path = 'youtube_cookies.txt'
    elif 'instagram.com' in lower_url:
        cookie_data = INSTAGRAM_COOKIE
        cookie_file_path = 'instagram_cookies.txt'

    if cookie_data and cookie_file_path:
        with open(cookie_file_path, 'w', encoding='utf-8') as f:
            f.write(cookie_data)
        return cookie_file_path
    return None

async def safe_edit_message(message, text, **kwargs):
    """Xabarni xavfsiz tahrirlaydi, 'MessageNotModifiedError' xatosini e'tiborsiz qoldiradi."""
    if not message or message.text == text:
        return
    try:
        await message.edit(text, **kwargs)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        logging.warning(f"Xabarni tahrirlashda kutilmagan xatolik: {e}")


# --- YUKLASH FUNKSIYASI (Barcha logikani o'z ichiga oladi) ---
async def download_and_send_video(event, url):
    chat_id = event.chat_id
    processing_message = None
    cookie_file = None
    file_path = None
    # --- XATOLIK TUZATILDI ---
    # Joriy asyncio siklini o'zgaruvchiga saqlab olamiz
    loop = asyncio.get_running_loop()

    try:
        if isinstance(event, events.CallbackQuery.Event):
            processing_message = await event.edit("⏳Havola tekshirilmoqda...")
        else:
            processing_message = await event.reply("⏳Havola tekshirilmoqda...")

        cookie_file = get_cookie_for_url(url)

        # --- SERVERGA YUKLASH JARAYONINI KO'RSATISH UCHUN ---
        last_update = 0
        def progress_hook(d):
            nonlocal last_update
            if d['status'] == 'downloading':
                current_time = time.time()
                if current_time - last_update > 3:
                    percentage = d['_percent_str']
                    speed = d['_speed_str']
                    eta = d['_eta_str']
                    progress_text = f"📥Yuklanmoqda...\n\n{percentage} | {speed} | {eta}"
                    # --- XATOLIK TUZATILDI ---
                    # Boshqa thread'dan xavfsiz murojaat qilish uchun avvaldan olingan sikldan foydalanamiz
                    asyncio.run_coroutine_threadsafe(
                        safe_edit_message(processing_message, progress_text),
                        loop
                    )
                    last_update = current_time

        ydl_opts = {
            'format': 'best[ext=mp4][height<=720]/bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': '%(title)s - %(id)s.%(ext)s', 'noplaylist': True,
            'cookiefile': cookie_file, 'postprocessor_args': ['-movflags', '+faststart'],
            'retries': 5, 'progress_hooks': [progress_hook],
            'socket_timeout': 30, 'max_filesize': 1024 * 1024 * 1024, # 1 GB CHEKLOV
            'nopart': True, 'no_warnings': True,
        }

        with YoutubeDL(ydl_opts) as ydl:
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            file_path = ydl.prepare_filename(info_dict)
            # --- XATOLIK TUZATILDI ---
            # Ushbu 'if' bloki 'with' bloki ichida to'g'ri joylashtirildi.
            if not file_path or not os.path.exists(file_path):
                await safe_edit_message(processing_message, "❌ Kechirasiz, videoni yuklab bo'lmadi.")
                return

        # --- TELEGRAM'GA YUBORISH JARAYONINI KO'RSATISH ---
        async def upload_progress(current, total):
            percentage = current * 100 / total
            await safe_edit_message(processing_message, f"✅Yuborilmoqda...\n{percentage:.1f}%")

        await client.send_file(
            chat_id, file_path, caption="Yordamim tekkanidan xursandman, @Allsavervide0bot!",
            progress_callback=upload_progress
        )
        await client.delete_messages(chat_id, processing_message)

        description = info_dict.get('description') if "instagram.com" in url.lower() else None
        if description and description.strip():
            for i in range(0, len(description), 4096):
                await client.send_message(chat_id, f"{description[i:i+4096]}\n\n "@Allsavervide0bot")

    except Exception as e:
        logging.error(f"Xatolik yuz berdi: {e}")
        error_text = str(e)
        if "File is larger than max-filesize" in error_text:
            error_text = "Video hajmi 1 GB dan katta. Iltimos, kichikroq hajmdagi videoni tanlang."
        elif "Sign in to confirm" in error_text or "Login required" in error_text:
            error_text = "Cookie'lar eskirgan yoki noto'g'ri. Iltimos, ularni yangilang."

        error_full_text = f"❌ Kechirasiz, xatolik yuz berdi.\n\n{error_text}"
        await safe_edit_message(processing_message, error_full_text)
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)


# --- ASOSIY QAYTA ISHLOVCHI: XABAR KELGANDA ISHLAYDI ---
@client.on(events.NewMessage(pattern=r'https?://\S+'))
async def main_handler(event):
    url = event.text
    if "list=" in url or "/playlist?" in url:
        playlist_msg = await event.reply("⏳ Playlist...")
        cookie_file = get_cookie_for_url(url)
        try:
            ydl_opts = {'extract_flat': True, 'playlistend': 10, 'cookiefile': cookie_file}
            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=False)
            buttons = []
            entries = info_dict.get('entries', [])
            for entry in entries:
                video_id = entry.get('id'); title = entry.get('title', 'Nomsiz video')
                button_text = title[:50] + '…' if len(title) > 50 else title
                buttons.append([Button.inline(button_text, data=f"dl_{video_id}")])
            if not buttons:
                await playlist_msg.edit("❌ Playlist'dan videolarni olib bo'lmadi."); return
            await playlist_msg.edit(f"'{info_dict.get('title')}' playlisti topildi.\n\nQuyidagi videolardan birini tanlang (birinchi {len(entries)} tasi):", buttons=buttons)
        except Exception as e:
            await playlist_msg.edit(f"❌ Playlist'ni o'qishda xatolik: {e}")
        finally:
            if cookie_file and os.path.exists(cookie_file):
                os.remove(cookie_file)
    else:
        await download_and_send_video(event, url)


# --- TUGMA QAYTA ISHLOVCHISI ---
@client.on(events.CallbackQuery(pattern=b"dl_"))
async def button_handler(event):
    video_id = event.data.decode('utf-8').split('_', 1)[1]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    await download_and_send_video(event, video_url)


# --- /START BUYRUG'I UCHUN QAYTA ISHLOVCHI ---
@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply("Assalomu alaykum! Video yuklash uchun YouTube yoki Instagram havolasini yuboring.")


# --- ASOSIY ISHGA TUSHIRISH FUNKSIYASI ---
async def main():
    await client.start(bot_token=BOT_TOKEN)
    print("Bot muvaffaqiyatli ishga tushdi...")
    await client.run_until_disconnected()

# --- XATOLIK TUZATILDI ---
# Skript to'g'ri ishga tushishi uchun 'if name == 'main':' 'if __name__ == '__main__':'-ga o'zgartirildi
if __name__ == '__main__':
    asyncio.run(main())

