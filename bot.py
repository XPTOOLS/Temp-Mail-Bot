import os
import re
import time
import random
import string
import hashlib
import requests
import asyncio
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.enums import ParseMode, ChatType
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, CallbackQuery, Message
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timedelta
import io
import logging
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
from aiohttp import web  # <-- Add this import

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('temp_mail_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
CONFIG = {
    'API_ID': int(os.getenv('API_ID', '25753873')),
    'API_HASH': os.getenv('API_HASH', '3a5cdc2079cd76af80586102bd9761e2'),
    'BOT_TOKEN': os.getenv('TELEGRAM_BOT_TOKEN', '7887824561:AAGmmuNMcD_H4JtRYUj3tuMQ34qJ0sn_9AE'),
    'ADMIN_IDS': [int(id.strip()) for id in os.getenv('ADMIN_IDS', '5962658076').split(',')],
    'MONGO_URI': os.getenv('MONGO_URI', 'mongodb+srv://anonymousguywas:12345Trials@cluster0.t4nmrtp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0'),
    'BASE_URL': 'https://api.mail.tm',
    'HEADERS': {
        "Content-Type": "application/json",
        "Accept": "application/json"
    },
    'MAX_MESSAGE_LENGTH': 4000,
    'WELCOME_IMAGE': "https://envs.sh/Hss.jpg",
    'REQUIRED_CHANNELS': os.getenv('REQUIRED_CHANNELS', 'megahubbots,Freenethubz,smmserviceslogs').split(','),
    'CHANNEL_LINKS': os.getenv('CHANNEL_LINKS', 'https://t.me/megahubbots, https://t.me/Freenethubz, https://t.me/smmserviceslogs').split(','),
    'CHANNEL_BUTTON_NAMES': os.getenv('CHANNEL_BUTTON_NAMES', '🤖 BOTS UPDATE,📢 MAIN CHANNEL,📝 LOGS CHANNEL').split(',')
}

# Notification channel
NOTIFICATION_CHANNEL = os.getenv('NOTIFICATION_CHANNEL', '@smmserviceslogs')

# Initialize MongoDB
mongo_client = MongoClient(CONFIG['MONGO_URI'])
db = mongo_client['temp_mail_bot']
users_collection = db['users']
stats_collection = db['stats']
broadcasts_collection = db['broadcasts']

# Initialize bot
bot = Client(
    "bot_session",
    api_id=CONFIG['API_ID'],
    api_hash=CONFIG['API_HASH'],
    bot_token=CONFIG['BOT_TOKEN'],
    workers=1000,
    parse_mode=ParseMode.MARKDOWN
)

token_map = {}
user_tokens = {}

# ------------------------ Database Functions ------------------------

async def register_user(user_id: int, username: str = None):
    """Register or update user in database"""
    user_data = {
        'user_id': user_id,
        'username': username,
        'join_date': datetime.now(),
        'email_count': 0,
        'message_count': 0,
        'in_channels': False
    }
    users_collection.update_one(
        {'user_id': user_id},
        {
            '$setOnInsert': user_data,
            '$set': {'last_active': datetime.now()}
        },
        upsert=True
    )

async def increment_stat(counter_name: str, value: int = 1):
    """Increment statistics counter"""
    stats_collection.update_one(
        {'name': 'statistics'},
        {'$inc': {counter_name: value}},
        upsert=True
    )

async def get_stats():
    """Get all statistics"""
    return stats_collection.find_one({'name': 'statistics'}) or {
        'total_users': 0,
        'total_emails': 0,
        'total_messages': 0
    }

async def get_all_users():
    """Get all user IDs for broadcasting"""
    return [user['user_id'] for user in users_collection.find({}, {'user_id': 1})]

async def log_broadcast(admin_id: int, message: str, recipients: int):
    """Log broadcast message"""
    broadcasts_collection.insert_one({
        'admin_id': admin_id,
        'message': message,
        'date': datetime.now(),
        'recipients': recipients
    })

# ------------------------ Notification Functions ------------------------

async def get_profile_photo(client, user_id):
    """Fetch user or bot profile picture as circular RGBA image"""
    try:
        chat = await client.get_chat(user_id)
        if not chat.photo:
            raise Exception("No profile photo")

        # Download the small version of the profile picture
        photo_path = await client.download_media(chat.photo.big_file_id, in_memory=True)
        original_img = Image.open(photo_path).convert("RGB")

        # Create circular crop
        size = (500, 500)
        mask = Image.new('L', size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size[0], size[1]), fill=255)

        img = ImageOps.fit(original_img, size, method=Image.LANCZOS)
        img.putalpha(mask)
        return img

    except Exception as e:
        logger.warning(f"Using default profile photo: {e}")
        # Same fallback logic as before
        img = Image.new("RGBA", (500, 500), (70, 70, 70, 255))
        draw = ImageDraw.Draw(img)

        try:
            user = await client.get_users(user_id)
            initial = (user.first_name or str(user_id))[0].upper()
            font = ImageFont.truetype("arialbd.ttf", 200) if os.path.exists("arialbd.ttf") else ImageFont.load_default()
            draw.ellipse((0, 0, 500, 500), fill=(100, 100, 100, 255))
            draw.text((250, 250), initial, font=font, fill="white", anchor="mm")
        except Exception:
            pass
        return img

