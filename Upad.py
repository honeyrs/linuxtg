import asyncio
import paramiko
import random
import threading
import subprocess
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from pymongo import MongoClient
import logging

# Define conversation states
SSH, TRUSTED, PASSWORD, TERMINAL = range(4)

# MongoDB setup
MONGO_URI = "mongodb+srv://testbindark:65I379zmYZzefXmm@clus.xg5n6.mongodb.net/"  # Replace with your MongoDB URI
client = MongoClient(MONGO_URI)
db = client["ssh_bot_db"]
bots_collection = db["bots"]

# Constants
MAIN_OWNER_ID = "1094941160"  # Replace with @h_oneysingh's Telegram ID
LOG_GROUP_ID = -1002335903626  # Replace with your log group ID
MAIN_BOT_TOKEN = "7891611632:AAFBNG71g-VM34macGZ2cryMRkmQ0zq8Lwo"  # Replace with your main bot token

# Store runtime data
user_data = {}
ssh_sessions = {}
bot_instances = {}  # {bot_token: Application}
port_forwards = {}  # {chat_id: {"thread": Thread, "port": int}}

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def log_to_group(context: ContextTypes.DEFAULT_TYPE, message: str):
    """Log messages to the specified group"""
    try:
        await context.bot.send_message(chat_id=LOG_GROUP_ID, text=message[:4000])
    except Exception as e:
        logger.error(f"Failed to log to group: {str(e)}")

def setup_web_editor(ssh_client, chat_id):
    """Setup code-server on the remote server and start port forwarding"""
    try:
        # Choose a random port between 8000-9000
        port = random.randint(8000, 9000)
        
        # Check if port is available on the remote server
        stdin, stdout, stderr = ssh_client.exec_command(f"netstat -tuln | grep :{port}")
        if stdout.read().decode().strip():
            return None, "Port already in use"
        
        # Install code-server in the background
        install_cmd = (
            "curl -fsSL https://code-server.dev/install.sh | sh -s -- --prefix=/tmp/code-server && "
            f"/tmp/code-server/bin/code-server --port {port} --auth none --host 0.0.0.0 /home/user &"
        )
        ssh_client.exec_command(install_cmd)
        
        # Wait briefly to ensure code-server starts
        time.sleep(2)
        
        # Start local port forwarding in a separate thread
        def forward_port():
            ssh_cmd = (
                f"ssh -L {port}:localhost:{port} -N "
                f"{user_data[chat_id]['username']}@{user_data[chat_id]['ip']}"
            )
            process = subprocess.Popen(ssh_cmd, shell=True)
            port_forwards[chat_id]["process"] = process
            process.wait()
        
        port_thread = threading.Thread(target=forward_port)
        port_thread.start()
        
        # Store thread and port
        port_forwards[chat_id] = {"thread": port_thread, "port": port}
        return port, None
    except Exception as e:
        return None, str(e)

