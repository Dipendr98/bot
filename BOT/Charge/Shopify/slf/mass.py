import re
import time
import asyncio
import math
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from BOT.Charge.Shopify.slf.slf import check_card, get_site  # your actual API functions
from BOT.helper.start import load_users
from BOT.tools.proxy import get_proxy
from BOT.helper.permissions import check_private_access, load_allowed_groups, is_premium_user
from BOT.gc.credit import deduct_credit_bulk

user_locks = {}

def chunk_cards(cards, size):
    for i in range(0, len(cards), size):
        yield cards[i:i + size]

def get_status_flag(raw_response):
    # Check for system errors first
    if any(error_keyword in raw_response for error_keyword in [
        "CONNECTION FAILED", "IP RATE LIMIT", "PRODUCT ID", "SITE NOT FOUND",
        "REQUEST TIMEOUT", "REQUEST FAILED", "SITE | CARD ERROR"
    ]):
        return "Error ⚠️"
    elif "ORDER_PLACED" in raw_response or "THANK YOU" in raw_response:
        return "Charged 💎"
    elif any(keyword in raw_response for keyword in [
        "3D CC", "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP",
        "INSUFFICIENT_FUNDS", "INVALID_CVC", "INCORRECT_CVC", "3DS_REQUIRED", "MISMATCHED_BILL",
        "3D_AUTHENTICATION", "INCORRECT_ZIP", "INCORRECT_ADDRESS", "CARD_DECLINED",
        "GENERIC_DECLINE", "DO_NOT_HONOR", "INVALID_ACCOUNT", "EXPIRED_CARD",
        "PROCESSING_ERROR", "CARD_NOT_SUPPORTED", "TRY_AGAIN_LATER",
        "AUTHENTICATION_REQUIRED", "PICKUP_CARD", "LOST_CARD", "STOLEN_CARD"
    ]):
        return "Approved ✅"
    else:
        return "Declined ❌"

def extract_cards(text):
    return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)

import json

def load_sites():
    with open("DATA/sites.json", "r") as f:
        return json.load(f)


