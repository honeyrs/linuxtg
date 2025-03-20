To integrate the "nano" feature with a web-based notepad editor into your existing Telegram bot code, we'll modify it to use your VPS IP (103.125.217.22) and provide a URL-based editing experience similar to the previous example. Since your current bot uses nano in a text-based way (editing within Telegram), we'll replace that with a web editor hosted on your VPS. This requires:

A lightweight web server (e.g., Flask) running on your VPS at 103.125.217.22.
Modifications to your bot to generate and send an editing URL instead of handling content in Telegram.
Here’s how we can adapt your code:

Step 1: Set Up the Web Editor on Your VPS
First, install Flask on your VPS and create a simple web editor. SSH into your VPS (103.125.217.22) and run:

bash



sudo apt update
sudo apt install python3-pip
pip3 install flask
Create a file, e.g., editor.py, on your VPS:

python



from flask import Flask, request, render_template_string
import os

app = Flask(__name__)

# Directory to store files on the VPS
FILE_DIR = "/home/user/files"  # Adjust this path to your preferred location
os.makedirs(FILE_DIR, exist_ok=True)

@app.route('/edit/<filename>', methods=['GET', 'POST'])
def edit_file(filename):
    file_path = os.path.join(FILE_DIR, filename)
    if request.method == 'POST':
        content = request.form['content']
        with open(file_path, 'w') as f:
            f.write(content)
        return "File saved! You can close this window."
    try:
        with open(file_path, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        content = ""
    return render_template_string('''
        <h2>Editing {{ filename }}</h2>
        <form method="POST">
            <textarea name="content" rows="20" cols="80">{{ content }}</textarea><br>
            <input type="submit" value="Save">
        </form>
    ''', filename=filename, content=content)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
Run it with:

bash



python3 editor.py
This Flask app runs on port 5000 and serves a web editor at http://103.125.217.22:5000/edit/<filename>.
Ensure port 5000 is open on your VPS firewall (e.g., sudo ufw allow 5000).
For production, use gunicorn or a systemd service and add HTTPS (e.g., via Nginx and Let’s Encrypt).
Step 2: Modify Your Telegram Bot Code
Now, update your bot to use this web editor instead of the text-based nano system. Replace the nano_state logic in your code with a URL generator. Here’s the modified version:

python



import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import subprocess
import os
import shlex

# Bot configuration
TOKEN = "8132664143:AAHbaq378Q7Pw5a5bQf1xbLXmQzAZpOb-B8"
LOG_CHANNEL_ID = None  # e.g., -1001234567890
VPS_IP = "103.125.217.22"
EDITOR_URL = f"http://{VPS_IP}:5000/edit"
FILE_DIR = "/home/user/files"  # Must match the Flask app's FILE_DIR

# Store user roles
ALLOWED_USERS = {
    1094941160: "admin",  # Replace with your Telegram ID
}

# Log to channel
async def log_to_channel(context, message):
    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=message)
        except Exception as e:
            print(f"Failed to send log: {e}")

# Start command
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

# Add/remove sudo/su users (unchanged)
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

# Handle file uploads
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
        file_path = os.path.join(FILE_DIR, file_name)
        await file.download_to_drive(file_path)
        await update.message.reply_text(f"File '{file_name}' uploaded successfully!")
        await log_to_channel(context, f"User {user_id} ({role}) uploaded file: {file_name}")
    except Exception as e:
        await update.message.reply_text(f"Error uploading file: {str(e)}")

# Command restrictions for sudo users
def is_restricted_command(command):
    parts = shlex.split(command.lower())
    if not parts:
        return True
    restricted = [
        "rm", "del", "unlink", "cat", "less", "more", "tail", "head",
        "ls", "dir", "mv", "cp", "chmod", "chown", "sudo", "su",
        "bash", "sh", "python", "perl", "ruby", "wget", "curl",
        "&", ";", "|", ">", "<"
    ]
    return any(part in restricted for part in parts)

# Execute commands and handle nano
async def execute_command(update, context):
    user_id = update.message.from_user.id
    role = ALLOWED_USERS.get(user_id, "unauthorized")
    command = update.message.text.strip()
    
    if role == "unauthorized":
        await update.message.reply_text("You’re not authorized to use this bot!")
        return
    
    # Handle nano command
    if command.startswith("nano "):
        filename = command[5:].strip()
        if not filename:
            await update.message.reply_text("Please specify a filename (e.g., 'nano myfile.txt').")
            return
        file_path = os.path.join(FILE_DIR, filename)
        os.makedirs(FILE_DIR, exist_ok=True)
        if not os.path.exists(file_path):
            with open(file_path, 'w') as f:
                f.write("")  # Create empty file if it doesn’t exist
        edit_url = f"{EDITOR_URL}/{filename}"
        await update.message.reply_text(
            f"Edit '{filename}' here: {edit_url}\n"
            "Open the link, edit the file, and save it. The file will be stored on the VPS."
        )
        await log_to_channel(context, f"User {user_id} ({role}) opened nano for {filename}")
        return
    
    # Apply restrictions for sudo users
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

# Set up the application
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
Changes Made
Removed nano_state: No need to track editing state in Telegram since it’s now handled via the web editor.
Added Web Editor Integration:
Defined VPS_IP and EDITOR_URL as http://103.125.217.22:5000/edit.
When you send nano filename, it creates an empty file if it doesn’t exist and sends a URL like http://103.125.217.22:5000/edit/filename.
File Directory: Added FILE_DIR to store files, matching the Flask app’s directory.
How It Works
Setup:
Run the Flask app (editor.py) on your VPS at 103.125.217.22:5000.
Ensure the bot and Flask app use the same FILE_DIR (e.g., /home/user/files).
Run the bot script on your VPS or locally.
Usage:
Send /start to verify access.
Send nano myfile.txt to the bot.
Bot replies: Edit 'myfile.txt' here: http://103.125.217.22:5000/edit/myfile.txt.
Open the link in a browser, edit the file, and click "Save."
The file is saved to /home/user/files/myfile.txt on your VPS.
Security:
Currently, anyone with the URL can edit the file. Add authentication (e.g., a token in the URL) to secure it.
Example: Modify Flask to check a query parameter like ?token=xyz
Grok was unable to finish replying.
Please try again later or use a different model.
Retry