async def generate_notification_image(client, user_img, user_name, bot_name, action, email=None):
    """Generate high-quality notification image with profile pictures"""
    try:
        # Get bot profile photo
        bot_img = await get_profile_photo(client, (await client.get_me()).id)
        
        # Create base image
        width, height = 800, 400
        bg = Image.new("RGB", (width, height), (30, 30, 45))
        
        # Add gradient overlay
        gradient = Image.new("L", (1, height), color=0xFF)
        for y in range(height):
            gradient.putpixel((0, y), int(255 * (1 - y/height)))
        alpha_gradient = gradient.resize((width, height))
        black_img = Image.new("RGB", (width, height), color=(10, 10, 25))
        bg = Image.composite(bg, black_img, alpha_gradient)
        
        draw = ImageDraw.Draw(bg)
        
        # Load fonts with fallbacks
        try:
            title_font = ImageFont.truetype("arialbd.ttf", 40)
        except:
            title_font = ImageFont.load_default()
            
        try:
            name_font = ImageFont.truetype("arialbd.ttf", 28)
        except:
            name_font = ImageFont.load_default()
            
        try:
            action_font = ImageFont.truetype("arialbd.ttf", 24)
        except:
            action_font = ImageFont.load_default()
        
        # Draw title
        draw.text((width // 2, 40), "NEW ACTIVITY", 
                 font=title_font, fill="white", anchor="mm")
        
        # Draw profile images with glow effect
        def draw_profile_with_glow(img, pos, size=150):
            # Create glow
            glow = Image.new("RGBA", (size + 40, size + 40), (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow)
            center = (glow.size[0] // 2, glow.size[1] // 2)
            
            for radius in range(size // 2 + 10, size // 2 + 20, 2):
                glow_draw.ellipse(
                    [center[0] - radius, center[1] - radius,
                     center[0] + radius, center[1] + radius],
                    fill=(255, 215, 0, 10)
                )
            
            glow = glow.filter(ImageFilter.GaussianBlur(8))
            bg.paste(glow, (pos[0] - 20, pos[1] - 20), glow)
            
            # Resize and paste profile image
            img = img.resize((size, size))
            bg.paste(img, pos, img)
            
            # Add gold border
            border = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            border_draw = ImageDraw.Draw(border)
            border_draw.ellipse((0, 0, size - 1, size - 1), 
                              outline=(255, 215, 0), width=6)
            bg.paste(border, pos, border)
        
        # Position profile images
        user_pos = (130, 120)
        bot_pos = (520, 120)
        draw_profile_with_glow(user_img, user_pos)
        draw_profile_with_glow(bot_img, bot_pos)
        
        # Format names safely
        def format_name(name, max_length=15):
            if not name:
                return "User"
            name = str(name)
            return name[:max_length] + '..' if len(name) > max_length else name
            
        user_display = format_name(user_name)
        bot_display = format_name(bot_name)
        
        # Draw names
        draw.text((user_pos[0] + 75, 290), user_display,
                 font=name_font, fill="white", anchor="ma")
        draw.text((bot_pos[0] + 75, 290), bot_display,
                 font=name_font, fill="white", anchor="ma")
        
        # Draw action text
        action_text = f"Action: {action[:30] + '..' if len(action) > 30 else action}"
        if email:
            action_text += f"\nEmail: {email[:30] + '..' if len(email) > 30 else email}"
            
        draw.text((width // 2, 330), action_text,
                 font=action_font, fill=(255, 215, 0), anchor="ma")
        
        # Draw footer
        draw.rectangle([0, 370, width, 400], fill=(255, 215, 0))
        draw.text((width // 2, 385), "Powered by Temp Mail 📬",
                 font=name_font, fill=(30, 30, 30), anchor="mm")
        
        # Convert to bytes
        img_byte_arr = io.BytesIO()
        bg.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return img_byte_arr
        
    except Exception as e:
        logger.error(f"Error generating notification image: {e}", exc_info=True)
        return None

async def send_notification(client, user, action, email=None):
    """Send notification to channel with generated image and styled caption"""
    try:
        # Get user info if needed
        if isinstance(user, int):
            user = await client.get_users(user)
            
        # Generate image
        user_img = await get_profile_photo(client, user.id)
        bot_info = await client.get_me()
        image_bytes = await generate_notification_image(
    client,
    user_img,
    user.first_name or user.username or f"User_{user.id}",
    bot_info.first_name,
    action,
    email
)
        
        # Create caption
        caption = f"""⭐️ ｢Uꜱᴇʀ Aᴄᴛɪᴠɪᴛʏ Nᴏᴛɪꜰɪᴄᴀᴛɪᴏɴ 」⭐️
━━━━━━━━•❅•°•❈•°•❅•━━━━━━━━
➠ 🕵🏻‍♂️ Uꜱᴇʀɴᴀᴍᴇ: @{user.username or 'Not set'}
━━━━━━━━━━━━━━━━━━━━━━━
➠ 🆔 Uꜱᴇʀ Iᴅ: {user.id}
━━━━━━━━━━━━━━━━━━━━━━━
➠ 📦 Aᴄᴛɪᴏɴ: {action}"""

        if email:
            caption += f"\n━━━━━━━━━━━━━━━━━━━━━━━\n➠ 📧 Eᴍᴀɪʟ: <code>{email}</code>"

        caption += f"""
━━━━━━━━━━━━━━━━━━━━━━━
➠ ⏰ Tɪᴍᴇ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━━━━━━━━━
➠ 🤖 <b>Bᴏᴛ:</b> @{bot_info.username}
━━━━━━━━•❅•°•❈•°•❅•━━━━━━━━"""
        
        # Create keyboard
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🤖 Visit Bot", url=f"https://t.me/{bot_info.username}")
        ]])
        
        # Send notification
        if image_bytes:
            await client.send_photo(
                chat_id=NOTIFICATION_CHANNEL,
                photo=image_bytes,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        else:
            await client.send_message(
                chat_id=NOTIFICATION_CHANNEL,
                text=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
            
    except Exception as e:
        logger.error(f"Failed to send notification: {e}", exc_info=True)

# ------------------------ Utility Functions ------------------------

def short_id_generator(email):
    return hashlib.md5((email + str(time.time())).encode()).hexdigest()[:10]

def generate_random_username(length=8):
    return ''.join(random.choices(string.ascii_lowercase, k=length))

def generate_random_password(length=12):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def get_domain():
    res = requests.get(f"{CONFIG['BASE_URL']}/domains", headers=CONFIG['HEADERS'])
    data = res.json()
    if isinstance(data, list) and data:
        return data[0]['domain']
    if 'hydra:member' in data and data['hydra:member']:
        return data['hydra:member'][0]['domain']
    return None

def create_account(email, password):
    data = {"address": email, "password": password}
    res = requests.post(f"{CONFIG['BASE_URL']}/accounts", headers=CONFIG['HEADERS'], json=data)
    return res.json() if res.status_code in [200, 201] else None

def get_token(email, password):
    data = {"address": email, "password": password}
    res = requests.post(f"{CONFIG['BASE_URL']}/token", headers=CONFIG['HEADERS'], json=data)
    return res.json().get('token') if res.status_code == 200 else None

def get_text_from_html(html_content_list):
    html = ''.join(html_content_list)
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.find_all('a', href=True):
        a.string = f"{a.text} [{a['href']}]"
    return re.sub(r'\s+', ' ', soup.get_text()).strip()

def list_messages(token):
    headers = CONFIG['HEADERS'].copy()
    headers["Authorization"] = f"Bearer {token}"
    res = requests.get(f"{CONFIG['BASE_URL']}/messages", headers=headers)
    data = res.json()
    return data if isinstance(data, list) else data.get('hydra:member', [])

async def check_user_in_channels(client, user_id):
    if not CONFIG['REQUIRED_CHANNELS']:
        return True
    
    try:
        for channel in CONFIG['REQUIRED_CHANNELS']:
            member = await client.get_chat_member(channel, user_id)
            if member.status in ['left', 'kicked']:
                return False
        
        # Update user's channel status in DB
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'in_channels': True}}
        )
        return True
    except Exception:
        return False

async def show_channel_links(client, message):
    if not CONFIG['REQUIRED_CHANNELS']:
        return True

    buttons = []
    # Use button names if provided, else fallback to channel username
    button_names = CONFIG.get('CHANNEL_BUTTON_NAMES', [])
    for i, (channel, link) in enumerate(zip(CONFIG['REQUIRED_CHANNELS'], CONFIG['CHANNEL_LINKS'])):
        btn_text = button_names[i] if i < len(button_names) and button_names[i].strip() else f"Join @{channel}"
        buttons.append([InlineKeyboardButton(btn_text, url=link)])

    buttons.append([InlineKeyboardButton("✅ I've Joined", callback_data="check_join")])

    await message.reply_photo(
        photo=CONFIG['WELCOME_IMAGE'],
        caption="📢 **Please join our channels to use this bot**",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )
    return False

async def delete_user_message(message: Message):
    try:
        await message.delete()
    except Exception:
        pass
    
# ------------------------ Menu Functions ------------------------

def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔁 Generate Email", callback_data="generate_email"),
            InlineKeyboardButton("📨 Custom Email", callback_data="custom_email")
        ],
        [
            InlineKeyboardButton("✉️ Check Email", callback_data="check_email"),
            InlineKeyboardButton("💠 Channel Update", url=CONFIG['CHANNEL_LINKS'][0] if CONFIG['CHANNEL_LINKS'] else "https://t.me/example")
        ]
    ])

