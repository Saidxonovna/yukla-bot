import os
import re
import asyncio
import logging
import uuid
import time
from functools import lru_cache

from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeFilename
from telethon.errors import MessageNotModifiedError
from yt_dlp import YoutubeDL

# Logger sozlamalari
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)

# --- Railway'ning "Variables" bo'limidan olinadigan ma'lumotlar ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUTUBE_COOKIE = os.environ.get("YOUTUBE_COOKIE")
INSTAGRAM_COOKIE = os.environ.get("INSTAGRAM_COOKIE")

# Telethon klientini yaratish
client = TelegramClient('bot_session', API_ID, API_HASH)

# Global navbat va vaqtinchalik URL saqlash joyi
download_queue = asyncio.Queue()
temp_urls = {}
playlist_info_cache = {}

# Qo'llab-quvvatlanadigan URLlar uchun regex
YOUTUBE_RE = re.compile(r'https?://(?:www\.)?(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/|playlist\?list=)).*')
INSTAGRAM_RE = re.compile(r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[a-zA-Z0-9_-]+')

# --- YORDAMCHI FUNKSIYALAR ---

@lru_cache(maxsize=128)
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

async def download_and_send(event, url, ydl_opts):
    """Videoni yuklaydi va foydalanuvchiga yuboradi."""
    chat_id = event.chat_id
    processing_message = None
    cookie_file = None
    file_path = None
    loop = asyncio.get_running_loop()

    try:
        if isinstance(event, events.CallbackQuery.Event):
            processing_message = await event.edit("⏳ Yuklab olish jarayoni boshlanmoqda...")
        else:
            processing_message = await event.reply("⏳ Yuklab olish jarayoni boshlanmoqda...")
        
        # Cookie sozlamalari
        cookie_file = get_cookie_for_url(url)
        if cookie_file and os.path.exists(cookie_file):
            ydl_opts['cookiefile'] = cookie_file
        
        # Yuklash jarayonini kuzatish
        last_update = 0
        def progress_hook(d):
            nonlocal last_update
            if d['status'] == 'downloading':
                current_time = time.time()
                if current_time - last_update > 3:
                    percentage = d['_percent_str']
                    speed = d['_speed_str']
                    eta = d['_eta_str']
                    progress_text = f"📥 Yuklanmoqda...\n\n{percentage} | {speed} | {eta}"
                    asyncio.run_coroutine_threadsafe(safe_edit_message(processing_message, progress_text), loop)
                    last_update = current_time

        ydl_opts['progress_hooks'] = [progress_hook]

        with YoutubeDL(ydl_opts) as ydl:
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            file_path = ydl.prepare_filename(info_dict)
            
            if not file_path or not os.path.exists(file_path):
                await safe_edit_message(processing_message, "❌ Kechirasiz, videoni yuklab bo'lmadi.")
                return

        await safe_edit_message(processing_message, "✅ Yuklab olindi. Endi videoni yuboraman...")
        
        # Sarlavha (caption) yaratish
        title = info_dict.get('title', 'Nomsiz video')
        uploader = info_dict.get('uploader', 'Noma\'lum manba')
        caption_text = f"**{title}**\n\nManba: {uploader}\n\nYuklab berildi: @Allsavervide0bot"
        
        # Yuborish jarayonini kuzatish
        async def upload_progress(current, total):
            percentage = current * 100 / total
            await safe_edit_message(processing_message, f"✅ Yuborilmoqda...\n{percentage:.1f}%")

        await client.send_file(
            chat_id,
            file_path,
            caption=caption_text,
            attributes=[DocumentAttributeFilename(file_path.split('/')[-1])],
            parse_mode='markdown',
            progress_callback=upload_progress
        )
        await client.delete_messages(chat_id, processing_message)
        
        description = info_dict.get('description') if "instagram.com" in url.lower() else None
        if description and description.strip():
            for i in range(0, len(description), 4096):
                await client.send_message(chat_id, f"{description[i:i+4096]}\n\n @Allsavervide0bot")

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

async def worker():
    """Navbatdan vazifalarni olib, ularni qayta ishlaydi."""
    while True:
        event, url, ydl_opts = await download_queue.get()
        try:
            await download_and_send(event, url, ydl_opts)
        except Exception as e:
            logging.error(f"Worker'da xatolik: {e}")
            try:
                if isinstance(event, events.CallbackQuery.Event):
                    await event.edit("❌ Yuklashda kutilmagan xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
                else:
                    await event.reply("❌ Yuklashda kutilmagan xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
            except Exception as e_reply:
                logging.error(f"Xabar yuborishda xatolik: {e_reply}")
        finally:
            download_queue.task_done()

# --- HANDLERLAR ---

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply("Assalomu alaykum! Video yuklash uchun YouTube yoki Instagram havolasini yuboring.")

@client.on(events.NewMessage(pattern=r'https?://\S+'))
async def main_handler(event):
    url = event.text.strip()
    
    # URLni tekshirish
    if not YOUTUBE_RE.match(url) and not INSTAGRAM_RE.match(url):
        return await event.reply("Kechirasiz, men faqat YouTube va Instagram havolalarini yuklab olaman.")
        
    try:
        # Playlistni aniqlash
        if 'list=' in url or '/playlist?' in url:
            
            # Playlist ma'lumotlarini keshdan olish
            if url in playlist_info_cache and time.time() - playlist_info_cache[url]['timestamp'] < 3600:
                info_dict = playlist_info_cache[url]['data']
            else:
                await event.reply("🔗 Bu playlist havolasi. Hozir videolarni yuklab olish uchun ro'yxat tuzaman, iltimos kuting...")
                cookie_file = get_cookie_for_url(url)
                ydl_opts = {'extract_flat': True, 'playlistend': 10, 'cookiefile': cookie_file}
                with YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
                if cookie_file and os.path.exists(cookie_file):
                    os.remove(cookie_file)
                playlist_info_cache[url] = {'data': info_dict, 'timestamp': time.time()}

            playlist_title = info_dict.get('title', 'Nomsiz playlist')
            entries = info_dict.get('entries', [])
            
            if not entries:
                return await event.reply("❌ Bu playlistda video topilmadi.")

            buttons = []
            for i, entry in enumerate(entries):
                if i >= 10: break
                video_id = entry['id']
                video_title = entry.get('title', f"Video {i+1}")
                unique_id = str(uuid.uuid4())
                temp_urls[unique_id] = f"https://www.youtube.com/watch?v={video_id}"
                
                button_text = video_title[:50] + '…' if len(video_title) > 50 else video_title
                buttons.append([Button.inline(button_text, data=f"video_{unique_id}")])
            
            await client.send_message(
                event.chat_id,
                f"**{playlist_title}** playlistidan yuklamoqchi bo'lgan videoni tanlang (birinchi {len(buttons)} ta):\n\n",
                buttons=buttons,
                parse_mode='markdown'
            )
        # --- BU YERDA O'ZGARISH AMALGA OSHIRILDI ---
        # Instagram havolasini tekshirish
        elif INSTAGRAM_RE.match(url):
            # Instagram uchun standart sozlamalar
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
                'outtmpl': 'downloads/%(title)s.%(ext)s',
                'noplaylist': True,
                'postprocessor_args': ['-movflags', '+faststart'],
                'retries': 5, 'socket_timeout': 30,
                'max_filesize': 1024 * 1024 * 1024,
            }
            # To'g'ridan-to'g'ri navbatga qo'shish
            await download_queue.put((event, url, ydl_opts))
            await event.reply("✅ So'rovingiz qabul qilindi va navbatga qo'yildi.")
            
        else: # Qolgan barcha holatlar, ya'ni oddiy YouTube videolari uchun
            unique_id = str(uuid.uuid4())
            temp_urls[unique_id] = url
            
            buttons = [
                [Button.inline("🎥 Video (720p)", data=f"quality_720_{unique_id}")],
                [Button.inline("🎥 Video (480p)", data=f"quality_480_{unique_id}")],
                [Button.inline("🎵 Faqat audio (MP3)", data=f"quality_audio_{unique_id}")]
            ]
            await event.reply("Yuklab olish formatini tanlang:", buttons=buttons)

    except Exception as e:
        logging.error(f"Main handlerda xatolik: {e}", exc_info=True)
        await event.reply("❌ Havolani tahlil qilishda xatolik yuz berdi. Iltimos, boshqa havolani urinib ko'ring.")

# CallbackQuery uchun handler
@client.on(events.CallbackQuery(pattern=b'quality_'))
async def quality_handler(event):
    await event.answer("So'rovingiz qabul qilindi va navbatga qo'yildi.")
    
    data = event.data.decode('utf-8').split('_', 2)
    quality = data[1]
    unique_id = data[2]
    url = temp_urls.get(unique_id)

    if not url:
        return await event.reply("❌ Kechirasiz, havolaning muddati tugadi yoki topilmadi. Iltimos, havolani qaytadan yuboring.")
    
    del temp_urls[unique_id]

    ydl_opts = {
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'noplaylist': True,
        'postprocessor_args': ['-movflags', '+faststart'],
        'retries': 5, 'socket_timeout': 30,
        'max_filesize': 1024 * 1024 * 1024,
    }

    if quality == "audio":
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else: # Masalan, '720' yoki '480'
        ydl_opts['format'] = f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4][height<={quality}]'
    
    await download_queue.put((event, url, ydl_opts))

@client.on(events.CallbackQuery(pattern=b"video_"))
async def playlist_video_handler(event):
    await event.answer("So'rovingiz qabul qilindi va navbatga qo'yildi.")
    
    data = event.data.decode('utf-8').split('_', 1)
    unique_id = data[1]
    url = temp_urls.get(unique_id)
    
    if not url:
        return await event.reply("❌ Kechirasiz, havolaning muddati tugadi yoki topilmadi. Iltimos, havolani qaytadan yuboring.")
    
    del temp_urls[unique_id]

    ydl_opts = {
        'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'noplaylist': True,
        'postprocessor_args': ['-movflags', '+faststart'],
        'retries': 5, 'socket_timeout': 30,
        'max_filesize': 1024 * 1024 * 1024,
    }
    
    await download_queue.put((event, url, ydl_opts))


async def main():
    """Asosiy ishga tushirish funksiyasi."""
    os.makedirs('downloads', exist_ok=True)
    
    print("Bot muvaffaqiyatli ishga tushdi...")
    logging.info("Bot ishga tushdi.")
    
    # Worker'larni fon rejimida ishga tushirish
    num_workers = 3
    for _ in range(num_workers):
        asyncio.create_task(worker())
    
    await client.start(bot_token=BOT_TOKEN)
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot o'chirildi.")
# ... yuqoridagi kodlar o'zgarmasdan qoladi ...

# Global foydalanuvchi lock-larini saqlash uchun lug'at
user_locks = {}
lock_timeout = 300 # 5 daqiqa

# ... boshqa yordamchi funksiyalar va handlerlar ...

# --- ASOSIY QAYTA ISHLOVCHI: XABAR KELGANDA ISHLAYDI ---
@client.on(events.NewMessage(pattern=r'https?://\S+'))
async def main_handler(event):
    user_id = event.sender_id
    url = event.text.strip()
    
    # Foydalanuvchi uchun Lock ob'ektini yaratish yoki mavjudini olish
    if user_id not in user_locks or user_locks[user_id]['lock'].locked():
        # Oxirgi so'rovdan beri 5 daqiqa o'tgan bo'lsa, lockni bo'shatish
        if user_id in user_locks and time.time() - user_locks[user_id]['timestamp'] > lock_timeout:
            user_locks[user_id]['lock'].release()
            del user_locks[user_id]
        else:
            await event.reply("⚠️ Sizning oldingi so'rovingiz hali tugamadi. Iltimos, uning yakunlanishini kuting.")
            return

    # Lockni band qilish
    user_locks[user_id] = {'lock': asyncio.Lock(), 'timestamp': time.time()}
    await user_locks[user_id]['lock'].acquire()

    try:
        # URLni tekshirish
        if not YOUTUBE_RE.match(url) and not INSTAGRAM_RE.match(url):
            return await event.reply("Kechirasiz, men faqat YouTube va Instagram havolalarini yuklab olaman.")
            
        # ... qolgan kodlar (playlist va video logikasi) ...
        
        # Original koddagi kabi, video hajmi yoki turiga qarab navbatga qo'shish
        # ...
        
    except Exception as e:
        logging.error(f"Main handlerda xatolik: {e}", exc_info=True)
        await event.reply("❌ Havolani tahlil qilishda xatolik yuz berdi. Iltimos, boshqa havolani urinib ko'ring.")
    finally:
        # Jarayon tugagandan so'ng, Lockni bo'shatish
        if user_id in user_locks and user_locks[user_id]['lock'].locked():
            user_locks[user_id]['lock'].release()
            # Lockni keyinroq tozalash uchun qoldirish mumkin, hozircha o'chiramiz
            # del user_locks[user_id]
