# bot.py

import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
# Yordamchi funksiyani utils.py dan import qilamiz
from utils import download_media

TOKEN = os.getenv("BOT_TOKEN")
MAX_FILE_SIZE = 49 * 1024 * 1024

# Jurnallashni (logging) sozlash
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Bot Buyruqlari (Handlers) ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start buyrug'i uchun javob."""
    user = update.effective_user
    await update.message.reply_html(
        f"Assalomu alaykum, {user.mention_html()}!\n\n"
        "Men YouTube, Instagram, TikTok va Facebook'dan videolar yuklay olaman.\n\n"
        "Shunchaki video havolasini yuboring. 🎬\n\n"
        "YouTubedan audio (mp3) yuklash uchun esa quyidagi formatdan foydalaning:\n"
        "<code>/audio &lt;youtube_havolasi&gt;</code>"
    )


async def process_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Havola kelganda uni qayta ishlaydigan asosiy funksiya.
    """
    is_audio = update.message.text.startswith('/audio')

    if is_audio:
        if not context.args:
            await update.message.reply_text("Iltimos, YouTube havolasini yuboring.\nMasalan: /audio https://youtu.be/...")
            return
        url = context.args[0]
    else:
        url = update.message.text

    supported_sites = ["youtube.com", "youtu.be",
                       "tiktok.com", "instagram.com", "facebook.com"]
    if not any(site in url for site in supported_sites):
        await update.message.reply_text("❌ Kechirasiz, faqat YouTube, TikTok, Instagram yoki Facebook havolalarini qo'llab-quvvatlayman.")
        return

    if is_audio and not ("youtube.com" in url or "youtu.be" in url):
        await update.message.reply_text("❌ Audio yuklash faqat YouTube uchun mavjud.")
        return

    status_message = None
    file_path = None
    try:
        media_type = "🎵 Audio" if is_audio else "🎬 Video"
        status_message = await update.message.reply_text(f"⏳ {media_type} yuklanmoqda, iltimos kuting...")

        download_dir = f"downloads/{update.effective_chat.id}"
        # `download_media` funksiyasini chaqirish
        file_path = download_media(
            url, is_audio, download_dir, max_size=MAX_FILE_SIZE)

        await status_message.edit_text("📤 Fayl yuborilmoqda...")

        with open(file_path, 'rb') as media_file:
            if is_audio:
                await update.message.reply_audio(media_file, read_timeout=120, write_timeout=120)
            else:
                await update.message.reply_video(media_file, read_timeout=120, write_timeout=120)

        await status_message.delete()
    except Exception as e:
        logger.error(f"Jarayonda umumiy xato: {e}")
        error_text = f"❌ Xatolik yuz berdi: {e}"
        if status_message:
            await status_message.edit_text(error_text)
        else:
            await update.message.reply_text(error_text)
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Vaqtinchalik fayl o'chirildi: {file_path}")


def main():
    """Botni ishga tushirish."""
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("audio", process_link))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, process_link))

    logger.info("✅ Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
