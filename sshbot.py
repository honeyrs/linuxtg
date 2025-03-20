import asyncio
import paramiko
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Define conversation states
SSH, TRUSTED, PASSWORD = range(3)

# Store user data temporarily
user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Welcome! Use /ssh username@ip to start an SSH login.")
    return ConversationHandler.END

async def ssh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the /ssh command"""
    ssh_input = update.message.text.split(" ", 1)  # Split "/ssh username@ip"
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
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # Auto-trust host
    try:
        ssh_client.connect(ip, username=username, password=password, timeout=10)
        await update.message.reply_text(f"Successfully connected to {username}@{ip}!")
        ssh_client.close()
    except paramiko.AuthenticationException:
        await update.message.reply_text("Authentication failed. Wrong password or credentials.")
    except Exception as e:
        await update.message.reply_text(f"SSH error: {str(e)}")
    
    # Clean up
    del user_data[chat_id]
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation"""
    chat_id = update.message.chat_id
    if chat_id in user_data:
        del user_data[chat_id]
    await update.message.reply_text("SSH login cancelled.")
    return ConversationHandler.END

def main() -> None:
    """Main function to run the bot"""
    # Replace 'YOUR_TELEGRAM_BOT_TOKEN' with your actual token from BotFather
    application = Application.builder().token("7891611632:AAGEEdqf726lQNlopHlEozhKZPwkKYr0Uok").build()

    # Define the conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("ssh", ssh_command)],
        states={
            TRUSTED: [MessageHandler(filters.TEXT & ~filters.COMMAND, trusted_response)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_response)],
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
