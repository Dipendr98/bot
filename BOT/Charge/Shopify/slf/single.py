"""
Professional Shopify Single Card Checker
Handles /sh and /slf commands for checking cards on user's saved site.
"""

import re
import json
from time import time

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

from BOT.helper.start import load_users
from BOT.helper.antispam import can_run_command
from BOT.helper.permissions import check_private_access
from BOT.gc.credit import has_credits, deduct_credit
from BOT.Charge.Shopify.slf.checkout import shopify_checkout
from BOT.Charge.Shopify.tls_session import TLSAsyncSession

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None


def extract_card(text: str):
    """Extract card details from text in format cc|mm|yy|cvv."""
    match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
    if match:
        return match.groups()
    return None


def get_user_site(user_id: str):
    """Get user's saved site from sites.json or txtsite.json."""
    try:
        # First check sites.json
        with open("DATA/sites.json", "r", encoding="utf-8") as f:
            sites = json.load(f)
        site_info = sites.get(str(user_id))
        
        if site_info:
            return site_info
        
        # Fallback to txtsite.json
        try:
            with open("DATA/txtsite.json", "r", encoding="utf-8") as f:
                txt_sites = json.load(f)
            user_txt_sites = txt_sites.get(str(user_id), [])
            if user_txt_sites and len(user_txt_sites) > 0:
                first_site = user_txt_sites[0]
                return {
                    "site": first_site.get("site"),
                    "gate": first_site.get("gate", "Shopify")
                }
        except Exception:
            pass
        
        return None
    except Exception:
        return None


def format_response(card: str, result: dict, user_info: dict) -> str:
    """Format the checkout response professionally."""
    cc, mm, yy, cvv = card.split("|")
    fullcc = f"{cc}|{mm}|{yy}|{cvv}"
    
    status = result.get("status", "UNKNOWN")
    response = result.get("response", "UNKNOWN")
    gateway = result.get("gateway", "Unknown")
    price = result.get("price", "0.00")
    time_taken = result.get("time_taken", 0)
    emoji = result.get("emoji", "❓")
    is_ccn = result.get("is_ccn", False)
    
    # Determine status display
    if status == "CHARGED":
        status_display = f"Charged {emoji}"
        header = "CHARGED"
    elif status == "CCN" or is_ccn:
        status_display = f"Approved {emoji}"
        header = "CCN LIVE"
    elif status == "DECLINED":
        status_display = f"Declined {emoji}"
        header = "DECLINED"
    else:
        status_display = f"Error {emoji}"
        header = "ERROR"
    
    # BIN lookup
    bin_info = get_bin_details(cc[:6]) if get_bin_details else None
    if bin_info:
        bin_data = f"""<b>[+] BIN:</b> <code>{bin_info.get('bin', cc[:6])}</code>
<b>[+] Info:</b> <code>{bin_info.get('vendor', 'N/A')} - {bin_info.get('type', 'N/A')} - {bin_info.get('level', 'N/A')}</code>
<b>[+] Bank:</b> <code>{bin_info.get('bank', 'N/A')}</code> 🏦
<b>[+] Country:</b> <code>{bin_info.get('country', 'N/A')}</code> {bin_info.get('flag', '🏳️')}"""
    else:
        bin_data = f"<b>[+] BIN:</b> <code>{cc[:6]}</code>"
    
    # Build message
    message = f"""<b>[#Shopify] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>Shopify {gateway} ${price}</code>
<b>[•] Status:</b> <code>{status_display}</code>
<b>[•] Response:</b> <code>{response}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
{bin_data}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {user_info['profile']} [<code>{user_info['plan']} {user_info['badge']}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{time_taken}s</code> | <b>Proxy:</b> <code>Live ⚡️</code>"""
    
    return message


@Client.on_message(filters.command(["sh", "slf"]) | filters.regex(r"^\.sh(\s|$)") | filters.regex(r"^\.slf(\s|$)"))
async def handle_sh_command(client: Client, message: Message):
    """
    Handle /sh and /slf commands for Shopify card checking.
    
    Usage:
        /sh cc|mm|yy|cvv
        /slf cc|mm|yy|cvv
        Reply to a message containing a card with /sh or /slf
    """
    try:
        # Check if message has a user
        if not message.from_user:
            return
        
        user_id = str(message.from_user.id)
        users = load_users()
        
        # Check registration
        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You must register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Check private access
        if not await check_private_access(message):
            return
        
        # Check credits
        if not has_credits(user_id):
            return await message.reply(
                """<pre>Insufficient Credits ❗️</pre>
<b>Message:</b> <code>You have no credits remaining</code>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get credits.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Check if user has a site set
        user_site_info = get_user_site(user_id)
        if not user_site_info:
            return await message.reply(
                """<pre>Site Not Found ⚠️</pre>
<b>Error:</b> <code>Please set a site first</code>

Use <code>/addurl https://store.com</code> to add a Shopify site.""",
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
                """<pre>Card Not Found ❌</pre>
<b>Error:</b> <code>No card found in your input</code>

<b>Usage:</b> <code>/sh cc|mm|yy|cvv</code>
<b>Example:</b> <code>/sh 4111111111111111|12|2025|123</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                """<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>Card format is incorrect</code>

<b>Format:</b> <code>cc|mm|yy|cvv</code> or <code>cc|mm|yyyy|cvv</code>
<b>Example:</b> <code>/sh 4111111111111111|12|25|123</code>""",
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
        
        # Prepare card and site info
        card_num, mm, yy, cvv = extracted
        fullcc = f"{card_num}|{mm}|{yy}|{cvv}"
        site = user_site_info['site']
        gate = user_site_info.get('gate', 'Shopify')
        
        # Get user info for response
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")
        profile = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
        
        user_info = {
            "profile": profile,
            "plan": plan,
            "badge": badge
        }
        
        # Show processing message
        loading_msg = await message.reply(
            f"""<pre>Processing Request...</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card:</b> <code>{fullcc}</code>
<b>• Gate:</b> <code>{gate}</code>
<b>• Status:</b> <i>Checking...</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
        
        # Perform checkout
        try:
            async with TLSAsyncSession(timeout_seconds=90) as session:
                result = await shopify_checkout(site, fullcc, session)
        except Exception as e:
            result = {
                "status": "ERROR",
                "response": str(e)[:80],
                "gateway": "Unknown",
                "price": "0.00",
                "time_taken": 0,
                "emoji": "⚠️",
                "is_ccn": False
            }
        
        # Format and send response
        final_message = format_response(fullcc, result, user_info)
        
        buttons = InlineKeyboardMarkup([
            [
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
        print(f"Error in /sh command: {e}")
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