def email_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="go_back:main")]
    ])

async def show_main_menu(client, message_or_callback):
    if isinstance(message_or_callback, CallbackQuery):
        msg = message_or_callback.message
        await msg.edit_media(
            media=InputMediaPhoto(
                CONFIG['WELCOME_IMAGE'],
                caption="**📧 Welcome to Temp Mail Bot!**\n\nChoose an option below:",
                parse_mode=ParseMode.MARKDOWN
            ),
            reply_markup=main_menu()
        )
    else:
        await message_or_callback.reply_photo(
            photo=CONFIG['WELCOME_IMAGE'],
            caption="**📧 Welcome to Temp Mail Bot!**\n\nChoose an option below:",
            reply_markup=main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )

# ------------------------ Admin Commands ------------------------

@bot.on_message(filters.command('broadcast') & filters.user(CONFIG['ADMIN_IDS']))
async def broadcast_message(client, message: Message):
    """Broadcast message to all users (admin only)"""
    if len(message.command) < 2:
        await message.reply("Usage: /broadcast <message>")
        return
    
    broadcast_text = ' '.join(message.command[1:])
    users = await get_all_users()
    total_users = len(users)
    success = 0
    failed = 0
    
    progress = await message.reply(f"📢 Broadcasting to {total_users} users...")
    
    for user_id in users:
        try:
            await bot.send_message(user_id, f"📢 **Admin Broadcast**\n\n{broadcast_text}")
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.1)  # Prevent flooding
    
    await progress.edit_text(
        f"✅ Broadcast completed!\n\n"
        f"• Total users: {total_users}\n"
        f"• Successful: {success}\n"
        f"• Failed: {failed}"
    )
    await log_broadcast(message.from_user.id, broadcast_text, success)

