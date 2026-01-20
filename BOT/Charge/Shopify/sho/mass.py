import re
from pyrogram import Client, filters
from time import time
import asyncio
from BOT.Charge.Shopify.sho.sho import create_shopify_charge
from BOT.Charge.Shopify.sho.response import format_shopify_response
from BOT.helper.start import load_users 
from BOT.helper.permissions import check_private_access, load_allowed_groups, is_premium_user
from BOT.gc.credit import deduct_credit_bulk
# from BOT.Auth.Stripe.st import load_proxies
from pyrogram.enums import ChatType
import httpx

user_locks = {}

@Client.on_message(filters.command("msho") | filters.regex(r"^\.msho(\s|$)"))
async def handle_msho_command(client, message):

    user_id = str(message.from_user.id)

    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/msho</code> <b>request is still processing.</b>\n"
            "<b>Please wait until it finishes.</b>", reply_to_message_id=message.id
        )

    user_locks[user_id] = True  # Lock the user

    try:
          
        users = load_users()
        user_id = str(message.from_user.id)

        if user_id not in users:
            return await message.reply("""<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""", reply_to_message_id=message.id)

        # Group restriction removed - all groups can use this command
        if not await is_premium_user(message):
            return

        if not await check_private_access(message):
            return

        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        mlimit = plan_info.get("mlimit")
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")

        # Default fallback if mlimit is None (like for Owner or custom plans)
        if mlimit is None or str(mlimit).lower() in ["null", "none"]:
            mlimit = 10_000  # effectively unlimited
        else:
            mlimit = int(mlimit)

        def extract_cards(text):
            return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)

        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply("❌ Send cards!\n1 per line:\n4744721068437866|12|29|740", reply_to_message_id=message.id)

        all_cards = extract_cards(target_text)
        if not all_cards:
            return await message.reply("❌ No valid cards found!", reply_to_message_id=message.id)

        if len(all_cards) > mlimit:
            return await message.reply(f"❌ You can check max {mlimit} cards as per your plan!", reply_to_message_id=message.id)

        available_credits = user_data["plan"].get("credits", 0)
        card_count = len(all_cards)

        # Convert ∞ to skip check
        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if card_count > available_credits:
                    return await message.reply(
                        """<pre>Notification ❗️</pre>
<b>Message :</b> <code>You Have Insufficient Credits</code>
<b>Get Credits To Use</b>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""", reply_to_message_id=message.id
                    )
            except:
                return await message.reply("⚠️ Error reading your credit balance.", reply_to_message_id=message.id)


        # proxies = load_proxies()
        gateway = "M-Shopify 1.5$ [/msho]"
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        # Initial loader message
        loader_msg = await message.reply(
            f"""<pre>✦ Sync | {gateway}</pre>
<b>[⚬] Gateway -</b> <b>{gateway}</b>
<b>[⚬] CC Amount : {len(all_cards)}</b>
<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[⚬] Status :</b> <code>Processing Request..!</code>
""", reply_to_message_id=message.id
        )

        start_time = time()
        final_results = []

        for idx, fullcc in enumerate(all_cards, start=1):
            card, mes, ano, cvv = fullcc.split("|")

            async with httpx.AsyncClient(follow_redirects=True) as session:
                raw_response = await create_shopify_charge(card, mes, ano, cvv, session)

                # Check for product/gateway errors first
                if any(x in raw_response for x in ["MERCHANDISE_PRODUCT_NOT_PUBLISHED", "DELIVERY_NO_DELIVERY_STRATEGY", "REQUIRED_ARTIFACTS_UNAVAILABLE"]):
                    status_flag = "Gateway Error ⚠️"
                elif "ORDER_CONFIRMED" in raw_response:
                    status_flag = "Charged 💎"
                elif any(x in raw_response for x in ["3DS", "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP", "INSUFFICIENT_FUNDS", "INVALID_CVC ⚠️", "INCORRECT_CVC ⚠️", "3DS REQUIRED", "MISMATCHED_BILL🟢"]):
                    status_flag = "Approved ✅"
                else:
                    status_flag = "Declined ❌"

                final_results.append(f"""• <b>Card :</b> <code>{fullcc}</code>
• <b>Status :</b> <code>{status_flag}</code>
• <b>Result :</b> <code>{raw_response or "-"}</code>
━ ━ ━ ━ ━ ━━━ ━ ━ ━ ━ ━""")

                # Update after each
                ongoing_result = "\n".join(final_results)
                await loader_msg.edit(
                    f"""<pre>✦ Sync | {gateway}</pre>
{ongoing_result}
<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[⚬] Dev :</b> <a href="https://t.me/Chr1shtopher">Christopher</a>
""", disable_web_page_preview=True
                )

        end_time = time()
        timetaken = round(end_time - start_time, 2)

        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, deduct_credit_bulk, user_id, card_count)

        final_result_text = "\n".join(final_results)
        # proxy_text = proxy_status if proxy_status else "N/A"

        await loader_msg.edit(
            f"""<pre>✦ Sync | {gateway}</pre>
{final_result_text}
<b>[⚬] T/t :</b> <code>{timetaken}s</code> <b>
<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[⚬] Dev :</b> <a href="https://t.me/Chr1shtopher">Christopher</a>

""", disable_web_page_preview=True
        )

    except Exception as e:
        print(f"Error occurred: {str(e)}")

    finally:
        user_locks.pop(user_id, None)  # Always unlock