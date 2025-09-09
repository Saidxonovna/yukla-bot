import os
import logging
import yt_dlp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# --- Sozlamalar ---
TOKEN = os.getenv("BOT_TOKEN")
# 50 MB lik cheklovni to'g'ridan-to'g'ri o'rnatamiz
MAX_FILE_SIZE = 49 * 1024 * 1024

# Jurnallashni (logging) sozlash
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Cookie faylini sozlash (Railway uchun) ---
COOKIE_FILE = 'cookies.txt'
cookie_data_from_env = os.getenv('COOKIE_DATA')
if cookie_data_from_env:
    with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
        f.write(cookie_data_from_env)
    logger.info(f"'{COOKIE_FILE}' fayli server o'zgaruvchisidan yaratildi.")


# --- Asosiy yuklovchi funksiya ---
def download_media(url: str, is_audio: bool):
    """Berilgan havoladan media yuklaydi va fayl yo'lini qaytaradi."""
    download_dir = "downloads"
    os.makedirs(download_dir, exist_ok=True)

    ydl_opts = {
        'logger': logger,
        'outtmpl': os.path.join(download_dir, '%(id)s.%(ext)s'),
        'noplaylist': True,
        'max_filesize': MAX_FILE_SIZE,  # Cheklovni shu yerda ishlatamiz
    }

    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE

    if is_audio:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
        })
    else:
        ydl_opts.update({
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
        })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise Exception("Ma'lumot topilmadi.")

        # Yuklangan fayl nomini topish
        downloaded_file = ydl.prepare_filename(info)

        # Agar post-processing bo'lsa, fayl kengaytmasi o'zgarishi mumkin
        if is_audio:
            base, _ = os.path.splitext(downloaded_file)
            final_file = base + '.mp3'
        else:
            base, _ = os.path.splitext(downloaded_file)
            final_file = base + '.mp4'

        if os.path.exists(final_file):
            return final_file
        # Agar aniq nom bilan topilmasa, ID bo'yicha qidiramiz
        else:
            video_id = info.get('id')
            found_files = [f for f in os.listdir(
                download_dir) if f.startswith(video_id)]
            if found_files:
                return os.path.join(download_dir, found_files[0])

    raise Exception("Yuklangan faylni topib bo'lmadi.")


# --- Telegram uchun funksiyalar (Handlers) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start buyrug'i uchun javob."""
    user = update.effective_user
    await update.message.reply_html(
        f"Assalomu alaykum, {user.mention_html()}!\n\n"
        "Menga YouTube, Instagram, TikTok kabi saytlardan havola yuboring, men uni sizga yuklab beraman.\n\n"
        "Faqat 50 MB gacha bo'lgan fayllarni yuklay olaman."
    )


async def process_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Havolani qayta ishlaydigan asosiy funksiya."""
    url = update.message.text
    status_message = await update.message.reply_text("⏳ Yuklanmoqda, iltimos kuting...")
    file_path = None

    try:
        # Hozircha faqat video yuklaymiz (audio uchun /audio buyrug'ini olib tashladik)
        file_path = download_media(url, is_audio=False)

        await status_message.edit_text("📤 Fayl yuborilmoqda...")
        with open(file_path, 'rb') as media_file:
            await update.message.reply_video(media_file, read_timeout=120)

        await status_message.delete()

    except Exception as e:
        logger.error(f"Xatolik: {e}")
        # Foydalanuvchiga tushunarliroq xabar beramiz
        if "File is larger than the maximum" in str(e):
            error_text = "❌ Xatolik: Fayl hajmi 50 MB dan katta."
        else:
            error_text = f"❌ Xatolik yuz berdi: {e}"
        await status_message.edit_text(error_text)

    finally:
        # Vaqtinchalik faylni o'chirish
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Vaqtinchalik fayl o'chirildi: {file_path}")


# --- Botni ishga tushirish ---
def main():
    """Botni ishga tushirish."""
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, process_link))

    logger.info("✅ Sodda bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
