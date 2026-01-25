"""
Professional Stripe WooCommerce Auth Handler
Handles /swc and $swc commands for Stripe WooCommerce authentication.
"""

import re
from datetime import datetime
from time import time
import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

from BOT.Auth.StripeWC.api import async_check_stripe_wc
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


@Client.on_message(filters.command("swc") | filters.regex(r"^\$swc(\s|$)"))
async def handle_swc_command(client, message):
    """Handle single Stripe WooCommerce Auth command: $swc cc|mes|ano|cvv or $swc cc|mes|ano|cvv site"""

    if not message.from_user:
        return
    
    user_id = str(message.from_user.id)

    # Check if user has ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>$swc</code> <b>request is still processing.</b>\n"
            "<b>Please wait until it finishes.</b>",
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
                """<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""",
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
        def extract_card_and_site(text):
            # Match card format with optional site
            match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})(?:\s+(https?://[^\s]+))?', text)
            if match:
                card, mes, ano, cvv = match.groups()[:4]
                site = match.group(5) if match.lastindex >= 5 else None
                return card, mes, ano, cvv, site
            return None

        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                "❌ <b>Send card in format:</b>\n<code>$swc cc|mes|ano|cvv</code>\n"
                "<code>$swc cc|mes|ano|cvv site</code>\n\n"
                "<b>Examples:</b>\n"
                "<code>$swc 5312590016282230|12|2029|702</code>\n"
                "<code>$swc 5312590016282230|12|2029|702 https://grownetics.com</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        card_data = extract_card_and_site(target_text)
        if not card_data:
            return await message.reply(
                "❌ <b>Invalid card format!</b>\n"
                "<b>Use:</b> <code>$swc cc|mes|ano|cvv</code> or <code>$swc cc|mes|ano|cvv site</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        card, mes, ano, cvv, site = card_data
        fullcc = f"{card}|{mes}|{ano}|{cvv}"

        # Check credits
        available_credits = user_data["plan"].get("credits", 0)
        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if available_credits < 1:
                    return await message.reply(
                        """<pre>Notification ❗️</pre>
<b>Message :</b> <code>You Have Insufficient Credits</code>
<b>Get Credits To Use</b>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                        reply_to_message_id=message.id,
                        parse_mode=ParseMode.HTML
                    )
            except:
                return await message.reply(
                    "⚠️ Error reading your credit balance.",
                    reply_to_message_id=message.id,
                    parse_mode=ParseMode.HTML
                )

        gateway = "Stripe WooCommerce Auth"
        if site:
            gateway = f"Stripe WC [{site.split('/')[2]}]"

        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        # Send loading message
        loader_msg = await message.reply(
            f"""<pre>━━━ Stripe WooCommerce Auth ━━━</pre>
<b>Card:</b> <code>{fullcc}</code>
<b>Status:</b> <code>Processing...</code>
<b>Site:</b> <code>{site if site else 'grownetics.com'}</code>
<b>Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
━━━━━━━━━━━━━━━""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

        # Process auth
        start_time = time()
        result = await async_check_stripe_wc(card, mes, ano, cvv, site)
        end_time = time()
        timetaken = round(end_time - start_time, 2)

        # Deduct credit
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, deduct_credit, user_id)

        # Format and send response
        status = result.get("status", "error")
        response = result.get("response", "Unknown error")

        # Status emoji
        if status == "approved":
            status_emoji = "✅"
            status_text = "Approved"
            header = "APPROVED"
        elif status == "declined":
            status_emoji = "❌"
            status_text = "Declined"
            header = "DECLINED"
        else:
            status_emoji = "⚠️"
            status_text = "Error"
            header = "ERROR"

        # BIN lookup
        bin_data = get_bin_details(card[:6]) if get_bin_details else None
        if bin_data:
            vendor = bin_data.get('vendor', 'N/A')
            card_type = bin_data.get('type', 'N/A')
            level = bin_data.get('level', 'N/A')
            bank = bin_data.get('bank', 'N/A')
            country = bin_data.get('country', 'N/A')
            country_flag = bin_data.get('flag', '🏳️')
        else:
            vendor = "N/A"
            card_type = "N/A"
            level = "N/A"
            bank = "N/A"
            country = "N/A"
            country_flag = "🏳️"

        current_time = datetime.now().strftime("%I:%M %p")

        final_message = f"""<b>[#StripeWC] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>{gateway}</code>
<b>[•] Status:</b> <code>{status_text} {status_emoji}</code>
<b>[•] Response:</b> <code>{response}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{card[:6]}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type} - {level}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code> {country_flag}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{timetaken}s</code> | <b>Proxy:</b> <code>Live ⚡️</code>"""

        await loader_msg.edit(final_message, disable_web_page_preview=True, parse_mode=ParseMode.HTML)

    except Exception as e:
        print(f"Error in $swc command: {str(e)}")
        import traceback
        traceback.print_exc()
        await message.reply(
            f"<b>⚠️ An error occurred:</b>\n<code>{str(e)}</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

    finally:
        user_locks.pop(user_id, None)