@bot.on_message(filters.command('stats') & filters.user(CONFIG['ADMIN_IDS']))
async def show_stats(client, message: Message):
    """Show bot statistics (admin only)"""
    stats = await get_stats()
    total_users = users_collection.count_documents({})
    active_users = users_collection.count_documents({'last_active': {'$gt': datetime.now() - timedelta(days=30)}})
    
    stats_text = (
        "📊 **Bot Statistics**\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"📈 Active Users (30d): `{active_users}`\n"
        f"📧 Total Emails Created: `{stats.get('total_emails', 0)}`\n"
        f"📨 Total Messages Checked: `{stats.get('total_messages', 0)}`\n"
        f"📢 Total Broadcasts: `{broadcasts_collection.count_documents({})}`"
    )
    await message.reply(stats_text)

# ------------------------ User Commands ------------------------

@bot.on_message(filters.command('howtouse'))
async def how_to_use(client, message: Message):
    """Show how to use the bot"""
    how_to_use_text = (
        "📖 **How To Use**\n\n"
        "1. Click '🔁 Generate Email' to get a random email\n"
        "2. Use '📨 Custom Email' to create with your own username\n"
        "3. Click '✉️ Check Email' to view your messages\n\n"
        "🔒 Your emails are temporary and will expire after some time\n"
        "📢 Join our channel for updates and tips"
    )
    await message.reply_photo(
        photo=CONFIG['WELCOME_IMAGE'],
        caption=how_to_use_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Join Channel", url=CONFIG['CHANNEL_LINKS'][0] if CONFIG['CHANNEL_LINKS'] else "https://t.me/example")]
        ])
    )
    await delete_user_message(message)

