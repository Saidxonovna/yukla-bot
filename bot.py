import logging
import os
import time
import asyncio
import re
from yt_dlp import YoutubeDL

from telethon import TelegramClient, events, Button

# Log yozishni sozlash
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)

# --- Railway'ning "Variables" bo'limidan olinadi ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
# IKKITA ALOHIDA COOKIE O'ZGARUVCHISI
YOUTUBE_COOKIE = os.environ.get("YOUTUBE_COOKIE")
INSTAGRAM_COOKIE = os.environ.get("INSTAGRAM_COOKIE")


# Telethon klientini yaratish
client = TelegramClient('bot_session', API_ID, API_HASH)


# --- YORDAMCHI FUNKSIYA: HAVOLAGA QARAB TO'G'RI COOKIE'NI TANLAYDI ---
def get_cookie_for_url(url):
    """Havolani analiz qilib, mos cookie faylini yaratadi va nomini qaytaradi."""
    cookie_file_path = None
    cookie_data = None
    
    # URL'ni kichik harflarga o'tkazib tekshirish
    lower_url = url.lower()

    if 'youtube.com' in lower_url or 'youtu.be' in lower_url:
        cookie_data = YOUTUBE_COOKIE
        cookie_file_path = 'youtube_cookies.txt'
    elif 'instagram.com' in lower_url:
        cookie_data = INSTAGRAM_COOKIE
        cookie_file_path = 'instagram_cookies.txt'
        
    if cookie_data and cookie_file_path:
        # Faylga yozish
        with open(cookie_file_path, 'w', encoding='utf-8') as f:
            f.write(cookie_data)
        return cookie_file_path
    
    # Agar mos cookie topilmasa, None qaytaradi
    return None


# --- YUKLASH FUNKSIYASI (barcha logikani o'z ichiga oladi) ---
async def download_and_send_video(event, url):
    chat_id = event.chat_id
    processing_message = None
    cookie_file = None
    file_path = None

    try:
        # Xabarni tahrirlash yoki yangi xabar yuborish
        if hasattr(event, 'edit'):
            processing_message = await event.edit("⏳ Jarayon boshlandi...")
        else:
            processing_message = await event.reply("⏳ Jarayon boshlandi...")

        # URL uchun mos cookie faylini olish
        cookie_file = get_cookie_for_url(url)
        if cookie_file:
            logging.info(f"{url} uchun {cookie_file} ishlatilmoqda.")
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': '%(title)s - %(id)s.%(ext)s',
            'noplaylist': True,
            'cookiefile': cookie_file,  # DINAMIK RAVISHDA COOKIE'NI ISHLATISH
            'postprocessor_args': ['-movflags', '+faststart'],
            'retries': 5,
        }

        with YoutubeDL(ydl_opts) as ydl:
            await client.edit_message(processing_message, "📥 Video ma'lumotlari olinmoqda...")
            loop = asyncio.get_event_loop()
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            file_path = ydl.prepare_filename(info_dict)

        if not file_path or not os.path.exists(file_path):
            await client.edit_message(processing_message, "❌ Kechirasiz, videoni yuklab bo'lmadi.")
            return

        await client.edit_message(processing_message, "📤Yuborilmoqda...")
        
        description = info_dict.get('description') if "instagram.com" in url.lower() else None

        await client.send_file(
            chat_id,
            file_path,
            caption="Yordamim tekkanidan xursandman, @Allsavervide0bot!"
        )
        await client.delete_messages(chat_id, processing_message)

        if description and description.strip():
            for i in range(0, len(description), 4096):
                await client.send_message(chat_id, f"**Video tavsifi:**\n\n{description[i:i+4096]}")

    except Exception as e:
        logging.error(f"Xatolik yuz berdi: {e}")
        error_text = str(e)
        if "Sign in to confirm" in error_text or "Login required" in error_text:
             error_text = "Cookie'lar eskirgan yoki noto'g'ri. Iltimos, ularni yangilang."
        await client.edit_message(processing_message, f"❌ Kechirasiz, xatolik yuz berdi.\n\n`{error_text}`")
    finally:
        # Vaqtinchalik fayllarni o'chirish
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)


# --- ASOSIY HANDLER: XABAR KELGANDA ISHLAYDI ---
@client.on(events.NewMessage(pattern=r'https?://\S+'))
async def main_handler(event):
    url = event.text
    
    if "list=" in url or "/playlist?" in url:
        # Playlist logikasi
        playlist_msg = await event.reply("⏳ Playlist tahlil qilinmoqda...")
        cookie_file = get_cookie_for_url(url) # Playlist uchun ham cookie
        try:
            ydl_opts = {'extract_flat': True, 'playlistend': 10, 'cookiefile': cookie_file}
            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=False)
            buttons = []
            entries = info_dict.get('entries', [])
            for entry in entries:
                video_id = entry.get('id')
                title = entry.get('title', 'Nomsiz video')
                button_text = title[:50] + '…' if len(title) > 50 else title
                buttons.append([Button.inline(button_text, data=f"dl_{video_id}")])
            
            if not buttons:
                await playlist_msg.edit("❌ Playlist'dan videolarni olib bo'lmadi."); return
            
            await playlist_msg.edit(f"**'{info_dict.get('title')}'** playlisti topildi.\n\nQuyidagi videolardan birini tanlang (birinchi {len(entries)} tasi):", buttons=buttons)
        except Exception as e:
            await playlist_msg.edit(f"❌ Playlist'ni o'qishda xatolik: {e}")
        finally:
             if cookie_file and os.path.exists(cookie_file):
                os.remove(cookie_file) # Playlist uchun ham cookieni o'chirish
    else:
        # Bitta video yuklash
        await download_and_send_video(event, url)


# --- KNOPKA HANDLERI ---
@client.on(events.CallbackQuery(pattern=b"dl_"))
async def button_handler(event):
    video_id = event.data.decode('utf-8').split('_', 1)[1]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    await download_and_send_video(event, video_url)


# --- /START HANDLERI ---
@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply("Assalomu alaykum! Video yuklash uchun YouTube yoki Instagram havolasini yuboring.")


# --- ASOSIY ISHGA TUSHIRISH FUNKSIYASI ---
async def main():
    await client.start(bot_token=BOT_TOKEN)
    print("Bot muvaffaqiyatli ishga tushdi...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
