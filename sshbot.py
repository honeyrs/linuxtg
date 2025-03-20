import asyncio
import paramiko
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Define conversation states
SSH, TRUSTED, PASSWORD, TERMINAL = range(4)

# Store user data and SSH sessions
user_data = {}
ssh_sessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Welcome! Use /ssh username@ip to start an SSH login.")
    return ConversationHandler.END

async def ssh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the /ssh command"""
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
    return TRUSTED

async def trusted_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the trusted response"""
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
    """Handle the password and attempt SSH login"""
    chat_id = update.message.chat_id
    if chat_id not in user_data:
        await update.message.reply_text("Session expired. Start again with /ssh.")
        return ConversationHandler.END
    
    password = update.message.text.strip()
    username = user_data[chat_id]["username"]
    ip = user_data[chat_id]["ip"]
    
    # Attempt SSH connection
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh_client.connect(ip, username=username, password=password, timeout=10)
        ssh_sessions[chat_id] = ssh_client  # Store the SSH session
        await update.message.reply_text(f"Successfully connected to {username}@{ip}!\n"
                                        "You are now in terminal mode. Send commands (e.g., 'ls', 'whoami') or '/exit' to disconnect.")
        return TERMINAL
    except paramiko.AuthenticationException:
        await update.message.reply_text("Authentication failed. Wrong password or credentials.")
        del user_data[chat_id]
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"SSH error: {str(e)}")
        del user_data[chat_id]
        return ConversationHandler.END

async def terminal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle terminal commands after login"""
    chat_id = update.message.chat_id
    if chat_id not in ssh_sessions:
        await update.message.reply_text("No active SSH session. Start with /ssh.")
        return ConversationHandler.END
    
    command = update.message.text.strip()
    if command == "/exit":
        ssh_sessions[chat_id].close()
        del ssh_sessions[chat_id]
        del user_data[chat_id]
        await update.message.reply_text("Disconnected from the VPS.")
        return ConversationHandler.END
    
    # Execute the command on the VPS
    ssh_client = ssh_sessions[chat_id]
    try:
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=10)
        output = stdout.read().decode("utf-8").strip()
        error = stderr.read().decode("utf-8").strip()
        
        response = output if output else error if error else "Command executed, no output."
        await update.message.reply_text(response[:4000])  # Telegram message limit is ~4096 chars
    except Exception as e:
        await update.message.reply_text(f"Error executing command: {str(e)}")
    
    return TERMINAL

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation or disconnect"""
    chat_id = update.message.chat_id
    if chat_id in ssh_sessions:
        ssh_sessions[chat_id].close()
        del ssh_sessions[chat_id]
    if chat_id in user_data:
        del user_data[chat_id]
    await update.message.reply_text("SSH login or session cancelled.")
    return ConversationHandler.END

def main() -> None:
    """Main function to run the bot"""
    # Replace 'YOUR_TELEGRAM_BOT_TOKEN' with your actual token from BotFather
    application = Application.builder().token("7891611632:AAG8-lvlmoT8LjQ0LAA9NjgoHHOAWLlczl0").build()

    # Define the conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("ssh", ssh_command)],
        states={
            TRUSTED: [MessageHandler(filters.TEXT & ~filters.COMMAND, trusted_response)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_response)],
            TERMINAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, terminal_command)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