@Client.on_message(filters.command("msh") | filters.regex(r"^\.mslf(\s|$)"))
async def mslf_handler(client, message):
    user_id = str(message.from_user.id)

    if not message.from_user:
        return await message.reply("❌ Cannot process this message. Comes From Channel")

    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/mslf</code> <b>request is still processing.</b>\n"
            "<b>Please wait until it finishes.</b>", reply_to_message_id=message.id
        )

    user_locks[user_id] = True

    try:
        users = load_users()

        if user_id not in users:
            return await message.reply(
                "<pre>Access Denied 🚫</pre>\n"
                "<b>You have to register first using</b> <code>/register</code> <b>command.</b>",
                reply_to_message_id=message.id
            )

        # Group approval check removed - all groups are now allowed
        # allowed_groups = load_allowed_groups()
        # if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and message.chat.id not in allowed_groups:
        #     return await message.reply(
        #         "<pre>Notification ❗️</pre>\n"
        #         "<b>~ Message :</b> <code>This Group Is Not Approved ⚠️</code>\n"
        #         "<b>~ Contact  →</b> <b>@Chr1shtopher</b>\n"
        #         "━━━━━━━━━━━━━\n"
        #         "<b>Contact Owner For Approving</b>",
        #         reply_to_message_id=message.id
        #     )

        # if not await is_premium_user(message):
        #     return

        if not await check_private_access(message):
            return

        proxy = get_proxy(user_id)
        if proxy == None:
            return await message.reply(
                "<pre>Proxy Error ❗️</pre>\n"
                "<b>~ Message :</b> <code>You Have To Add Proxy For Mass checking</code>\n"
                "<b>~ Command  →</b> <b>/setpx</b>\n",
                reply_to_message_id=message.id
            )
        
        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        mlimit = plan_info.get("mlimit")
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🎟️")

        # Default unlimited if None
        if mlimit is None or str(mlimit).lower() in ["null", "none"]:
            mlimit = 10_000
        else:
            mlimit = int(mlimit)

        sites = load_sites()
        user_site_info = None

        if user_id in sites:
            user_site_info = sites[user_id]
        else:
            # Check txtsite.json as fallback
            try:
                with open("DATA/txtsite.json") as f:
                    txt_sites = json.load(f)
                user_txt_sites = txt_sites.get(str(user_id), [])
                if user_txt_sites and len(user_txt_sites) > 0:
                    # Use the first site from txtsite.json
                    first_site = user_txt_sites[0]
                    user_site_info = {
                        "site": first_site.get("site"),
                        "gate": first_site.get("gate", "Unknown")
                    }
            except Exception:
                pass

        if not user_site_info:
            await message.reply(
                "<pre>Site Not Found ⚠️</pre>\n"
                "Error : <code>Please Set Site First</code>\n"
                "~ <code>Using /slfurl or /txturl in Bot's Private</code>",
                reply_to_message_id=message.id
            )
            return

        site = user_site_info["site"]
        gateway = user_site_info["gate"]

        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                "❌ Send cards!\n1 per line:\n4633438786747757|10|2025|298",
                reply_to_message_id=message.id
            )

        all_cards = extract_cards(target_text)
        if not all_cards:
            return await message.reply("❌ No valid cards found!", reply_to_message_id=message.id)

        if len(all_cards) > mlimit:
            return await message.reply(
                f"❌ You can check max {mlimit} cards as per your plan!",
                reply_to_message_id=message.id
            )

        available_credits = user_data.get("plan", {}).get("credits", 0)
        card_count = len(all_cards)

        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if card_count > available_credits:
                    return await message.reply(
                        "<pre>Notification ❗️</pre>\n"
                        "<b>Message :</b> <code>You Have Insufficient Credits</code>\n"
                        "<b>Get Credits To Use</b>\n"
                        "━━━━━━━━━━━━━\n"
                        "<b>Type <code>/buy</code> to get Credits.</b>",
                        reply_to_message_id=message.id
                    )
            except Exception:
                return await message.reply(
                    "⚠️ Error reading your credit balance.",
                    reply_to_message_id=message.id
                )

        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        loader_msg = await message.reply(
            f"<pre>✦ [$mslf] | M-Self Shopify</pre>"
            f"<b>[⚬] Gateway -</b> <b>{gateway}</b>\n"
            f"<b>[⚬] CC Amount : {card_count}</b>\n"
            f"<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]\n"
            f"<b>[⚬] Status :</b> <code>Processing Request..!</code>\n",
            reply_to_message_id=message.id
        )

        # start_time = time.time()
        # final_results = []

        # product_id_count = 0
        # rate_limit_count = 0

        # for idx, fullcc in enumerate(all_cards, start=1):
        #     # Use your check_card API directly (pass user_id, card)
        #     raw_response = await check_card(user_id, fullcc)

        #     if "ip rate limit" in raw_response.lower():
        #         rate_limit_count += 1
        #         if rate_limit_count >= 2:
        #             await message.reply(
        #                 "<pre>🚫 M-Self Shopify Aborted</pre>\n",
        #                 "<b>Reason :</b> <code>Site Got Rate Limit</code>\n",
        #                 "<b>Note :</b> <code>Add Another URL Using /adddurl</code>",
        #                 disable_web_page_preview=True,
        #                 reply_to_message_id=message.id
        #             )
        #             break

        #     if "product id" in raw_response.lower():
        #         product_id_count += 1
        #         if product_id_count >= 2:
        #             await message.reply(
        #                 "<pre>🚫 M-Self Shopify Aborted</pre>\n",
        #                 "<b>Reason : Site Got Rate Limit\n",
        #                 "<b>Action :</b> <code>Add Another URL Using /adddurl</code>\n",
        #                 disable_web_page_preview=True,
        #                 reply_to_message_id=message.id
        #             )
        #             break

        #     status_flag = get_status_flag(raw_response.upper())

        #     final_results.append(
        #         f"• <b>Card :</b> <code>{fullcc}</code>\n"
        #         f"• <b>Status :</b> <code>{status_flag}</code>\n"
        #         f"• <b>Result :</b> <code>{raw_response or '-'}</code>\n"
        #         "━ ━ ━ ━ ━ ━━━ ━ ━ ━ ━ ━"
        #     )

        #     # Edit after every card
        #     await loader_msg.edit(
        #         f"<pre>✦ [$mslf] | M-Self Shopify</pre>\n"
        #         + "\n".join(final_results) + "\n"
        #         f"<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]\n"
        #         f"<b>[⚬] Dev :</b> <a href='https://t.me/Chr1shtopher'>Christopher�</a>",
        #         disable_web_page_preview=True
        #     )

        # end_time = time.time()
        # timetaken = round(end_time - start_time, 2)

        # # Deduct credits after processing
        # if user_data["plan"].get("credits") != "∞":
        #     loop = asyncio.get_event_loop()
        #     await loop.run_in_executor(None, deduct_credit_bulk, user_id, card_count)

        # final_result_text = "\n".join(final_results)

        # await loader_msg.edit(
        #     f"<pre>✦ [$mslf] | M-Self Shopify</pre>\n"
        #     f"{final_result_text}\n"
        #     f"<b>[⚬] T/t :</b> <code>{timetaken}s</code>\n"
        #     f"<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]\n"
        #     f"<b>[⚬] Dev :</b> <a href='https://t.me/Chr1shtopher'>Christopher�</a>",
        #     disable_web_page_preview=True
        # )

        start_time = time.time()

        batch_size = 10
        final_results = []

        # Statistics counters
        total_cc = len(all_cards)
        approved_count = 0
        declined_count = 0
        charged_count = 0
        captcha_count = 0
        error_count = 0
        processed_count = 0

        for batch in chunk_cards(all_cards, batch_size):
            # Run check_card in parallel for current batch
            results = await asyncio.gather(*[
                check_card(user_id, card) for card in batch
            ])

            # Process results from batch
            for card, raw_response in zip(batch, results):
                status_flag = get_status_flag((raw_response or "").upper())

                # Count statistics
                if "Charged 💎" in status_flag:
                    charged_count += 1
                elif "Approved ✅" in status_flag:
                    approved_count += 1
                elif "Error ⚠️" in status_flag:
                    error_count += 1
                else:
                    declined_count += 1

                # Count CAPTCHA
                if any(x in (raw_response or "").upper() for x in ["CAPTCHA", "RECAPTCHA", "CHALLENGE"]):
                    captcha_count += 1

                processed_count += 1

                final_results.append(
                    f"• <b>Card :</b> <code>{card}</code>\n"
                    f"• <b>Status :</b> <code>{status_flag}</code>\n"
                    f"• <b>Result :</b> <code>{raw_response or '-'}</code>\n"
                    "━ ━ ━ ━ ━ ━━━ ━ ━ ━ ━ ━"
                )

            # Edit after every batch with progress
            ongoing_result = "\n".join(final_results[-10:])  # Show last 10 cards
            await loader_msg.edit(
                f"<pre>✦ [$mslf] | M-Self Shopify</pre>\n"
                f"{ongoing_result}\n"
                f"<b>💬 Progress :</b> <code>{processed_count}/{total_cc}</code>\n"
                f"<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]\n"
                f"<b>[⚬] Dev :</b> <a href='https://t.me/Chr1shtopher'>Chr1shtopher</a>",
                disable_web_page_preview=True
            )

        end_time = time.time()
        timetaken = round(end_time - start_time, 2)

        # Deduct credits after processing
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, deduct_credit_bulk, user_id, len(all_cards))

        # Final completion response with statistics
        from datetime import datetime
        current_time = datetime.now().strftime("%I:%M %p")

        completion_message = f"""<pre>✦ CC Check Completed</pre>
━━━━━━━━━━━━━━━
🟢 <b>Total CC</b>     : <code>{total_cc}</code>
💬 <b>Progress</b>    : <code>{processed_count}/{total_cc}</code>
✅ <b>Approved</b>    : <code>{approved_count}</code>
💎 <b>Charged</b>     : <code>{charged_count}</code>
❌ <b>Declined</b>    : <code>{declined_count}</code>
⚠️ <b>Errors</b>      : <code>{error_count}</code>
⚠️ <b>CAPTCHA</b>     : <code>{captcha_count}</code>
━━━━━━━━━━━━━━━
⏱️ <b>Time Elapsed :</b> <code>{timetaken}s</code>
👤 <b>Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]
🔧 <b>Dev</b>: <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>
━━━━━━━━━━━━━━━"""

        await loader_msg.edit(completion_message, disable_web_page_preview=True)

    except Exception as e:
        await message.reply(f"⚠️ Error: {e}", reply_to_message_id=message.id)

    finally:
        user_locks.pop(user_id, None)


