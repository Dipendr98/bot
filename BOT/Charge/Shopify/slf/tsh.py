"""
TXT Sites Shopify Checker with Site Rotation
Handles /tsh command with intelligent site rotation on captcha/errors.
"""

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from BOT.Charge.Shopify.slf.api import autoshopify, autoshopify_with_captcha_retry
from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.Charge.Shopify.slf.site_manager import SiteRotator, get_user_sites
from BOT.Charge.Shopify.slf.single import check_card_all_sites_parallel
from BOT.helper.permissions import check_private_access
from BOT.tools.proxy import get_proxy
from BOT.helper.start import load_users
import json
import re
import asyncio
import time
from datetime import datetime

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

MAX_SITE_RETRIES = 3


def extract_cards_from_text(text: str):
    """Extract cards from text in various formats."""
    # Standard format: cc|mm|yy|cvv
    pattern1 = r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})'
    found = re.findall(pattern1, text)
    
    if found:
        cleaned = []
        for card in found:
            cc, mm, yy, cvv = card
            mm = mm.zfill(2)
            if len(yy) == 2:
                yy = "20" + yy
            cleaned.append(f"{cc}|{mm}|{yy}|{cvv}")
        return list(dict.fromkeys(cleaned))
    
    # Alternative format with various separators
    pattern2 = r'(\d{13,16})[^0-9]*(\d{1,2})[^0-9]*(\d{2,4})[^0-9]*(\d{3,4})'
    found = re.findall(pattern2, text)
    cleaned = []

    for card in found:
        cc, mm, yy, cvv = card
        mm = mm.zfill(2)
        if len(yy) == 2:
            yy = "20" + yy
        cleaned.append(f"{cc}|{mm}|{yy}|{cvv}")

    return list(dict.fromkeys(cleaned))


def get_status_flag(raw_response: str) -> str:
    """Determine proper status flag from response."""
    response_upper = str(raw_response).upper() if raw_response else ""
    
    # Errors first - Site/System issues
    if any(x in response_upper for x in [
        # Captcha/Bot detection
        "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE", "VERIFY",
        # Site errors
        "SITE_EMPTY", "SITE_HTML", "SITE_CAPTCHA", "SITE_HTTP", "SITE_CONNECTION",
        "SITE_NO_PRODUCTS", "SITE_PRODUCTS_EMPTY", "SITE_INVALID_JSON", "SITE_EMPTY_JSON",
        # Cart/Session errors
        "CART_ERROR", "CART_HTML", "CART_INVALID", "CART_CREATION",
        "SESSION_ERROR", "SESSION_ID", "SESSION_INVALID",
        # Other system errors
        "CONNECTION", "RATE LIMIT", "PRODUCT ID", "SITE NOT FOUND",
        "TIMEOUT", "FAILED", "ERROR", "BLOCKED", "PROXY", "DEAD", "EMPTY",
        "NO_AVAILABLE_PRODUCTS", "BUILD", "TAX", "DELIVERY"
    ]):
        return "Error ⚠️"
    
    # Charged
    if any(x in response_upper for x in [
        "ORDER_PLACED", "THANK YOU", "SUCCESS", "CHARGED", "COMPLETE"
    ]):
        return "Charged 💎"
    
    # CCN/Live
    if any(x in response_upper for x in [
        "3DS", "3D_SECURE", "AUTHENTICATION_REQUIRED",
        "INCORRECT_CVC", "INVALID_CVC", "CVV_MISMATCH",
        "INSUFFICIENT_FUNDS", "INCORRECT_ZIP", "INCORRECT_ADDRESS",
        "MISMATCHED", "INCORRECT_PIN"
    ]):
        return "Approved ✅"
    
    # Declined
    if any(x in response_upper for x in [
        "CARD_DECLINED", "DECLINED", "GENERIC_DECLINE", "DO_NOT_HONOR",
        "INVALID_ACCOUNT", "EXPIRED", "CARD_NOT_SUPPORTED", "TRY_AGAIN",
        "PROCESSING_ERROR", "PICKUP", "LOST", "STOLEN", "FRAUD",
        "RESTRICTED", "REVOKED", "INVALID_NUMBER", "NO_SUCH_CARD"
    ]):
        return "Declined ❌"
    
    return "Declined ❌"

