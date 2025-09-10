import logging
import os
import asyncio
import re
import httpx
from yt_dlp import YoutubeDL

from telethon import TelegramClient, events, Button
from telethon.errors import MessageNotModifiedError

# Setup logging
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)

# --- Get environment variables from Railway ---
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
except (ValueError, TypeError):
    logging.critical("API_ID, API_HASH, or BOT_TOKEN not found or in wrong format!")
    exit(1)

# Create the Telethon client
client = TelegramClient('bot_session', API_ID, API_HASH)

# --- Helper Function ---
async def safe_edit_message(message, text, **kwargs):
    """Safely edits a message, ignoring 'MessageNotModifiedError'."""
    if not message or not hasattr(message, 'text') or message.text == text:
        return
    try:
        await message.edit(text, **kwargs)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        logging.warning(f"Unexpected error while editing message: {e}")

# --- Main Download Function (Hybrid Method) ---
async def hybrid_download(event, url):
    chat_id = event.chat_id
    processing_message = None
    info_dict = None

    try:
        if isinstance(event, events.CallbackQuery.Event):
            processing_message = await event.edit("⏳ Processing link...")
        else:
            processing_message = await event.reply("⏳ Processing link...")
    except Exception as e:
        logging.error(f"Error sending initial message: {e}")
        return

    # --- STEP 1: Get metadata with yt-dlp (no download) ---
    try:
        await safe_edit_message(processing_message, "ℹ️ Fetching video info...")
        ydl_opts_info = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True, # This is crucial: only get info
        }
        with YoutubeDL(ydl_opts_info) as ydl:
            loop = asyncio.get_running_loop()
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
    except Exception as e:
        logging.warning(f"Could not get metadata with yt-dlp: {e}")
        # If yt-dlp fails, we can still proceed with Cobalt, just without a title/description
        await safe_edit_message(processing_message, "⚠️ Couldn't get video details, proceeding with download...")

    # --- STEP 2: Get video stream with Cobalt API ---
    try:
        await safe_edit_message(processing_message, "🌎 Requesting video from download service...")
        api_url = "https://co.wuk.sh/api/json"
        payload = {"url": url, "vQuality": "720"}
        
        async with httpx.AsyncClient(timeout=90) as client_http:
            response = await client_http.post(api_url, json=payload, headers={"Accept": "application/json"})
            response.raise_for_status()
            data = response.json()

        if data.get("status") == "stream":
            video_url = data["url"]
            video_title = info_dict.get('title', 'Downloaded Video') if info_dict else "Downloaded Video"
            description = info_dict.get('description') if info_dict else None
            
            await safe_edit_message(processing_message, "✅ Video found, sending to Telegram...")

            # Telethon can send a file directly from a URL
            await client.send_file(
                chat_id,
                file=video_url,
                caption=f"**{video_title}**\n\nDownloaded via @Allsavervide0bot"
            )

            # Send the description if it exists
            if description and description.strip():
                logging.info(f"Description found, sending {len(description)} chars...")
                for i in range(0, len(description), 4096):
                    chunk = description[i:i+4096]
                    await client.send_message(chat_id, f"**📝 Video Description:**\n\n{chunk}")
            
            await processing_message.delete()
        else:
            error_text = data.get('text', 'Unknown error. This link may not be downloadable.')
            await safe_edit_message(processing_message, f"❌ Error: {error_text}")

    except httpx.HTTPStatusError:
        await safe_edit_message(processing_message, "❌ The download service is temporarily unavailable. Please try again later.")
    except httpx.ReadTimeout:
        await safe_edit_message(processing_message, "❌ The download timed out, possibly because the video is too large.")
    except Exception as e:
        logging.error(f"A general error occurred: {e}", exc_info=True)
        await safe_edit_message(processing_message, "❌ Sorry, an unexpected error occurred.")


# --- Event Handlers ---
@client.on(events.NewMessage(pattern=re.compile(r'https?://\S+')))
async def main_handler(event):
    url_match = re.search(r'https?://\S+', event.text)
    if not url_match: return
    url = url_match.group(0)
    
    # Playlists are not supported by the Cobalt stream, so we'll block them
    if "list=" in url or "/playlist?" in url:
        await event.reply("Sorry, downloading playlists is not supported. Please send a link to a single video.")
        return

    await hybrid_download(event, url)

@client.on(events.CallbackQuery())
async def button_handler(event):
    # Buttons are not used in this version, so we provide a generic response
    await event.answer("This button is outdated.", alert=True)

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply(
        "Hello! I can download videos from YouTube and Instagram.\n\n"
        "Just send me a video link."
    )

# --- Main Function to Run the Bot ---
async def main():
    await client.start(bot_token=BOT_TOKEN)
    logging.info("Bot started successfully with the hybrid method...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