# import re
# import time
# import asyncio
# from pyrogram import Client, filters
# from pyrogram.enums import ChatType
# from BOT.Charge.Shopify.slf.slf import check_card, get_site  # your actual API functions
# from BOT.helper.start import load_users
# from BOT.helper.permissions import check_private_access, load_allowed_groups, is_premium_user
# from BOT.gc.credit import deduct_credit_bulk

# user_locks = {}

# def get_status_flag(raw_response):
#     if "ORDER_PLACED" in raw_response or "THANK YOU" in raw_response:
#         return "Charged 💎"
#     elif any(keyword in raw_response for keyword in [
#         "3D CC", "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP",
#         "INSUFFICIENT_FUNDS", "INVALID_CVC", "INCORRECT_CVC", "3DS_REQUIRED", "MISMATCHED_BILL"
#     ]):
#         return "Approved ✅"
#     else:
#         return "Declined ❌"

# def extract_cards(text):
#     return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)

# import json

# def load_sites():
#     with open("DATA/sites.json", "r") as f:
#         return json.load(f)


# @Client.on_message(filters.command("msh") | filters.regex(r"^\.mslf(\s|$)"))
# async def mslf_handler(client, message):
#     user_id = str(message.from_user.id)

#     if not message.from_user:
#         return await message.reply("❌ Cannot process this message. Comes From Channel")