async def check_card_with_rotation(user_id: str, card: str, proxy: str = None) -> tuple:
    """
    Check a card with site rotation on captcha/errors.
    Returns (response, retries, site_url)
    """
    rotator = SiteRotator(user_id, max_retries=MAX_SITE_RETRIES)
    
    if not rotator.has_sites():
        return "NO_SITES_CONFIGURED", 0, None
    
    retry_count = 0
    last_response = "UNKNOWN"
    last_site = None
    
    while retry_count < MAX_SITE_RETRIES:
        current_site = rotator.get_current_site()
        if not current_site:
            break
        
        site_url = current_site.get("url")
        last_site = site_url
        
        try:
            async with TLSAsyncSession(timeout_seconds=90, proxy=proxy) as session:
                # Use captcha-aware wrapper with 3 internal retries
                result = await autoshopify_with_captcha_retry(site_url, card, session, max_captcha_retries=3)
            
            response = str(result.get("Response", "UNKNOWN"))
            last_response = response
            
            # Check if this is a real response
            if rotator.is_real_response(response):
                rotator.mark_current_success()
                return response, retry_count, site_url
            
            # Check if we should retry
            if rotator.should_retry(response):
                retry_count += 1
                rotator.mark_current_failed()
                next_site = rotator.get_next_site()
                if not next_site:
                    break
                await asyncio.sleep(0.3)
                continue
            else:
                return response, retry_count, site_url
                
        except Exception as e:
            last_response = f"ERROR: {str(e)[:30]}"
            retry_count += 1
            next_site = rotator.get_next_site()
            if not next_site:
                break
    
    return last_response, retry_count, last_site


