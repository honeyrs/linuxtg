import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import subprocess
import os
import shlex

# Replace with your bot token from BotFather
TOKEN = "8132664143:AAGrAKwg2zZw2YUzqe1UCO1JlqPr3W_weUk"

# Replace with your log channel ID (optional, set to None if not used)
LOG_CHANNEL_ID = None  # e.g., -1001234567890

# Store the state of which file is being "edited" by nano (per user)
nano_state = {}

# Define user roles (persistent dictionary)
ALLOWED_USERS = {
    1094941160: "admin",  # Replace with your Telegram ID as admin
}

# Function to log messages to the log channel
async def log_to_channel(context, message):
    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=message)
        except Exception as e:
            print(f"Failed to send log: {e}")

# Function to handle the /start command
async def start(update, context):
    user = update.message.from_user.first_name
    user_id = update.message.from_user.id
    role = ALLOWED_USERS.get(user_id, "unauthorized")
    
    if role == "admin":
        await update.message.reply_text(
            f"Hello, {user}! I’m your Linux Terminal Bot.\n"
            "You have full admin access.\n"
            "Send commands or upload files!\n"
            "Use /addsudo <user_id>, /removesudo <user_id>, /addsu <user_id>, /removesu <user_id>"
        )
        await log_to_channel(context, f"Admin {user} ({user_id}) started the bot")
    elif role == "sudo":
        await update.message.reply_text(
            f"Hello, {user}! You have sudo access.\n"
            "You can upload files and run limited commands."
        )
        await log_to_channel(context, f"Sudo user {user} ({user_id}) started the bot")
    elif role == "su":
        await update.message.reply_text(
            f"Hello, {user}! You have su access.\n"
            "You can run all commands and upload files."
        )
        await log_to_channel(context, f"Su user {user} ({user_id}) started the bot")
    else:
        await update.message.reply_text("You’re not authorized to use this bot!")

# Function to add sudo user (admin only)
async def add_sudo(update, context):
    user_id = update.message.from_user.id
    if ALLOWED_USERS.get(user_id) != "admin":
        await update.message.reply_text("Only admins can add sudo users!")
        return
    
    try:
        new_sudo_id = int(context.args[0])
        if new_sudo_id in ALLOWED_USERS:
            await update.message.reply_text("This user already has a role!")
        else:
            ALLOWED_USERS[new_sudo_id] = "sudo"
            await update.message.reply_text(f"User {new_sudo_id} added as sudo.")
            await log_to_channel(context, f"Admin {user_id} added sudo user {new_sudo_id}")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /addsudo <user_id> (numeric ID)")

# Function to remove sudo user (admin only)
async def remove_sudo(update, context):
    user_id = update.message.from_user.id
    if ALLOWED_USERS.get(user_id) != "admin":
        await update.message.reply_text("Only admins can remove sudo users!")
        return
    
    try:
        sudo_id = int(context.args[0])
        if sudo_id not in ALLOWED_USERS:
            await update.message.reply_text("This user is not in the list!")
        elif ALLOWED_USERS[sudo_id] == "admin":
            await update.message.reply_text("Cannot remove admin!")
        else:
            del ALLOWED_USERS[sudo_id]
            await update.message.reply_text(f"User {sudo_id} removed from sudo.")
            await log_to_channel(context, f"Admin {user_id} removed sudo user {sudo_id}")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /removesudo <user_id> (numeric ID)")

# Function to add su user (admin only, can use restricted commands)
async def add_su(update, context):
    user_id = update.message.from_user.id
    if ALLOWED_USERS.get(user_id) != "admin":
        await update.message.reply_text("Only admins can add su users!")
        return
    
    try:
        new_su_id = int(context.args[0])
        if new_su_id in ALLOWED_USERS:
            await update.message.reply_text("This user already has a role!")
        else:
            ALLOWED_USERS[new_su_id] = "su"
            await update.message.reply_text(f"User {new_su_id} added as su.")
            await log_to_channel(context, f"Admin {user_id} added su user {new_su_id}")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /addsu <user_id> (numeric ID)")

# Function to remove su user (admin only)
async def remove_su(update, context):
    user_id = update.message.from_user.id
    if ALLOWED_USERS.get(user_id) != "admin":
        await update.message.reply_text("Only admins can remove su users!")
        return
    
    try:
        su_id = int(context.args[0])
        if su_id not in ALLOWED_USERS:
            await update.message.reply_text("This user is not in the list!")
        elif ALLOWED_USERS[su_id] == "admin":
            await update.message.reply_text("Cannot remove admin!")
        else:
            del ALLOWED_USERS[su_id]
            await update.message.reply_text(f"User {su_id} removed from su.")
            await log_to_channel(context, f"Admin {user_id} removed su user {su_id}")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /removesu <user_id> (numeric ID)")