#     if user_id in user_locks:
#         return await message.reply(
#             "<pre>⚠️ Wait!</pre>\n"
#             "<b>Your previous</b> <code>/mslf</code> <b>request is still processing.</b>\n"
#             "<b>Please wait until it finishes.</b>", reply_to_message_id=message.id
#         )

#     user_locks[user_id] = True

#     try:
#         users = load_users()

#         if user_id not in users:
#             return await message.reply(
#                 "<pre>Access Denied 🚫</pre>\n"
#                 "<b>You have to register first using</b> <code>/register</code> <b>command.</b>",
#                 reply_to_message_id=message.id
#             )

#         allowed_groups = load_allowed_groups()

#         if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and message.chat.id not in allowed_groups:
#             return await message.reply(
#                 "<pre>Notification ❗️</pre>\n"
#                 "<b>~ Message :</b> <code>This Group Is Not Approved ⚠️</code>\n"
#                 "<b>~ Contact  →</b> <b>@Chr1shtopher</b>\n"
#                 "━━━━━━━━━━━━━\n"
#                 "<b>Contact Owner For Approving</b>",
#                 reply_to_message_id=message.id
#             )

#         if not await is_premium_user(message):
#             return

#         if not await check_private_access(message):
#             return

#         user_data = users[user_id]
#         plan_info = user_data.get("plan", {})
#         mlimit = plan_info.get("mlimit")
#         plan = plan_info.get("plan", "Free")
#         badge = plan_info.get("badge", "🎟️")

#         # Default unlimited if None
#         if mlimit is None or str(mlimit).lower() in ["null", "none"]:
#             mlimit = 10_000
#         else:
#             mlimit = int(mlimit)

#         sites = load_sites()
#         if user_id not in sites:
#             await message.reply(
#                 "<pre>Site Not Found ⚠️</pre>\n"
#                 "Error : <code>Please Set Site First</code>\n"
#                 "~ <code>Using /slfurl in Bot's Private</code>",
#                 reply_to_message_id=message.id
#             )
#             return

#         user_site_info = sites[user_id]
#         site = user_site_info["site"]
#         gateway = user_site_info["gate"]

