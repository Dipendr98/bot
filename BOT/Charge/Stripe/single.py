"""
Professional Stripe $20 Charge Handler
Handles /st and $st commands for Stripe charge checking.
"""

import re
from time import time
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode, ChatType

from BOT.helper.start import load_users
from BOT.helper.antispam import can_run_command
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.Charge.Stripe.api import async_stripe_charge
from BOT.Charge.Stripe.response import format_stripe_charge_response
from BOT.gc.credit import has_credits, deduct_credit

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None


def extract_card(text):
    """Extract card details from text in format cc|mm|yy|cvv"""
    match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
    if match:
        return match.groups()
    return None


@Client.on_message(filters.command(["st", "stripe"]) | filters.regex(r"^\$st(\s|$)"))
async def handle_stripe_charge(client, message):
    """
    Handle /st command for Stripe $20 Charge
    Professional implementation with BIN billing.
    
    Usage: /st cc|mm|yy|cvv
    Example: /st 4405639706340195|03|2029|734
    """
    try:
        if not message.from_user:
            return
        
        # Load users and check registration
        users = load_users()
        user_id = str(message.from_user.id)

        if user_id not in users:
            return await message.reply(
                """<pre>🚫 Access Denied</pre>
━━━━━━━━━━━━━━━
<b>You must register first!</b>
Use <code>/register</code> to create your account.""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        # Check private access
        if not await check_private_access(message):
            return

        # Check premium user
        if not await is_premium_user(message):
            return

        # Check credits
        if not has_credits(user_id):
            return await message.reply(
                """<pre>💳 Insufficient Credits</pre>
━━━━━━━━━━━━━━━
<b>You have no credits remaining.</b>
Use <code>/buy</code> to purchase credits.""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        # Extract card from command or replied message
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

<b>Usage:</b> <code>/st cc|mm|yy|cvv</code>
<b>Example:</b> <code>/st 4405639706340195|03|2029|734</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                """<pre>❌ Invalid Format</pre>
━━━━━━━━━━━━━━━
<b>Card format is incorrect!</b>

<b>Format:</b> <code>cc|mm|yy|cvv</code>
<b>Example:</b> <code>/st 4405639706340195|03|29|734</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        # Check antispam
        allowed, wait_time = can_run_command(user_id, users)
        if not allowed:
            return await message.reply(
                f"""<pre>⏳ Antispam Active</pre>
━━━━━━━━━━━━━━━
<b>Please wait before checking again.</b>
<b>Try again in:</b> <code>{wait_time}s</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        card, mes, ano, cvv = extracted
        fullcc = f"{card}|{mes}|{ano}|{cvv}"

        start_time = time()

        # Show processing message
        loading_msg = await message.reply(
            f"""<pre>🔄 Processing...</pre>
━━━━━━━━━━━━━━━
<b>Card:</b> <code>{fullcc}</code>
<b>Gate:</b> <code>Stripe $20 Charge</code>
<b>Status:</b> <i>Charging...</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

        # Check card using Stripe charge
        result = await async_stripe_charge(card, mes, ano, cvv)

        # Format response
        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🎟️")
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        user_info = {
            "plan": plan,
            "badge": badge,
            "checked_by": checked_by
        }

        final_msg = format_stripe_charge_response(fullcc, result, start_time, user_info)

        # Create buttons based on result
        status = result.get("status", "error")
        response_msg = result.get("response", "")
        
        if status == "approved":
            if "PAYMENT_SUCCESSFUL" in response_msg or "CHARGED" in response_msg:
                buttons = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("💎 Charged!", callback_data="charged_info"),
                        InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher")
                    ]
                ])
            else:
                buttons = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ CCN Live", callback_data="ccn_info"),
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

        # Send final response
        await loading_msg.edit(
            final_msg,
            reply_markup=buttons,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML
        )

        # Deduct credit
        success, msg = deduct_credit(user_id)
        if not success:
            print(f"Credit deduction failed for user {user_id}")

    except Exception as e:
        print(f"Error in /st: {e}")
        import traceback
        traceback.print_exc()
        try:
            await message.reply(
                f"""<pre>⚠️ Error Occurred</pre>
━━━━━━━━━━━━━━━
<code>{str(e)[:100]}</code>

<i>Please try again or contact support.</i>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        except:
            pass
