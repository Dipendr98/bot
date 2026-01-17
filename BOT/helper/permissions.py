from pyrogram import Client, filters
from BOT.helper.start import load_users
from pyrogram.types import Message
import json
import os
from pyrogram.enums import ChatType
# from typing import Union

# async def check_private_access(message: Message) -> bool:
#     db = load_users()
#     user_id = str(message.from_user.id)

#     user_data = db.get(user_id)
#     if not user_data:
#         await message.reply("❌ User not found in database.")
#         return False

#     private_status = user_data.get("plan", {}).get("private", "off")
#     if private_status != "on":
#         await message.reply_text(
#             "<pre>Notification ❗️</pre>\n"
#             "<b>~ Message :</b> <code>Only For Premium Users !</code>\n"
#             "<b>~ Use Free In Chat →</b> <a href="https://t.me/SyncUI">Click Here</a>\n"
#             "━━━━━━━━━━━━━\n"
#             "<b>Type <code>/buy</code> to get Premium.</b>",
#             quote=True
#         )
#         return False

#     return True

GROUPS_FILE = "DATA/groups.json"
OWNER_ID = 6891929831  # apna user ID yahan daal

def load_allowed_groups():
    if not os.path.exists(GROUPS_FILE):
        print("Groups file not found:", GROUPS_FILE)
        return []
    with open(GROUPS_FILE, "r") as f:
        data = json.load(f)
        # print("Loaded groups:", data)
        return data

def save_allowed_groups(groups):
    with open(GROUPS_FILE, "w") as f:
        json.dump(groups, f)

async def is_premium_user(message: Message) -> bool:
    # Premium restriction removed - all users have access
    return True

async def check_private_access(message: Message) -> bool:
    # Premium restriction removed - all users have private access
    return True

# GROUPS_FILE = "DATA/groups.json"
# OWNER_ID = 6891929831  # apna user ID yahan daal

# def load_allowed_groups():
#     if not os.path.exists(GROUPS_FILE):
#         print("Groups file not found:", GROUPS_FILE)
#         return []
#     with open(GROUPS_FILE, "r") as f:
#         data = json.load(f)
#         print("Loaded groups:", data)
#         return data

# def save_allowed_groups(groups):
#     with open(GROUPS_FILE, "w") as f:
#         json.dump(groups, f)
@Client.on_message(filters.command(["add", ".add", "$add"]) & filters.user(OWNER_ID))
async def add_group(client: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) != 2:
            return await message.reply("❌ Format: /add -100xxxx")

        chat_id = int(args[1])
        groups = load_allowed_groups()
        if chat_id in groups:
            return await message.reply("ℹ️ Already added.")

        groups.append(chat_id)
        save_allowed_groups(groups)
        await message.reply(f"✅ Group {chat_id} added.")
    except Exception as e:
        await message.reply(f"⚠️ Error: {e}")

@Client.on_message(filters.command("rmv") & filters.user(OWNER_ID))
async def remove_group(client: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) != 2:
            return await message.reply("❌ Format: /rmv -100xxxx")

        chat_id = int(args[1])
        groups = load_allowed_groups()
        if chat_id not in groups:
            return await message.reply("ℹ️ Group not in allowed list.")

        groups.remove(chat_id)
        save_allowed_groups(groups)
        await message.reply(f"✅ Group {chat_id} removed.")
    except Exception as e:
        await message.reply(f"⚠️ Error: {e}")

FILE_PATH = "DATA/groups.json"

# Ensure the file exists
if not os.path.exists(FILE_PATH):
    with open(FILE_PATH, "w") as f:
        json.dump([], f)

@Client.on_message(filters.command(["groupid", "id", "chatid"]))
async def get_group_id(client: Client, message: Message):
    """Shows the current chat ID"""
    chat_id = message.chat.id
    chat_type = message.chat.type
    chat_title = message.chat.title or "Private Chat"

    response = (
        "<b>📋 Chat Information</b>\n"
        f"<b>Chat ID:</b> <code>{chat_id}</code>\n"
        f"<b>Chat Type:</b> <code>{chat_type}</code>\n"
        f"<b>Chat Title:</b> <code>{chat_title}</code>\n\n"
        f"<i>Use this ID with /add {chat_id} to approve this group</i>"
    )
    await message.reply(response)

@Client.on_message(filters.command(["add", "rmv"]) & filters.user([6891929831]))  # Add your admin ID here
async def modify_allowed_chats(bot, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("❌ Usage: /add <chat_id> or /rmv <chat_id>")

    command = message.command[0]
    try:
        chat_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid chat ID.")

    with open(FILE_PATH, "r") as f:
        allowed = json.load(f)

    if command == "add":
        if chat_id not in allowed:
            allowed.append(chat_id)
            with open(FILE_PATH, "w") as f:
                json.dump(allowed, f, indent=4)
            return await message.reply_text(f"✅ Chat ID {chat_id} added to allowed list.")
        else:
            return await message.reply_text(f"ℹ️ Chat ID {chat_id} is already allowed.")

    elif command == "rmv":
        if chat_id in allowed:
            allowed.remove(chat_id)
            with open(FILE_PATH, "w") as f:
                json.dump(allowed, f, indent=4)
            return await message.reply_text(f"✅ Chat ID {chat_id} removed from allowed list.")
        else:
            return await message.reply_text(f"❌ Chat ID {chat_id} not found in allowed list.")