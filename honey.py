import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, filters
import subprocess
import os

# Replace with your bot token from BotFather
TOKEN = "8132664143:AAGrAKwg2zZw2YUzqe1UCO1JlqPr3W_weUk"

# Initialize the bot
updater = Updater(token=TOKEN, use_context=True)
dp = updater.dispatcher

# Store the state of which file is being "edited" by nano (per user)
nano_state = {}

# Function to handle the /start command
def start(update, context):
    user = update.message.from_user.first_name
    update.message.reply_text(f"Hello, {user}! I’m your Linux Terminal Bot. Send me a command to execute!\nUse 'nano <filename>' to edit a file.")

# Function to execute terminal commands and handle nano
def execute_command(update, context):
    user_id = update.message.from_user.id
    command = update.message.text.strip()
    
    # Security: Restrict to authorized users (optional)
    allowed_users = [1094941160]  # Replace with your Telegram ID
    if user_id not in allowed_users:
        update.message.reply_text("You’re not authorized to use this bot!")
        return
    
    # Check if user is in "nano mode" (editing a file)
    if user_id in nano_state:
        filename = nano_state[user_id]
        if command.lower() == "save":
            update.message.reply_text("Please send the new file contents to save.")
        elif command.lower() == "exit":
            del nano_state[user_id]
            update.message.reply_text(f"Exited nano for {filename} without saving.")
        else:
            # Assume this is the new file content
            try:
                with open(filename, 'w') as f:
                    f.write(command)
                del nano_state[user_id]
                update.message.reply_text(f"File {filename} saved successfully!")
            except Exception as e:
                update.message.reply_text(f"Error saving file: {str(e)}")
        return
    
    # Handle nano command
    if command.startswith("nano "):
        filename = command[5:].strip()
        if not filename:
            update.message.reply_text("Please specify a filename (e.g., 'nano myfile.txt').")
            return
        try:
            # Check if file exists, create it if it doesn’t
            if not os.path.exists(filename):
                with open(filename, 'w') as f:
                    f.write("")
            # Read current file contents
            with open(filename, 'r') as f:
                content = f.read()
            nano_state[user_id] = filename
            update.message.reply_text(
                f"Opened {filename} in nano:\n\n{content}\n\n"
                "Send the new contents to edit. Reply 'save' to confirm or 'exit' to discard."
            )
        except Exception as e:
            update.message.reply_text(f"Error opening file: {str(e)}")
        return
    
    # Handle regular commands
    try:
        result = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, text=True)
        update.message.reply_text(f"Output:\n{result}")
    except subprocess.CalledProcessError as e:
        update.message.reply_text(f"Error:\n{e.output}")
    except Exception as e:
        update.message.reply_text(f"Something went wrong: {str(e)}")

# Add handlers
dp.add_handler(CommandHandler("start", start))
dp.add_handler(MessageHandler(filters.text & ~filters.command, execute_command))

# Start the bot
updater.start_polling()
print("Bot is running...")
updater.idle()