#         target_text = None
#         if message.reply_to_message and message.reply_to_message.text:
#             target_text = message.reply_to_message.text
#         elif len(message.text.split(maxsplit=1)) > 1:
#             target_text = message.text.split(maxsplit=1)[1]

#         if not target_text:
#             return await message.reply(
#                 "❌ Send cards!\n1 per line:\n4633438786747757|10|2025|298",
#                 reply_to_message_id=message.id
#             )

#         all_cards = extract_cards(target_text)
#         if not all_cards:
#             return await message.reply("❌ No valid cards found!", reply_to_message_id=message.id)

#         if len(all_cards) > mlimit:
#             return await message.reply(
#                 f"❌ You can check max {mlimit} cards as per your plan!",
#                 reply_to_message_id=message.id
#             )

#         available_credits = user_data.get("plan", {}).get("credits", 0)
#         card_count = len(all_cards)

#         if available_credits != "∞":
#             try:
#                 available_credits = int(available_credits)
#                 if card_count > available_credits:
#                     return await message.reply(
#                         "<pre>Notification ❗️</pre>\n"
#                         "<b>Message :</b> <code>You Have Insufficient Credits</code>\n"
#                         "<b>Get Credits To Use</b>\n"
#                         "━━━━━━━━━━━━━\n"
#                         "<b>Type <code>/buy</code> to get Credits.</b>",
#                         reply_to_message_id=message.id
#                     )
#             except Exception:
#                 return await message.reply(
#                     "⚠️ Error reading your credit balance.",
#                     reply_to_message_id=message.id
#                 )

#         checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

#         loader_msg = await message.reply(
#             f"<pre>✦ [$mslf] | M-Self Shopify</pre>"
#             f"<b>[⚬] Gateway -</b> <b>{gateway}</b>\n"
#             f"<b>[⚬] CC Amount : {card_count}</b>\n"
#             f"<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]\n"
#             f"<b>[⚬] Status :</b> <code>Processing Request..!</code>\n",
#             reply_to_message_id=message.id
#         )

#         async def handle_card(fullcc):
#             try:
#                 raw_response = await check_card(user_id, fullcc)
#                 status_flag = get_status_flag(raw_response.upper())
#                 return f"• <b>Card :</b> <code>{fullcc}</code>\n" \
#                        f"• <b>Status :</b> <code>{status_flag}</code>\n" \
#                        f"• <b>Result :</b> <code>{raw_response or '-'}</code>\n" \
#                        "━ ━ ━ ━ ━ ━━━ ━ ━ ━ ━ ━"
#             except Exception as e:
#                 return f"• <b>Card :</b> <code>{fullcc}</code>\n" \
#                        f"• <b>Status :</b> <code>Error ❌</code>\n" \
#                        f"• <b>Result :</b> <code>{e}</code>\n" \
#                        "━ ━ ━ ━ ━ ━━━ ━ ━ ━ ━ ━"

#         start_time = time.time()

#         tasks = [handle_card(card) for card in all_cards]
#         final_results = await asyncio.gather(*tasks)

#         end_time = time.time()
#         timetaken = round(end_time - start_time, 2)

#         # Deduct credits after processing
#         if user_data["plan"].get("credits") != "∞":
#             loop = asyncio.get_event_loop()
#             await loop.run_in_executor(None, deduct_credit_bulk, user_id, card_count)

#         final_result_text = "\n".join(final_results)

#         await loader_msg.edit(
#             f"<pre>✦ [$mslf] | M-Self Shopify</pre>\n"
#             f"{final_result_text}\n"
#             f"<b>[⚬] T/t :</b> <code>{timetaken}s</code>\n"
#             f"<b>[⚬] Checked By :</b> {checked_by} [<code>{plan} {badge}</code>]\n"
#             f"<b>[⚬] Dev :</b> <a href='https://t.me/Chr1shtopher'>Christopher�</a>",
#             disable_web_page_preview=True
#         )

#     except Exception as e:
#         await message.reply(f"⚠️ Error: {e}", reply_to_message_id=message.id)

#     finally:
#         user_locks.pop(user_id, None)