def cleanup_web_editor(ssh_client, chat_id):
    """Cleanup code-server and port forwarding"""
    try:
        if chat_id in port_forwards:
            # Kill code-server process
            ssh_client.exec_command("pkill -f code-server")
            ssh_client.exec_command("rm -rf /tmp/code-server")
            
            # Stop port forwarding
            if "process" in port_forwards[chat_id]:
                port_forwards[chat_id]["process"].terminate()
            port_forwards[chat_id]["thread"].join(timeout=2)
            del port_forwards[chat_id]
    except Exception as e:
        logger.error(f"Cleanup error for {chat_id}: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start command handler"""
    await update.message.reply_text("Welcome! Use /ssh username@ip to start an SSH login.")
    await log_to_group(context, f"User {update.effective_user.id} started bot.")
    return ConversationHandler.END

async def ssh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Initiate SSH connection"""
    ssh_input = update.message.text.split(" ", 1)
    if len(ssh_input) < 2:
        await update.message.reply_text("Please provide username@ip, e.g., /ssh user@192.168.1.1")
        return ConversationHandler.END
    
    username_ip = ssh_input[1].strip()
    if "@" not in username_ip:
        await update.message.reply_text("Invalid format. Use username@ip.")
        return ConversationHandler.END
    
    username, ip = username_ip.split("@")
    user_data[update.message.chat_id] = {"username": username, "ip": ip}
    
    await update.message.reply_text(f"Attempting SSH to {ip}. Is this host trusted? Reply 'trusted yes' or 'no'.")
    await log_to_group(context, f"User {update.effective_user.id} initiated SSH to {username}@{ip}")
    return TRUSTED

async def trusted_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle trusted host response"""
    chat_id = update.message.chat_id
    if chat_id not in user_data:
        await update.message.reply_text("Session expired. Start again with /ssh.")
        return ConversationHandler.END
    
    response = update.message.text.lower().strip()
    if response != "trusted yes":
        await update.message.reply_text("SSH aborted. Host not trusted.")
        del user_data[chat_id]
        return ConversationHandler.END
    
    await update.message.reply_text("Host trusted. Please enter the password:")
    return PASSWORD

async def password_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle password input and establish SSH connection"""
    chat_id = update.message.chat_id
    if chat_id not in user_data:
        await update.message.reply_text("Session expired. Start again with /ssh.")
        return ConversationHandler.END
    
    password = update.message.text.strip()
    username = user_data[chat_id]["username"]
    ip = user_data[chat_id]["ip"]
    
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh_client.connect(ip, username=username, password=password, timeout=10)
        ssh_sessions[chat_id] = ssh_client
        bots_collection.update_one(
            {"token": context.bot.token},
            {"$set": {f"ssh_sessions.{chat_id}": {"username": username, "ip": ip, "password": password}}},
            upsert=True
        )
        await update.message.reply_text(f"Connected to {username}@{ip}! Send commands or /exit.")
        await log_to_group(context, f"User {update.effective_user.id} connected to {username}@{ip}")
        return TERMINAL
    except Exception as e:
        await update.message.reply_text(f"SSH error: {str(e)}")
        del user_data[chat_id]
        return ConversationHandler.END

async def terminal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle terminal commands including /nano"""
    chat_id = update.message.chat_id
    if chat_id not in ssh_sessions:
        await update.message.reply_text("No active SSH session. Start with /ssh.")
        return ConversationHandler.END
    
    command = update.message.text.strip()
    ssh_client = ssh_sessions[chat_id]
    
    if command == "/exit":
        cleanup_web_editor(ssh_client, chat_id)
        ssh_client.close()
        del ssh_sessions[chat_id]
        del user_data[chat_id]
        bots_collection.update_one({"token": context.bot.token}, {"$unset": f"ssh_sessions.{chat_id}"})
        await update.message.reply_text("Disconnected from the VPS. All resources cleaned up.")
        await log_to_group(context, f"User {update.effective_user.id} disconnected and cleaned up.")
        return ConversationHandler.END
    
    if command.startswith("/nano "):
        file_path = command[len("/nano "):].strip()
        if not file_path:
            await update.message.reply_text("Usage: /nano <file_path>")
            return TERMINAL
        
        # Setup web editor
        port, error = setup_web_editor(ssh_client, chat_id)
        if error:
            await update.message.reply_text(f"Failed to setup editor: {error}")
            return TERMINAL
        
        # Provide link
        link = f"http://localhost:{port}"
        await update.message.reply_text(
            f"Open this link in your browser to edit {file_path}:\n{link}\n"
            "Save your changes in the editor. Use /exit to disconnect and cleanup."
        )
        await log_to_group(context, f"User {update.effective_user.id} opened editor for {file_path} at {link}")
        return TERMINAL
    
    # Execute regular commands
    try:
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=10)
        output = stdout.read().decode("utf-8").strip()
        error = stderr.read().decode("utf-8").strip()
        response = output or error or "No output."
        await update.message.reply_text(response[:4000])
        await log_to_group(context, f"User {update.effective_user.id} executed: {command}\nOutput: {response[:100]}")
    except Exception as e:
        await update.message.reply_text(f"Error executing command: {str(e)}")
    
    return TERMINAL

async def clone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clone the bot with a new token"""
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /clone <new_bot_token>")
        return
    
    new_token = context.args[0]
    bot_data = bots_collection.find_one({"token": context.bot.token})
    if str(update.effective_user.id) != MAIN_OWNER_ID and str(update.effective_user.id) not in bot_data.get("sudo_users", []):
        await update.message.reply_text("Only owner or sudo users can clone.")
        return
    
    # Create new bot instance
    new_app = Application.builder().token(new_token).build()
    setup_handlers(new_app)
    bot_instances[new_token] = new_app
    
    # Store in MongoDB
    bots_collection.insert_one({
        "token": new_token,
        "owner_id": str(update.effective_user.id),
        "sudo_users": [],
        "ssh_sessions": {}
    })
    
    await update.message.reply_text(f"Bot cloned with token {new_token}. Starting now...")
    await log_to_group(context, f"User {update.effective_user.id} cloned bot with token {new_token}")
    asyncio.create_task(new_app.run_polling(allowed_updates=Update.ALL_TYPES))

async def addsudo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a sudo user"""
    bot_data = bots_collection.find_one({"token": context.bot.token})
    if str(update.effective_user.id) != MAIN_OWNER_ID and str(update.effective_user.id) != bot_data["owner_id"]:
        await update.message.reply_text("Only owners can add sudo users.")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /addsudo <user_id>")
        return
    
    user_id = context.args[0]
    bots_collection.update_one({"token": context.bot.token}, {"$addToSet": {"sudo_users": user_id}})
    await update.message.reply_text(f"Added {user_id} as sudo.")
    await log_to_group(context, f"User {update.effective_user.id} added sudo {user_id}")

