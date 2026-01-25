"""
Stripe Auth Single Card Checker
===============================
Handles /au command for Stripe authentication checks.

Uses WooCommerce site (epicalarc.com) with auto-registration for Stripe auth checks.
"""

import re
from time import time
from datetime import datetime
import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.helper.antispam import can_run_command
from BOT.gc.credit import deduct_credit, has_credits

# Import the WooCommerce Stripe checker and gate selector
from BOT.Auth.StripeAuth.wc_checker import check_stripe_wc_fullcc, determine_status
from BOT.Auth.StripeAuth.au_gate import (
    get_au_gate,
    get_au_gate_url,
    toggle_au_gate,
    gate_display_name,
)

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

user_locks = {}


def extract_card(text: str):
    """Extract card details from text in format cc|mm|yy|cvv."""
    match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
    if match:
        return match.groups()
    return None


def format_response(fullcc: str, result: dict, user_info: dict, time_taken: float) -> str:
    """Format the Stripe Auth response in professional style."""
    parts = fullcc.split("|")
    cc = parts[0] if len(parts) > 0 else "Unknown"
    
    response = result.get("response", "UNKNOWN")
    message = result.get("message", "Unknown")
    site = result.get("site", "Unknown")
    
    # Determine status and header
    status = determine_status(result)
    
    if status == "APPROVED":
        header = "APPROVED"
        status_text = "Approved ✅"
    elif status == "CCN LIVE":
        header = "CCN LIVE"
        status_text = "CCN Live ⚡"
    elif status == "DECLINED":
        header = "DECLINED"
        status_text = "Declined ❌"
    else:
        header = "ERROR"
        status_text = "Error ⚠️"
    
    # Clean up response for display
    response_display = response.replace("_", " ").title() if response else "Unknown"
    message_display = message[:80] if message else "Unknown"
    
    # BIN lookup
    bin_data = get_bin_details(cc[:6]) if get_bin_details else None
    
    if bin_data:
        bin_number = bin_data.get('bin', cc[:6])
        vendor = bin_data.get('vendor', 'N/A')
        card_type = bin_data.get('type', 'N/A')
        level = bin_data.get('level', 'N/A')
        bank = bin_data.get('bank', 'N/A')
        country = bin_data.get('country', 'N/A')
        country_flag = bin_data.get('flag', '🏳️')
    else:
        bin_number = cc[:6]
        vendor = "N/A"
        card_type = "N/A"
        level = "N/A"
        bank = "N/A"
        country = "N/A"
        country_flag = "🏳️"
    
    # Site display
    if site and site != "Unknown":
        site_display = site.replace("https://", "").replace("http://", "")[:25]
    else:
        site_display = "WC Stripe"
    
    return f"""<b>[#StripeAuth] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>Stripe Auth [{site_display}]</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{message_display}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{bin_number}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type} - {level}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code> {country_flag}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {user_info['profile']} [<code>{user_info['plan']} {user_info['badge']}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{time_taken}s</code> | Proxy: <code>Live ⚡️</code>"""


@Client.on_message(filters.command("au") | filters.regex(r"^\$au(\s|$)"))
async def handle_au_command(client: Client, message: Message):
    """
    Handle /au and $au commands for Stripe Auth checking.
    
    Uses WooCommerce Stripe auth with auto-registration.
    """
    if not message.from_user:
        return
    
    user_id = str(message.from_user.id)
    
    # Check for ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/au</code> <b>request is still processing.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    user_locks[user_id] = True
    
    try:
        users = load_users()
        
        # Check registration
        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You must register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Check credits
        if not has_credits(user_id):
            return await message.reply(
                """<pre>Notification ❗️</pre>
<b>Message:</b> <code>You Have Insufficient Credits</code>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Extract card
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]
        
        if not target_text:
            return await message.reply(
                """<pre>Card Not Found ❌</pre>
<b>Error:</b> <code>No card found in your input</code>

<b>Usage:</b> <code>/au cc|mm|yy|cvv</code>
<b>Example:</b> <code>/au 4111111111111111|12|2025|123</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                """<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>Card format is incorrect</code>

<b>Format:</b> <code>cc|mm|yy|cvv</code> or <code>cc|mm|yyyy|cvv</code>
<b>Example:</b> <code>/au 4111111111111111|12|25|123</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Antispam check
        allowed, wait_time = can_run_command(user_id, users)
        if not allowed:
            return await message.reply(
                f"""<pre>Antispam Detected ⚠️</pre>
<b>Message:</b> <code>Please wait before checking again</code>
<b>Try again in:</b> <code>{wait_time}s</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Prepare card
        card_num, mm, yy, cvv = extracted
        if len(yy) == 2:
            yy = "20" + yy
        fullcc = f"{card_num}|{mm}|{yy}|{cvv}"
        
        # Get user info
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🧿")
        profile = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
        
        user_info = {"profile": profile, "plan": plan, "badge": badge}
        
        start_time = time()
        gate_key = get_au_gate(user_id)
        site_url = get_au_gate_url(user_id)
        gate_label = gate_display_name(gate_key)

        # Show processing message
        loading_msg = await message.reply(
            f"""<pre>Processing Request...</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card:</b> <code>{fullcc}</code>
<b>• Gate:</b> <code>Stripe Auth [{gate_label}]</code>
<b>• Status:</b> <i>Registering and checking... ◐</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

        # Check card using WooCommerce Stripe checker (current gate)
        result = await check_stripe_wc_fullcc(fullcc, site_url=site_url)

        time_taken = round(time() - start_time, 2)

        # Format response
        final_message = format_response(fullcc, result, user_info, time_taken)

        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Change gate", callback_data="au_change_gate"),
                InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher"),
                InlineKeyboardButton("Plans", callback_data="plans_info")
            ]
        ])
        
        await loading_msg.edit(
            final_message,
            reply_markup=buttons,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML
        )
        
        # Deduct credit
        success, msg = deduct_credit(user_id)
        if not success:
            print(f"Credit deduction failed for user {user_id}")
        
    except Exception as e:
        print(f"Error in /au command: {e}")
        import traceback
        traceback.print_exc()
        try:
            await message.reply(
                f"<pre>Error Occurred ⚠️</pre>\n<code>{str(e)[:100]}</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        except:
            pass
    
    finally:
        user_locks.pop(user_id, None)


@Client.on_callback_query(filters.regex("^au_change_gate$"))
async def au_change_gate_callback(client: Client, cq: CallbackQuery):
    """Toggle Stripe Auth gate (epicalarc <-> shavercity) for /au and /mau."""
    if not cq.from_user:
        return
    user_id = str(cq.from_user.id)
    new_gate = toggle_au_gate(user_id)
    label = gate_display_name(new_gate)
    try:
        await cq.answer(f"Gate switched to {label}", show_alert=False)
        await cq.edit_message_text(
            f"""<pre>Stripe Auth Gate Changed</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Current gate:</b> <code>{label}</code>
<b>• Use</b> <code>/au</code> <b>or</b> <code>/mau</code> <b>to check.</b>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━""",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Change gate", callback_data="au_change_gate"),
                    InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher"),
                    InlineKeyboardButton("Plans", callback_data="plans_info")
                ]
            ]),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
