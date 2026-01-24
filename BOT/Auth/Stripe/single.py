"""
Professional Stripe Auth Handler
Handles /au and $au commands for Stripe authentication checking.
"""

import re
from time import time
from datetime import datetime
import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

from BOT.Auth.Stripe.fixme import async_stripe_auth_fixme
from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.gc.credit import deduct_credit

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

user_locks = {}


def format_au_response(fullcc: str, result: dict, user_info: dict, time_taken: float) -> str:
    """Format the AU response with professional billing info."""
    parts = fullcc.split("|")
    card = parts[0] if len(parts) > 0 else "Unknown"
    bin_number = card[:6]
    
    status = result.get("status", "error")
    response = result.get("response", "UNKNOWN")
    
    # Determine status display
    if status == "approved":
        status_emoji = "✅"
        status_text = "APPROVED"
    elif status == "declined":
        status_emoji = "❌"
        status_text = "DECLINED"
    else:
        status_emoji = "⚠️"
        status_text = "ERROR"
    
    # Current time
    current_time = datetime.now().strftime("%I:%M:%S %p")
    current_date = datetime.now().strftime("%d/%m/%Y")
    
    # BIN lookup
    bin_data = get_bin_details(bin_number) if get_bin_details else None
    
    if bin_data:
        vendor = bin_data.get('vendor', 'Unknown')
        card_type = bin_data.get('type', 'Unknown')
        level = bin_data.get('level', 'Unknown')
        bank = bin_data.get('bank', 'Unknown')
        country = bin_data.get('country', 'Unknown')
        country_flag = bin_data.get('flag', '🏳️')
    else:
        vendor = "Unknown"
        card_type = "Unknown"
        level = "Unknown"
        bank = "Unknown"
        country = "Unknown"
        country_flag = "🏳️"
    
    return f"""<b>╔══════════════════════════╗
║     𝐒𝐓𝐑𝐈𝐏𝐄 𝐀𝐔𝐓𝐇 {status_emoji}     
╚══════════════════════════╝</b>

<b>┌─────── CARD DETAILS ───────┐</b>
│ <b>Card:</b> <code>{fullcc}</code>
│ <b>Status:</b> <code>{status_text} {status_emoji}</code>
│ <b>Response:</b> <code>{response}</code>
<b>└────────────────────────────┘</b>

<b>┌─────── GATEWAY INFO ───────┐</b>
│ <b>Gateway:</b> <code>Stripe Auth EcologyJobs</code>
│ <b>Amount:</b> <code>$0.00 (Auth)</code>
│ <b>Type:</b> <code>Card Verification</code>
<b>└────────────────────────────┘</b>

<b>┌──────── BIN BILLING ───────┐</b>
│ <b>BIN:</b> <code>{bin_number}</code>
│ <b>Brand:</b> <code>{vendor}</code>
│ <b>Type:</b> <code>{card_type}</code>
│ <b>Level:</b> <code>{level}</code>
│ <b>Bank:</b> <code>{bank}</code>
│ <b>Country:</b> <code>{country}</code> {country_flag}
<b>└────────────────────────────┘</b>

<b>┌──────── CHECK INFO ────────┐</b>
│ <b>Checked By:</b> {user_info['profile']}
│ <b>Plan:</b> <code>{user_info['plan']} {user_info['badge']}</code>
│ <b>Time:</b> <code>{time_taken}s</code>
│ <b>Proxy:</b> <code>Live ⚡️</code>
<b>└────────────────────────────┘</b>

<b>┌────────── RECEIPT ─────────┐</b>
│ <b>Date:</b> <code>{current_date}</code>
│ <b>Time:</b> <code>{current_time}</code>
│ <b>Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
<b>└────────────────────────────┘</b>"""


@Client.on_message(filters.command("au") | filters.regex(r"^\$au(\s|$)"))
async def handle_au_command(client, message):
    """Handle single Stripe Auth command: $au cc|mes|ano|cvv"""

    if not message.from_user:
        return
    
    user_id = str(message.from_user.id)

    # Check if user has ongoing request
    if user_id in user_locks:
        return await message.reply(
            """<pre>⏳ Please Wait</pre>
━━━━━━━━━━━━━━━
<b>Your previous request is still processing.</b>
<i>Please wait until it finishes.</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

    user_locks[user_id] = True

    try:
        # Load users
        users = load_users()

        # Check if user is registered
        if user_id not in users:
            return await message.reply(
                """<pre>🚫 Access Denied</pre>
━━━━━━━━━━━━━━━
<b>You must register first!</b>
Use <code>/register</code> to create your account.""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        # Premium check
        if not await is_premium_user(message):
            return

        # Private access check
        if not await check_private_access(message):
            return

        user_data = users[user_id]
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")

        # Extract card from command
        def extract_card(text):
            match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
            return match.groups() if match else None

        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                """<pre>❌ Card Not Found</pre>
━━━━━━━━━━━━━━━
<b>No card detected in your input!</b>

<b>Usage:</b> <code>/au cc|mm|yy|cvv</code>
<b>Example:</b> <code>/au 4744721068437866|12|29|740</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        card_data = extract_card(target_text)
        if not card_data:
            return await message.reply(
                """<pre>❌ Invalid Format</pre>
━━━━━━━━━━━━━━━
<b>Card format is incorrect!</b>

<b>Format:</b> <code>cc|mm|yy|cvv</code>
<b>Example:</b> <code>/au 4744721068437866|12|29|740</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        card, mes, ano, cvv = card_data
        fullcc = f"{card}|{mes}|{ano}|{cvv}"

        # Check credits
        available_credits = user_data["plan"].get("credits", 0)
        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if available_credits < 1:
                    return await message.reply(
                        """<pre>💳 Insufficient Credits</pre>
━━━━━━━━━━━━━━━
<b>You have no credits remaining.</b>
Use <code>/buy</code> to purchase credits.""",
                        reply_to_message_id=message.id,
                        parse_mode=ParseMode.HTML
                    )
            except:
                pass

        profile = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
        user_info = {"profile": profile, "plan": plan, "badge": badge}

        # Send loading message
        loader_msg = await message.reply(
            f"""<pre>🔄 Processing...</pre>
━━━━━━━━━━━━━━━
<b>Card:</b> <code>{fullcc}</code>
<b>Gate:</b> <code>Stripe Auth</code>
<b>Status:</b> <i>Authenticating...</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

        # Process auth
        start_time = time()
        result = await async_stripe_auth_fixme(card, mes, ano, cvv)
        time_taken = round(time() - start_time, 2)

        # Format response
        final_message = format_au_response(fullcc, result, user_info, time_taken)

        # Create buttons based on result
        status = result.get("status", "error")
        if status == "approved":
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approved!", callback_data="approved_info"),
                    InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher")
                ]
            ])
        else:
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Try Another", callback_data="try_another"),
                    InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher")
                ]
            ])

        await loader_msg.edit(
            final_message,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML,
            reply_markup=buttons
        )

        # Deduct credit
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, deduct_credit, user_id)

    except Exception as e:
        print(f"Error in $au command: {str(e)}")
        import traceback
        traceback.print_exc()
        await message.reply(
            f"""<pre>⚠️ Error Occurred</pre>
━━━━━━━━━━━━━━━
<code>{str(e)[:100]}</code>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

    finally:
        user_locks.pop(user_id, None)