@bot.on_message(filters.command('contactus'))
async def contact_us(client, message: Message):
    """Show contact information"""
    contact_text = (
        "📩 **Contact Us**\n\n"
        "For any issues or questions:\n"
        "👉 @YourSupportUsername\n\n"
        "📢 Join our main channel:\n"
        f"{CONFIG['CHANNEL_LINKS'][0] if CONFIG['CHANNEL_LINKS'] else 'https://t.me/example'}"
    )
    await message.reply(contact_text)
    await delete_user_message(message)

# ------------------------ Bot Handlers ------------------------

@bot.on_message(filters.command('start'))
async def start_handler(client, message: Message):
    """Respond to the /start command"""
    await delete_user_message(message)
    await register_user(message.from_user.id, message.from_user.username)
    
    # Send notification to channel
    await send_notification(client, message.from_user, "Started the bot")

    # Check if user is in required channels
    if not await check_user_in_channels(client, message.from_user.id):
        await show_channel_links(client, message)
        return

    await message.reply_photo(
        photo=CONFIG['WELCOME_IMAGE'],
        caption="**📧 Welcome to Temp Mail Bot!**\n\nChoose an option below:",
        reply_markup=main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

@bot.on_callback_query(filters.regex("^check_join$"))
async def check_join_handler(client, callback_query: CallbackQuery):
    """Check if user has joined channels"""
    if await check_user_in_channels(client, callback_query.from_user.id):
        await show_main_menu(client, callback_query)
    else:
        await callback_query.answer("You haven't joined all channels yet!", show_alert=True)

@bot.on_callback_query()
async def callback_handler(client, callback_query: CallbackQuery):
    data = callback_query.data
    
    if data == "generate_email":
        await handle_generate_email(client, callback_query)
    elif data == "custom_email":
        await handle_custom_email_prompt(client, callback_query)
    elif data == "check_email":
        await handle_check_email_prompt(client, callback_query)
    elif data.startswith("go_back:"):
        if data.split(":")[1] == "main":
            await show_main_menu(client, callback_query)
    elif data.startswith("check_"):
        await handle_check_mail(client, callback_query)
    elif data.startswith("read_"):
        await handle_read_mail(client, callback_query)
    elif data == "close_message":
        await handle_close_message(client, callback_query)
    
    await callback_query.answer()

async def handle_generate_email(client, callback_query: CallbackQuery):
    msg = callback_query.message
    loading = await msg.reply("**Generating your temporary email...**")

    username = generate_random_username()
    password = generate_random_password()

    domain = get_domain()
    if not domain:
        await msg.reply("**Domain fetch failed. Try again.**")
        return await loading.delete()

    email = f"{username}@{domain}"
    account = create_account(email, password)
    if not account:
        await msg.reply("**Username taken. Choose another.**")
        return await loading.delete()

    time.sleep(1.5)
    token = get_token(email, password)
    if not token:
        await msg.reply("**Token generation failed.**")
        return await loading.delete()

    sid = short_id_generator(email)
    token_map[sid] = token

    # Send notification to channel for email generation
    await send_notification(
        client,
        callback_query.from_user,
        "Generated a temp email",
        email=email
    )

    reply = (
        "**📧 Smart-Email Details 📧**\n"
        f"**📧 Email:** `{email}`\n"
        f"**🔑 Password:** `{password}`\n"
        f"**🔒 Token:** `{token}`\n"
        "**━━━━━━━━━━━━━━━━━━**\n"
        "Keep your token to check emails."
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Check Emails", callback_data=f"check_{sid}")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="go_back:main")]
    ])

    await msg.edit_media(
        media=InputMediaPhoto(
            CONFIG['WELCOME_IMAGE'],
            caption=reply,
            parse_mode=ParseMode.MARKDOWN
        ),
        reply_markup=keyboard
    )
    await loading.delete()

    await increment_stat('total_emails', 1)

