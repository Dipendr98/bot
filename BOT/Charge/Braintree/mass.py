"""
Mass Braintree Charge Handler
Handles /mbr command for mass Braintree checking.
"""

import re
import time
import asyncio
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access
from BOT.Charge.Braintree.api import check_braintree
from BOT.gc.credit import deduct_credit_bulk

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

user_locks = {}

def extract_cards(text):
    """Extract all cards from text."""
    return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)

def get_status_flag(status, response):
    """Determine status flag from result.
    Braintree usually returns boolean status or string result.
    """
    if status is True or str(status).lower() == "true":
        return "Charged 💎"
    elif "approved" in str(response).lower() or "ccn" in str(response).lower():
         return "Approved ✅"
    elif "declined" in str(response).lower():
        return "Declined ❌"
    else:
        # Fallback based on response content
        resp = str(response).lower()
        if "insufficient" in resp or "security code" in resp:
            return "Approved ✅"
        return "Declined ❌" # Default safely

@Client.on_message(filters.command(["mbr", "mbraintree"]) | filters.regex(r"^\.mbr(\s|$)"))
async def handle_mass_braintree(client, message):
    """
    Handle /mbr command for mass Braintree checking.
    
    Usage: /mbr (reply to list of cards)
    """
    if not message.from_user:
        return
    
    user_id = str(message.from_user.id)
    
    # Check if user has ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/mbr</code> <b>request is still processing.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    user_locks[user_id] = True
    
    try:
        users = load_users()
        
        if user_id not in users:
            return await message.reply(
                \"\"\"<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>\"\"\",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Check private access
        if not await check_private_access(message):
            return
        
        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🎟️")
        
        # Extract cards
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]
        
        if not target_text:
            return await message.reply(
                "❌ <b>Send cards!</b>\n1 per line:\n<code>4242424242424242|08|28|690</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        all_cards = extract_cards(target_text)
        if not all_cards:
            return await message.reply(
                "❌ No valid cards found!",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Check credits
        available_credits = user_data["plan"].get("credits", 0)
        card_count = len(all_cards)
        
        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if card_count > available_credits:
                    return await message.reply(
                        \"\"\"<pre>Notification ❗️</pre>
<b>Message :</b> <code>You Have Insufficient Credits</code>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>\"\"\",
                        reply_to_message_id=message.id,
                        parse_mode=ParseMode.HTML
                    )
            except:
                pass
        
        gateway = "Braintree [Pixorize]"
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"
        
        # Send loading message
        loader_msg = await message.reply(
            f\"\"\"<pre>✦ Mass Braintree Check</pre>
<b>[⚬] Gateway:</b> <code>{gateway}</code>
<b>[⚬] CC Amount:</b> <code>{card_count}</code>
<b>[⚬] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[⚬] Status:</b> <code>Processing Parallel (100 threads)...</code>\"\"\",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
        
        start_time = time.time()
        
        # Statistics
        total_cc = len(all_cards)
        charged_count = 0
        approved_count = 0
        declined_count = 0
        error_count = 0
        processed_count = 0
        
        # Parallel Processing
        BRAINTREE_CONCURRENCY = 100
        sem = asyncio.Semaphore(BRAINTREE_CONCURRENCY)
        progress_lock = asyncio.Lock()
        last_edit_time = 0
        
        async def check_one(fullcc):
            async with sem:
                try:
                    card, mes, ano, cvv = fullcc.split("|")
                    # Adapting check_braintree return
                    # check_braintree returns (status, response) or result dict? 
                    # Checking single.py, it likely returns response string logic or tuple. Assuming similar to Stripe.
                    result = await check_braintree(card, mes, ano, cvv) 
                    return fullcc, result
                except Exception as e:
                    return fullcc, {"status": False, "response": str(e)}

        tasks = [check_one(cc) for cc in all_cards]
        
        for task in asyncio.as_completed(tasks):
            fullcc, result = await task
            
            # Identify result structure
            status = False
            response = "Unknown"
            
            if isinstance(result, tuple):
                # (status, response)
                status = result[0] 
                response = result[1]
            elif isinstance(result, dict):
                status = result.get("status", False)
                response = result.get("response", str(result))
            else:
                 response = str(result)
                 # Determine status from text if boolean status not provided
                 status = "charged" in response.lower() or "success" in response.lower()

            status_flag = get_status_flag(status, response)
            
            async with progress_lock:
                # Count statistics
                if "Charged" in status_flag:
                    charged_count += 1
                elif "Approved" in status_flag:
                    approved_count += 1
                elif "Declined" in status_flag:
                    declined_count += 1
                else:
                    error_count += 1
                
                processed_count += 1
                
                # Update UI periodically
                now = time.time()
                if now - last_edit_time > 1.5 or processed_count == total_cc:
                    try:
                        await loader_msg.edit(
                            f\"\"\"<pre>✦ Mass Braintree Check</pre>
<b>[⚬] Progress:</b> <code>{processed_count}/{total_cc}</code>
<b>[⚬] Charged:</b> <code>{charged_count}</code>
<b>[⚬] Approved:</b> <code>{approved_count}</code>
<b>[⚬] Declined:</b> <code>{declined_count}</code>
<b>[⚬] Checked By:</b> {checked_by}\"\"\",
                            parse_mode=ParseMode.HTML
                        )
                        last_edit_time = now
                    except:
                        pass

            # Send hit notification
            if "Charged" in status_flag or "Approved" in status_flag:
                try:
                    card_num = fullcc.split("|")[0]
                    bin_info = "N/A"
                    country_info = "N/A"
                    try:
                        bin_data = get_bin_details(card_num[:6])
                        if bin_data:
                            bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')}"
                            country_info = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
                    except:
                        pass

                    hit_msg = (
                        f"<b>[#Braintree] | {status_flag}</b> ✦\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"<b>[•] Card:</b> <code>{fullcc}</code>\n"
                        f"<b>[•] Status:</b> <code>{status_flag}</code>\n"
                        f"<b>[•] Response:</b> <code>{response}</code>\n"
                        f"━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━\n"
                        f"<b>[+] BIN:</b> <code>{card_num[:6]}</code> | <code>{bin_info}</code>\n"
                        f"<b>[+] Country:</b> <code>{country_info}</code>\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"<b>[ﾒ] Checked By:</b> {checked_by}"
                    )
                    await message.reply(hit_msg, parse_mode=ParseMode.HTML)
                except:
                    pass
        
        end_time = time.time()
        timetaken = round(end_time - start_time, 2)
        
        # Deduct credits
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, deduct_credit_bulk, user_id, card_count)
        
        # Final completion message
        from datetime import datetime
        current_time = datetime.now().strftime("%I:%M %p")
        
        completion_message = f\"\"\"<b>[#Braintree] | MASS CHECK ✦</b>
━━━━━━━━━━━━━━━
🟢 <b>Total CC</b>     : <code>{total_cc}</code>
💬 <b>Progress</b>    : <code>{processed_count}/{total_cc}</code>
💎 <b>Charged</b>     : <code>{charged_count}</code>
✅ <b>Approved</b>    : <code>{approved_count}</code>
❌ <b>Declined</b>    : <code>{declined_count}</code>
⚠️ <b>Errors</b>      : <code>{error_count}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{timetaken}s</code> | <code>{current_time}</code>\"\"\"
        
        await loader_msg.edit(
            completion_message,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML
        )
    
    except Exception as e:
        print(f"Error in /mbr: {e}")
        import traceback
        traceback.print_exc()
        try:
            await message.reply(
                f"<b>⚠️ An error occurred:</b>\n<code>{str(e)}</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        except:
            pass
    
    finally:
        user_locks.pop(user_id, None)
