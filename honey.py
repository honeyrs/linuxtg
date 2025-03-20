import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import subprocess
import os

# Replace with your bot token from BotFather
TOKEN = "8132664143:AAGrAKwg2zZw2YUzqe1UCO1JlqPr3W_weUk"

# Store the state of which file is being "edited" by nano (per user)
nano_state = {}

# Function to handle the /start command
async def start(update, context):
    user = update.message.from_user.first_name
    await update.message.reply_text(f"Hello, {user}! I’m your Linux Terminal Bot. Send me a command to execute!\nUse 'nano <filename>' to edit a file.")

# Function to execute terminal commands and handle nano
async def execute_command(update, context):
    user_id = update.message.from_user.id
    command = update.message.text.strip()
    
    # Security: Restrict to authorized users (optional)
    allowed_users = [1094941160]  # Replace with your Telegram ID
    if user_id not in allowed_users:
        await update.message.reply_text("You’re not authorized to use this bot!")
        return
    
    # Check if user is in "nano mode" (editing a file)
    if user_id in nano_state:
        filename = nano_state[user_id]
        if command.lower() == "save":
            await update.message.reply_text("Please send the new file contents to save.")
        elif command.lower() == "exit":
            del nano_state[user_id]
            await update.message.reply_text(f"Exited nano for {filename} without saving.")
        else:
            # Assume this is the new file content
            try:
                with open(filename, 'w') as f:
                    f.write(command)
                del nano_state[user_id]
                await update.message.reply_text(f"File {filename} saved successfully!")
            except Exception as e:
                await update.message.reply_text(f"Error saving file: {str(e)}")
        return
    
    # Handle nano command
    if command.startswith("nano "):
        filename = command[5:].strip()
        if not filename:
            await update.message.reply_text("Please specify a filename (e.g., 'nano myfile.txt').")
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
            await update.message.reply_text(
                f"Opened {filename} in nano:\n\n{content}\n\n"
                "Send the new contents to edit. Reply 'save' to confirm or 'exit' to discard."
            )
        except Exception as e:
            await update.message.reply_text(f"Error opening file: {str(e)}")
        return
    
    # Handle regular commands
    try:
        result = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, text=True)
        await update.message.reply_text(f"Output:\n{result}")
    except subprocess.CalledProcessError as e:
        await update.message.reply_text(f"Error:\n{e.output}")
    except Exception as e:
        await update.message.reply_text(f"Something went wrong: {str(e)}")

# Create the Application and add handlers
application = Application.builder().token(TOKEN).build()

# Add handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, execute_command))

# Start the bot
print("Bot is running...")
application.run_polling()