async def handle_custom_email_prompt(client, callback_query: CallbackQuery):
    msg = callback_query.message
    await msg.edit_media(
        media=InputMediaPhoto(
            CONFIG['WELCOME_IMAGE'],
            caption="**📨 Custom Email**\n\nPlease send your desired username and password in this format:\n\n`username:password`",
            parse_mode=ParseMode.MARKDOWN
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="go_back:main")]
        ])
    )
    
    # Store the user's state to expect a custom email next
    @bot.on_message(filters.text & filters.private & filters.user(callback_query.from_user.id))
    async def wait_for_custom_email(client, message: Message):
        if ':' not in message.text:
            await message.reply("**Invalid format. Use `username:password`**")
            await delete_user_message(message)
            return
        
        await delete_user_message(message)
        username, password = message.text.split(':', 1)
        
        loading = await msg.reply("**Creating your custom email...**")
        
        domain = get_domain()
        if not domain:
            await msg.reply("**Domain fetch failed. Try again.**")
            return await loading.delete()
        
        email = f"{username}@{domain}"
        account = create_account(email, password)
        if not account:
            await msg.reply("**Username taken. Choose another.**")
            return await loading.delete()
        
        time.sleep(1.5)
        token = get_token(email, password)
        if not token:
            await msg.reply("**Token generation failed.**")
            return await loading.delete()
        
        sid = short_id_generator(email)
        token_map[sid] = token
        
        # Send notification to channel for email generation
        await send_notification(
            client,
            message.from_user,
            "Generated a custom temp email",
            email=email
        )
        
        reply = (
            "**📧 Smart-Email Details 📧**\n"
            f"**📧 Email:** `{email}`\n"
            f"**🔑 Password:** `{password}`\n"
            f"**🔒 Token:** `{token}`\n"
            "**━━━━━━━━━━━━━━━━━━**\n"
            "Keep your token to check emails."
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Check Emails", callback_data=f"check_{sid}")],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="go_back:main")]
        ])
        
        await msg.edit_media(
            media=InputMediaPhoto(
                CONFIG['WELCOME_IMAGE'],
                caption=reply,
                parse_mode=ParseMode.MARKDOWN
            ),
            reply_markup=keyboard
        )
        await loading.delete()
        
        # Remove the handler after processing
        bot.remove_handler(wait_for_custom_email)

