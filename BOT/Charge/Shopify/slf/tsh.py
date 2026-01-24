from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from BOT.Charge.Shopify.slf.slf import check_card
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.tools.proxy import get_proxy
from BOT.helper.start import load_users
import json
import re
import asyncio
import time

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None


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
    response_upper = raw_response.upper() if raw_response else ""
    
    # Errors first
    if any(x in response_upper for x in [
        "CONNECTION", "RATE LIMIT", "PRODUCT ID", "SITE NOT FOUND",
        "TIMEOUT", "FAILED", "CAPTCHA", "HCAPTCHA", "ERROR"
    ]):
        return "Error ⚠️"
    
    # Charged
    if any(x in response_upper for x in [
        "ORDER_PLACED", "THANK YOU", "SUCCESS", "CHARGED"
    ]):
        return "Charged 💎"
    
    # CCN/Live
    if any(x in response_upper for x in [
        "3DS", "INCORRECT_CVC", "INVALID_CVC", "INSUFFICIENT_FUNDS",
        "INCORRECT_ZIP", "INCORRECT_ADDRESS", "MISMATCHED"
    ]):
        return "Approved ✅"
    
    # Declined
    return "Declined ❌"

def get_user_site_info(user_id):
    try:
        with open("DATA/txtsite.json", "r") as f:
            data = json.load(f)
        return data.get(str(user_id), [])
    except Exception:
        return []

def get_site_and_gate(user_id, index):
    sites = get_user_site_info(user_id)
    if not sites:
        return None, None
    item = sites[index % len(sites)]
    return item.get("site"), item.get("gate")


@Client.on_message(filters.command("tsh") & filters.reply)
async def tsh_handler(client: Client, m: Message):
    """Handle /tsh command for TXT sites checking."""
    
    # Check if user is registered
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
        # Download and read file
        file = await m.reply_to_message.download()
        with open(file, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        cards = extract_cards_from_text(text)
    elif m.reply_to_message.text:
        # Extract from text
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
    sites = get_user_site_info(int(user_id))

    if not sites:
        return await m.reply(
            "<pre>No Sites Found ❌</pre>\n<b>Use <code>/txturl site.com</code> to add sites.</b>",
            parse_mode=ParseMode.HTML
        )

    # Proxy is optional now
    proxy = get_proxy(int(user_id))

    site, gate = get_site_and_gate(user_id, 0)

    # Step 1: Send "Preparing" message
    status_msg = await m.reply("<pre>Preparing For Check</pre>")

    start_time = time.time()
    checked_count = 0
    charged_count = 0
    approved_count = 0
    dead_count = 0
    error_count = 0

    async def update_progress():
        elapsed = time.time() - start_time
        await status_msg.edit_text(
            f"<pre>Check Started</pre>\n"
            f"━━━━━━━━━━━━━\n"
            f"⊙ <b>Total CC     :</b> <code>{total_cards}</code>\n"
            f"⊙ <b>Progress     :</b> <code>{checked_count}/{total_cards}</code> ✅\n"
            f"⊙ <b>Time Elapsed :</b> <code>{elapsed:.2f}s</code> ⏱\n"
            f"━━━━━━━━━━━━━\n"
            f"[ﾒ] <b>Checked By:</b> {user.mention}\n"
            f"⌥ <b>Dev:</b> <code>Chr1shtopher</code>"
        )
    

    await update_progress()  # Initial edit

    sem = asyncio.Semaphore(25)
    lock = asyncio.Lock()

    async def process_card(index, card):
        nonlocal checked_count, charged_count, approved_count, dead_count, error_count

        async with sem:
            site, gate = get_site_and_gate(user_id, index)
            if not site:
                async with lock:
                    checked_count += 1
                    await update_progress()
                return

            t1 = time.time()
            raw_response = await check_card(user_id, card, site=site)
            t2 = time.time()
            elapsed = t2 - t1

            async with lock:
                checked_count += 1
                if checked_count % 25 == 0 or checked_count == total_cards:
                    await update_progress()

            if "HCAPTCHA DETECTED" in raw_response.upper():
                with open("DATA/txtsite.json", "r") as f:
                    all_sites = json.load(f)

                user_sites = all_sites.get(str(user.id), [])

                # filter out the site
                new_user_sites = [s for s in user_sites if s.get("site") != site]

                if len(new_user_sites) < len(user_sites):  # site was removed
                    all_sites[str(user.id)] = new_user_sites
                    with open("DATA/txtsite.json", "w") as f:
                        json.dump(all_sites, f, indent=4)

                    await m.reply_text(f"<b>{site}</b> Has Been Removed\nDue to Captcha ⚠️")

                    if not new_user_sites:
                        await m.reply_text("❌ All sites removed due to Captcha. Checking stopped.")
                        return


            # Get proper status flag
            status_flag = get_status_flag(raw_response)
            
            # Count statistics
            async with lock:
                if "Charged" in status_flag:
                    charged_count += 1
                elif "Approved" in status_flag:
                    approved_count += 1
                elif "Error" in status_flag:
                    error_count += 1
                else:
                    dead_count += 1
            
            # Get BIN info
            cc = card.split("|")[0] if "|" in card else card
            try:
                bin_data = get_bin_details(cc[:6])
                if bin_data:
                    bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')}"
                    country = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
                else:
                    bin_info = "N/A"
                    country = "N/A"
            except:
                bin_info = "N/A"
                country = "N/A"

            message = f"""<b>[#Shopify] | TXT CHECK ✦</b>
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{card}</code>
<b>[•] Gateway:</b> <code>{gate}</code>
<b>[•] Status:</b> <code>{status_flag}</code>
<b>[•] Response:</b> <code>{raw_response}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{cc[:6]}</code> | <code>{bin_info}</code>
<b>[+] Country:</b> <code>{country}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {user.mention}
<b>[ﾒ] Time:</b> <code>{elapsed:.2f}s</code>"""

            if status_flag in ["Charged 💎", "Approved ✅"]:
                await m.reply(message, parse_mode=ParseMode.HTML)


    tasks = [asyncio.create_task(process_card(i, card)) for i, card in enumerate(cards)]

    for task in asyncio.as_completed(tasks):
        await task

    total_time = time.time() - start_time

    summary_text = f"""<b>[#Shopify] | TXT CHECK COMPLETED ✦</b>
━━━━━━━━━━━━━━━
🟢 <b>Total CC</b>     : <code>{total_cards}</code>
💎 <b>Charged</b>     : <code>{charged_count}</code>
✅ <b>Approved</b>    : <code>{approved_count}</code>
❌ <b>Declined</b>    : <code>{dead_count}</code>
⚠️ <b>Errors</b>      : <code>{error_count}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {user.mention}
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{total_time:.2f}s</code>"""

    await m.reply_to_message.reply(summary_text, parse_mode=ParseMode.HTML)