@Client.on_message(filters.command("tsh") & filters.reply)
async def tsh_handler(client: Client, m: Message):
    """Handle /tsh command for TXT sites checking with site rotation."""
    
    users = load_users()
    user_id = str(m.from_user.id)
    
    if user_id not in users:
        return await m.reply(
            """<pre>Access Denied 🚫</pre>
<b>You must register first using</b> <code>/register</code> <b>command.</b>""",
            parse_mode=ParseMode.HTML
        )
    
    # Get cards from reply
    cards = []
    
    if m.reply_to_message.document:
        file = await m.reply_to_message.download()
        with open(file, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        cards = extract_cards_from_text(text)
    elif m.reply_to_message.text:
        cards = extract_cards_from_text(m.reply_to_message.text)
    
    if not cards:
        return await m.reply(
            "<pre>No Cards Found ❌</pre>\n<b>Reply to a file or message containing cards.</b>",
            parse_mode=ParseMode.HTML
        )

    total_cards = len(cards)
    if total_cards > 500:
        cards = cards[:500]
        total_cards = len(cards)

    user = m.from_user
    user_sites = get_user_sites(user_id)

    if not user_sites:
        return await m.reply(
            "<pre>No Sites Found ❌</pre>\n<b>Use <code>/addurl</code> or <code>/txturl</code> to add sites.</b>",
            parse_mode=ParseMode.HTML
        )

    proxy = get_proxy(int(user_id))
    
    # Check if proxy is configured
    if not proxy:
        return await m.reply(
            """<pre>Proxy Required 🔐</pre>
━━━━━━━━━━━━━━━
<b>You haven't configured a proxy yet.</b>

<b>Proxy is required for:</b>
• Avoiding rate limits
• Better success rates
• Secure checking

<b>How to set up:</b>
<code>/setpx ip:port:user:pass</code>

<b>Example:</b>
<code>/setpx 192.168.1.1:8080:user:pass</code>
━━━━━━━━━━━━━━━
<i>Set your proxy in private chat first!</i>""",
            parse_mode=ParseMode.HTML
        )
    
    site_count = len(user_sites)
    gateway = user_sites[0].get("gateway", "Shopify") if user_sites else "Shopify"

    # Send preparing message
    status_msg = await m.reply(
        f"""<pre>✦ [#TSH] | TXT Shopify Check</pre>
━━━━━━━━━━━━━
<b>⊙ Total CC:</b> <code>{total_cards}</code>
<b>⊙ Sites:</b> <code>{site_count}</code> (parallel)
<b>⊙ Threads:</b> <code>{site_count}</code>
<b>⊙ Status:</b> <code>Preparing...</code>
━━━━━━━━━━━━━
<b>[ﾒ] Checked By:</b> {user.mention}"""
    )

    start_time = time.time()
    checked_count = 0
    charged_count = 0
    approved_count = 0
    declined_count = 0
    error_count = 0
    captcha_count = 0
    total_retries = 0

    for idx, card in enumerate(cards, start=1):
        try:
            result, retries = await check_card_all_sites_parallel(user_id, card, proxy)
            raw_response = str(result.get("Response", "UNKNOWN"))
        except Exception as e:
            raw_response, retries = f"ERROR: {str(e)[:40]}", 0
        checked_count = idx
        total_retries += retries

        response_upper = (raw_response or "").upper()
        status_flag = get_status_flag(response_upper)
        
        # Track stats
        is_charged = "Charged 💎" in status_flag
        is_approved = "Approved ✅" in status_flag
        is_error = "Error ⚠️" in status_flag
        is_captcha = any(x in response_upper for x in ["CAPTCHA", "HCAPTCHA", "RECAPTCHA"])
        
        if is_charged:
            charged_count += 1
        elif is_approved:
            approved_count += 1
        elif is_error:
            error_count += 1
        else:
            declined_count += 1
        
        if is_captcha:
            captcha_count += 1
        
        # Send result for charged/approved cards immediately
        if is_charged or is_approved:
            cc = card.split("|")[0] if "|" in card else card
            try:
                bin_data = get_bin_details(cc[:6])
                if bin_data:
                    bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')} - {bin_data.get('level', 'N/A')}"
                    bank = bin_data.get('bank', 'N/A')
                    country = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
                else:
                    bin_info = "N/A"
                    bank = "N/A"
                    country = "N/A"
            except:
                bin_info = "N/A"
                bank = "N/A"
                country = "N/A"
            
            hit_header = "CHARGED" if is_charged else "CCN LIVE"
            
            hit_message = f"""<b>[#Shopify] | {hit_header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{card}</code>
<b>[•] Gateway:</b> <code>{gateway}</code>
<b>[•] Status:</b> <code>{status_flag}</code>
<b>[•] Response:</b> <code>{raw_response}</code>
<b>[•] Retries:</b> <code>{retries}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{cc[:6]}</code>
<b>[+] Info:</b> <code>{bin_info}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {user.mention}
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━"""
            
            try:
                await m.reply(hit_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            except:
                pass
        
        # Update progress every 5 cards
        if checked_count % 5 == 0 or checked_count == total_cards:
            elapsed = time.time() - start_time
            try:
                await status_msg.edit_text(
                    f"""<pre>✦ [#TSH] | TXT Shopify Check</pre>
━━━━━━━━━━━━━
<b>🟢 Total CC:</b> <code>{total_cards}</code>
<b>💬 Progress:</b> <code>{checked_count}/{total_cards}</code>
<b>✅ Approved:</b> <code>{approved_count}</code>
<b>💎 Charged:</b> <code>{charged_count}</code>
<b>❌ Declined:</b> <code>{declined_count}</code>
<b>⚠️ Errors:</b> <code>{error_count}</code>
━━━━━━━━━━━━━
<b>🔄 Rotations:</b> <code>{total_retries}</code>
<b>⏱️ Time:</b> <code>{elapsed:.2f}s</code>
<b>[ﾒ] By:</b> {user.mention}"""
                )
            except:
                pass

    total_time = time.time() - start_time
    current_time = datetime.now().strftime("%I:%M %p")

    summary_text = f"""<pre>✦ CC Check Completed</pre>
━━━━━━━━━━━━━━━
🟢 <b>Total CC</b>     : <code>{total_cards}</code>
💬 <b>Progress</b>    : <code>{checked_count}/{total_cards}</code>
✅ <b>Approved</b>    : <code>{approved_count}</code>
💎 <b>Charged</b>     : <code>{charged_count}</code>
❌ <b>Declined</b>    : <code>{declined_count}</code>
⚠️ <b>Errors</b>      : <code>{error_count}</code>
⚠️ <b>CAPTCHA</b>     : <code>{captcha_count}</code>
━━━━━━━━━━━━━━━
⏱️ <b>Time Elapsed</b> : <code>{total_time:.2f}s</code>
👤 <b>Checked By</b> : {user.mention}
🔧 <b>Dev</b>: <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>
━━━━━━━━━━━━━━━"""

    await status_msg.edit_text(summary_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