async def handle_check_email_prompt(client, callback_query: CallbackQuery):
    msg = callback_query.message
    await msg.edit_media(
        media=InputMediaPhoto(
            CONFIG['WELCOME_IMAGE'],
            caption="**✉️ Check Email**\n\nPlease send your email token to check your messages:",
            parse_mode=ParseMode.MARKDOWN
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="go_back:main")]
        ])
    )
    
    # Store the user's state to expect a token next
    @bot.on_message(filters.text & filters.private & filters.user(callback_query.from_user.id))
    async def wait_for_token(client, message: Message):
        token = message.text.strip()
        await delete_user_message(message)
        
        loading = await msg.reply("**⏳ Checking Mails...**")
        user_tokens[message.from_user.id] = token
        msgs = list_messages(token)
        
        if not msgs:
            await msg.reply("**❌ No messages or invalid token.**")
            return await loading.delete()
        
        output = "**📧 Your Smart-Mail Messages 📧**\n━━━━━━━━━━━━━━━━━━\n"
        buttons = []
        
        for i, msg_data in enumerate(msgs[:10], 1):
            output += f"{i}. From: {msg_data['from']['address']} - Subject: {msg_data['subject']}\n"
            buttons.append(InlineKeyboardButton(f"{i}", callback_data=f"read_{msg_data['id']}"))
        
        rows = [buttons[i:i+5] for i in range(0, len(buttons), 5)]
        keyboard = InlineKeyboardMarkup(rows + [[InlineKeyboardButton("⬅️ Back", callback_data="go_back:main")]])
        
        await msg.edit_media(
            media=InputMediaPhoto(
                CONFIG['WELCOME_IMAGE'],
                caption=output,
                parse_mode=ParseMode.MARKDOWN
            ),
            reply_markup=keyboard
        )
        await loading.delete()
        
        # Remove the handler after processing
        bot.remove_handler(wait_for_token)

async def handle_check_mail(client, callback_query: CallbackQuery):
    sid = callback_query.data.split('_')[1]
    token = token_map.get(sid)
    if not token:
        return await callback_query.message.reply("**Session expired. Use /cmail with your token.**")
    
    user_tokens[callback_query.from_user.id] = token
    msgs = list_messages(token)
    
    if not msgs:
        return await callback_query.answer("No messages yet.", show_alert=True)
    
    loading = await callback_query.message.reply("**⏳ Checking Mails...**")
    
    output = "**📧 Your Smart-Mail Messages 📧**\n━━━━━━━━━━━━━━━━━━\n"
    buttons = []
    
    for i, msg in enumerate(msgs[:10], 1):
        output += f"{i}. From: `{msg['from']['address']}` - Subject: {msg['subject']}\n"
        buttons.append(InlineKeyboardButton(f"{i}", callback_data=f"read_{msg['id']}"))
    
    rows = [buttons[i:i+5] for i in range(0, len(buttons), 5)]
    keyboard = InlineKeyboardMarkup(rows + [[InlineKeyboardButton("⬅️ Back", callback_data="go_back:main")]])
    
    await callback_query.message.edit_media(
        media=InputMediaPhoto(
            CONFIG['WELCOME_IMAGE'],
            caption=output,
            parse_mode=ParseMode.MARKDOWN
        ),
        reply_markup=keyboard
    )
    await loading.delete()

async def handle_read_mail(client, callback_query: CallbackQuery):
    msg_id = callback_query.data.split('_')[1]
    token = user_tokens.get(callback_query.from_user.id)
    if not token:
        return await callback_query.message.reply("**Token not found. Use /cmail again.**")
    
    headers = CONFIG['HEADERS'].copy()
    headers["Authorization"] = f"Bearer {token}"
    res = requests.get(f"{CONFIG['BASE_URL']}/messages/{msg_id}", headers=headers)
    
    if res.status_code != 200:
        return await callback_query.message.reply("**Failed to fetch message.**")
    
    data = res.json()
    content = (
        get_text_from_html(data['html']) if 'html' in data else data.get('text', "Content not available.")
    )
    
    if len(content) > CONFIG['MAX_MESSAGE_LENGTH']:
        content = content[:CONFIG['MAX_MESSAGE_LENGTH'] - 100] + "... [truncated]"
    
    reply = f"**From:** `{data['from']['address']}`\n**Subject:** `{data['subject']}`\n━━━━━━━━━━━━━━━━━━\n{content}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Close", callback_data="close_message")]])
    await callback_query.message.reply(reply, reply_markup=keyboard, disable_web_page_preview=True)

async def handle_close_message(client, callback_query: CallbackQuery):
    await callback_query.message.delete()

# ------------------------ Start Bot ------------------------

# Optional: Health check endpoint for Render
from aiohttp import web

async def health_check(request):
    return web.Response(text="OK")

def run_health_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    port = int(os.getenv('PORT', 10000))
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    print("Bot is running...")
    import threading
    if os.getenv("PORT"):
        bot_thread = threading.Thread(target=bot.run, daemon=True)
        bot_thread.start()
        run_health_server()
    else:
        bot.run()
