import asyncio
import logging
import random
import threading
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
import paramiko
from pymongo import MongoClient
import subprocess
import os
from typing import Dict, List

# Constants
MAIN_OWNER_ID = '1094941160'
LOG_GROUP_ID = -1002335903626
MAIN_BOT_TOKEN = '7891611632:AAFptf8qIr1ZOeYzghGVnPpSOpOtq8U8Z6Q'
MONGO_URI = 'mongodb+srv://testbindark:65I379zmYZzefXmm@clus.xg5n6.mongodb.net/'

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory storage
ssh_sessions: Dict[int, paramiko.SSHClient] = {}
user_data: Dict[int, dict] = {}
port_forwards: Dict[int, threading.Thread] = {}

# MongoDB setup
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['telegram_bot']
bots_collection = db['bots']

# Conversation states
SSH, TRUSTED, PASSWORD, TERMINAL = range(4)

async def log_to_group(context: ContextTypes.DEFAULT_TYPE, message: str):
    """Log messages to the specified Telegram group."""
    if len(message) > 4000:
        message = message[:3997] + '...'
    await context.bot.send_message(chat_id=LOG_GROUP_ID, text=message)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler."""
    await update.message.reply_text("Welcome! Use /ssh username@ip to connect.")
    return SSH

async def ssh_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ssh command."""
    user_id = str(update.message.from_user.id)
    if not await check_access(user_id, context):
        await update.message.reply_text("Unauthorized access.")
        return ConversationHandler.END
    
    try:
        ssh_str = update.message.text.split()[1]
        username, ip = ssh_str.split('@')
        user_data[user_id] = {'username': username, 'ip': ip}
        await update.message.reply_text("Is this host trusted? (yes/no)")
        return TRUSTED
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /ssh username@ip")
        return ConversationHandler.END

async def trusted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle trusted host response."""
    user_id = str(update.message.from_user.id)
    if update.message.text.lower() == 'yes':
        await update.message.reply_text("Enter password:")
        return PASSWORD
    else:
        await update.message.reply_text("Host not trusted. Session ended.")
        return ConversationHandler.END

async def password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle password input and establish SSH connection."""
    user_id = str(update.message.from_user.id)
    password = update.message.text
    data = user_data[user_id]
    
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(data['ip'], username=data['username'], password=password)
        ssh_sessions[user_id] = ssh
        # Updated instruction to reflect filename instead of file_path
        await update.message.reply_text("Connected! Enter commands or use /logout, /nano <filename>")
        await log_to_group(context, f"User {user_id} connected to {data['ip']}")
        return TERMINAL
    except Exception as e:
        await update.message.reply_text(f"Connection failed: {str(e)}")
        return ConversationHandler.END

async def terminal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle terminal commands."""
    user_id = str(update.message.from_user.id)
    command = update.message.text
    
    if command == '/logout':
        await cleanup_session(user_id, context)
        return ConversationHandler.END
    elif command.startswith('/nano'):
        await handle_nano(user_id, command, update, context)
        return TERMINAL
    
    ssh = ssh_sessions.get(user_id)
    if ssh:
        try:
            stdin, stdout, stderr = ssh.exec_command(command)
            output = stdout.read().decode() or stderr.read().decode()
            await update.message.reply_text(output[:4000])
            await log_to_group(context, f"User {user_id} executed: {command}\nOutput: {output[:1000]}")
        except Exception as e:
            await update.message.reply_text(f"Error: {str(e)}")
    return TERMINAL

async def handle_nano(user_id: str, command: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Setup web-based code editor with code-server for a filename."""
    ssh = ssh_sessions[user_id]
    port = random.randint(8000, 9000)
    
    try:
        # Extract filename instead of file_path
        filename = command.split()[1] if len(command.split()) > 1 else "untitled"
        # Use filename directly instead of full path
        ssh.exec_command("which code-server || (curl -fsSL https://code-server.dev/install.sh | sh)")
        ssh.exec_command(f"code-server {filename} --port {port} --auth none &")
        
        # Setup local port forwarding
        def forward_port():
            subprocess.run(f"ssh -L {port}:localhost:{port} {user_data[user_id]['username']}@{user_data[user_id]['ip']}", shell=True)
        
        forward_thread = threading.Thread(target=forward_port)
        forward_thread.start()
        port_forwards[user_id] = forward_thread
        
        await update.message.reply_text(f"Editor available at http://localhost:{port} for {filename}")
        await log_to_group(context, f"User {user_id} started editor on port {port} for {filename}")
    except Exception as e:
        await update.message.reply_text(f"Failed to setup editor: {str(e)}")