# Function to handle file uploads
async def handle_file(update, context):
    user_id = update.message.from_user.id
    role = ALLOWED_USERS.get(user_id, "unauthorized")
    
    if role == "unauthorized":
        await update.message.reply_text("You’re not authorized to use this bot!")
        return

    document = update.message.document
    if not document:
        return

    file_name = document.file_name
    try:
        file = await document.get_file()
        await file.download_to_drive(file_name)
        await update.message.reply_text(f"File '{file_name}' uploaded successfully!")
        await log_to_channel(context, f"User {user_id} ({role}) uploaded file: {file_name}")
    except Exception as e:
        await update.message.reply_text(f"Error uploading file: {str(e)}")

# Function to sanitize and restrict commands (only for sudo users)
def is_restricted_command(command):
    parts = shlex.split(command.lower())
    if not parts:
        return True
    
    restricted = [
        "rm", "del", "unlink",  # Delete commands
        "cat", "less", "more", "tail", "head",  # Read commands
        "ls", "dir",  # List commands
        "mv", "cp",  # Move/copy commands
        "chmod", "chown",  # Permission commands
        "sudo", "su",  # Privilege escalation
        "bash", "sh", "python", "perl", "ruby",  # Shell/script execution
        "wget", "curl",  # Download commands
        "&", ";", "|", ">", "<",  # Shell operators
    ]
    
    return any(part in restricted for part in parts)

# Function to execute terminal commands and handle nano
async def execute_command(update, context):
    user_id = update.message.from_user.id
    role = ALLOWED_USERS.get(user_id, "unauthorized")
    command = update.message.text.strip()
    
    if role == "unauthorized":
        await update.message.reply_text("You’re not authorized to use this bot!")
        return
    
    # Handle nano state
    if user_id in nano_state:
        filename = nano_state[user_id]["filename"]
        if command.lower() == "done":
            try:
                with open(filename, 'w') as f:
                    f.write(nano_state[user_id]["content"])
                del nano_state[user_id]
                await update.message.reply_text(f"File {filename} saved successfully!")
                await log_to_channel(context, f"User {user_id} ({role}) saved file {filename}")
            except Exception as e:
                await update.message.reply_text(f"Error saving file: {str(e)}")
        elif command.lower() == "exit":
            del nano_state[user_id]
            await update.message.reply_text(f"Exited nano for {filename} without saving.")
            await log_to_channel(context, f"User {user_id} ({role}) exited nano for {filename}")
        else:
            nano_state[user_id]["content"] = command
            await update.message.reply_text("Content updated. Reply 'done' to save or 'exit' to discard.")
        return
    
    if command.startswith("nano "):
        filename = command[5:].strip()
        if not filename:
            await update.message.reply_text("Please specify a filename (e.g., 'nano myfile.txt').")
            return
        try:
            if not os.path.exists(filename):
                with open(filename, 'w') as f:
                    f.write("")
            with open(filename, 'r') as f:
                content = f.read()
            nano_state[user_id] = {"filename": filename, "content": content}
            await update.message.reply_text(
                f"Opened {filename} in nano:\n\n{content}\n\n"
                "Send the new contents to edit (as one message). Reply 'done' to save or 'exit' to discard."
            )
            await log_to_channel(context, f"User {user_id} ({role}) opened {filename} in nano")
        except Exception as e:
            await update.message.reply_text(f"Error opening file: {str(e)}")
        return
    
    # Apply restrictions only to sudo users
    if role == "sudo" and is_restricted_command(command):
        await update.message.reply_text("This command is restricted for sudo users!")
        return
    
    try:
        result = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, text=True)
        await update.message.reply_text(f"Output:\n{result}")
        await log_to_channel(context, f"User {user_id} ({role}) executed: {command}\nResult: {result}")
    except subprocess.CalledProcessError as e:
        await update.message.reply_text(f"Error:\n{e.output}")
        await log_to_channel(context, f"User {user_id} ({role}) executed: {command}\nError: {e.output}")
    except Exception as e:
        await update.message.reply_text(f"Something went wrong: {str(e)}")

# Create the Application and add handlers
application = Application.builder().token(TOKEN).build()

# Add handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("addsudo", add_sudo))
application.add_handler(CommandHandler("removesudo", remove_sudo))
application.add_handler(CommandHandler("addsu", add_su))
application.add_handler(CommandHandler("removesu", remove_su))
application.add_handler(MessageHandler(filters.ATTACHMENT, handle_file))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, execute_command))

# Start the bot
print("Bot is running...")
application.run_polling()