async def removesudo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a sudo user"""
    bot_data = bots_collection.find_one({"token": context.bot.token})
    if str(update.effective_user.id) != MAIN_OWNER_ID and str(update.effective_user.id) != bot_data["owner_id"]:
        await update.message.reply_text("Only owners can remove sudo users.")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /removesudo <user_id>")
        return
    
    user_id = context.args[0]
    bots_collection.update_one({"token": context.bot.token}, {"$pull": {"sudo_users": user_id}})
    await update.message.reply_text(f"Removed {user_id} from sudo.")
    await log_to_group(context, f"User {update.effective_user.id} removed sudo {user_id}")

async def show_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the bot owner"""
    bot_data = bots_collection.find_one({"token": context.bot.token})
    if str(update.effective_user.id) != MAIN_OWNER_ID and str(update.effective_user.id) != bot_data["owner_id"]:
        await update.message.reply_text("Only owners can see this.")
        return
    owner = "@h_oneysingh" if str(update.effective_user.id) == MAIN_OWNER_ID else bot_data["owner_id"]
    await update.message.reply_text(f"Owner: {owner}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Broadcast a message to all bots"""
    if str(update.effective_user.id) != MAIN_OWNER_ID:
        await update.message.reply_text("Only main owner can broadcast.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    
    message = " ".join(context.args)
    for token, app in bot_instances.items():
        try:
            await app.bot.send_message(chat_id=LOG_GROUP_ID, text=f"Broadcast: {message}")
            await log_to_group(context, f"Broadcasted to bot {token}: {message}")
        except Exception as e:
            logger.error(f"Failed to broadcast to {token}: {str(e)}")
    await update.message.reply_text("Broadcast sent to all bots.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current SSH session"""
    chat_id = update.message.chat_id
    if chat_id in ssh_sessions:
        cleanup_web_editor(ssh_sessions[chat_id], chat_id)
        ssh_sessions[chat_id].close()
        del ssh_sessions[chat_id]
    if chat_id in user_data:
        del user_data[chat_id]
    await update.message.reply_text("SSH session cancelled and cleaned up.")
    return ConversationHandler.END

def setup_handlers(application: Application) -> None:
    """Setup all command and conversation handlers"""
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("ssh", ssh_command)],
        states={
            TRUSTED: [MessageHandler(filters.TEXT & ~filters.COMMAND, trusted_response)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_response)],
            TERMINAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, terminal_command)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("clone", clone))
    application.add_handler(CommandHandler("addsudo", addsudo))
    application.add_handler(CommandHandler("removesudo", removesudo))
    application.add_handler(CommandHandler("show_owner", show_owner))
    application.add_handler(CommandHandler("broadcast", broadcast))

def main() -> None:
    """Main function to start the bot and auto-start cloned bots"""
    # Main bot setup
    main_app = Application.builder().token(MAIN_BOT_TOKEN).build()
    setup_handlers(main_app)
    bot_instances[MAIN_BOT_TOKEN] = main_app
    
    # Initialize main bot in MongoDB
    bots_collection.update_one(
        {"token": MAIN_BOT_TOKEN},
        {"$set": {"owner_id": MAIN_OWNER_ID, "sudo_users": [], "ssh_sessions": {}}},
        upsert=True
    )
    
    # Auto-start cloned bots from MongoDB
    for bot in bots_collection.find({"token": {"$ne": MAIN_BOT_TOKEN}}):
        try:
            app = Application.builder().token(bot["token"]).build()
            setup_handlers(app)
            bot_instances[bot["token"]] = app
            asyncio.create_task(app.run_polling(allowed_updates=Update.ALL_TYPES))
            logger.info(f"Auto-started cloned bot with token {bot['token']}")
        except Exception as e:
            logger.error(f"Failed to auto-start bot {bot['token']}: {str(e)}")
    
    # Start main bot
    main_app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    import time
    main()