async def cleanup_session(user_id: str, context: ContextTypes.DEFAULT_TYPE):
    """Clean up SSH session and resources."""
    if user_id in ssh_sessions:
        ssh_sessions[user_id].close()
        del ssh_sessions[user_id]
    if user_id in port_forwards:
        del port_forwards[user_id]
    if user_id in user_data:
        del user_data[user_id]
    await log_to_group(context, f"User {user_id} session cleaned up")

async def clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clone the bot with a new token."""
    user_id = str(update.message.from_user.id)
    if user_id != MAIN_OWNER_ID:
        await update.message.reply_text("Only master owner can clone.")
        return
    
    try:
        new_token = update.message.text.split()[1]
        for _ in range(3):
            try:
                app = Application.builder().token(new_token).build()
                bots_collection.insert_one({'token': new_token, 'owner': user_id, 'sudo_users': []})
                await start_bot(app)
                await update.message.reply_text("Bot cloned successfully!")
                return
            except Exception:
                continue
        await update.message.reply_text("Failed to clone bot after 3 attempts.")
    except IndexError:
        await update.message.reply_text("Usage: /clone <new_bot_token>")

async def add_sudo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a sudo user."""
    user_id = str(update.message.from_user.id)
    bot_data = bots_collection.find_one({'owner': user_id})
    if not bot_data:
        await update.message.reply_text("You don't own a bot.")
        return
    
    try:
        sudo_id = update.message.text.split()[1]
        bots_collection.update_one({'owner': user_id}, {'$push': {'sudo_users': sudo_id}})
        await update.message.reply_text(f"Sudo user {sudo_id} added.")
    except IndexError:
        await update.message.reply_text("Usage: /addsudo <user_id>")

async def remove_sudo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a sudo user."""
    user_id = str(update.message.from_user.id)
    bot_data = bots_collection.find_one({'owner': user_id})
    if not bot_data:
        await update.message.reply_text("You don't own a bot.")
        return
    
    try:
        sudo_id = update.message.text.split()[1]
        bots_collection.update_one({'owner': user_id}, {'$pull': {'sudo_users': sudo_id}})
        await update.message.reply_text(f"Sudo user {sudo_id} removed.")
    except IndexError:
        await update.message.reply_text("Usage: /removesudo <user_id>")

async def show_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot owner."""
    user_id = str(update.message.from_user.id)
    bot_data = bots_collection.find_one({'token': context.bot.token})
    owner = bot_data.get('owner') if bot_data else MAIN_OWNER_ID
    await update.message.reply_text(f"Bot owner: {owner}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all cloned bots."""
    user_id = str(update.message.from_user.id)
    if user_id != MAIN_OWNER_ID:
        await update.message.reply_text("Only master owner can broadcast.")
        return
    
    message = ' '.join(update.message.text.split()[1:])
    for bot in bots_collection.find():
        app = Application.builder().token(bot['token']).build()
        await app.bot.send_message(chat_id=LOG_GROUP_ID, text=message)
    await update.message.reply_text("Broadcast sent.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current session."""
    user_id = str(update.message.from_user.id)
    await cleanup_session(user_id, context)
    await update.message.reply_text("Session cancelled.")
    return ConversationHandler.END

async def check_access(user_id: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check user access level."""
    if user_id == MAIN_OWNER_ID:
        return True
    bot_data = bots_collection.find_one({'token': context.bot.token})
    if not bot_data:
        return False
    return user_id == bot_data['owner'] or user_id in bot_data.get('sudo_users', [])

async def start_bot(app: Application):
    """Start a bot instance with handlers."""
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('ssh', ssh_start)],
        states={
            SSH: [CommandHandler('ssh', ssh_start)],
            TRUSTED: [MessageHandler(filters.TEXT & ~filters.COMMAND, trusted)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password)],
            TERMINAL: [MessageHandler(filters.TEXT, terminal)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('clone', clone))
    app.add_handler(CommandHandler('addsudo', add_sudo))
    app.add_handler(CommandHandler('removesudo', remove_sudo))
    app.add_handler(CommandHandler('show_owner', show_owner))
    app.add_handler(CommandHandler('broadcast', broadcast))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

async def main():
    """Main entry point to start all bots."""
    main_app = Application.builder().token(MAIN_BOT_TOKEN).build()
    await start_bot(main_app)
    
    for bot in bots_collection.find():
        app = Application.builder().token(bot['token']).build()
        await start_bot(app)
    
    await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(main())
