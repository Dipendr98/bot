from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from BOT.Charge.Shopify.slf.api import autoshopify  # ✅ your API function
from BOT.tools.proxy import get_proxy
from BOT.Charge.Shopify.api_endpoints import SLF_CHECK_BASE_URL
from BOT.Charge.Shopify.tls_session import TLSAsyncSession
import os
import json
import time

TXT_SITES_PATH = "DATA/txtsite.json"
TEST_CARD = "4342562842964445|04|26|568"

# API functions from slf.py
def get_site(user_id):
    with open("DATA/sites.json", "r") as f:
        sites = json.load(f)
    return sites.get(str(user_id), {}).get("site")

async def check_card(user_id, cc, site=None):
    if not site:
        site = get_site(user_id)
    if not site:
        return "Site Not Found"

    proxy = get_proxy(user_id)
    if proxy:
        url = f"{SLF_CHECK_BASE_URL}?card={cc}&site={site}&proxy={proxy}"
    else:
        url = f"{SLF_CHECK_BASE_URL}?card={cc}&site={site}"

    retries = 0
    while retries < 3:
        try:
            async with TLSAsyncSession(timeout_seconds=100) as client:
                response = await client.get(url)
                data = response.json()

            if not any(x in data for x in ("CARD_DECLINED", "3DS_REQUIRED")):
                print(data)


            response_text = data.get("Response", "").upper()

            if (
                "SERVER DISCONNECTED WITHOUT SENDING A RESPONSE" in response_text
                or "PEER CLOSED CONNECTION WITHOUT SENDING COMPLETE MESSAGE BODY (INCOMPLETE CHUNKED READ)" in response_text
                or "552 CONNECTION ERROR" in response_text
            ):
                retries += 1
                continue  # try again
            break  # if no disconnect error, break

        except Exception:
            return "Connection Failed"

    if retries == 3:
        return "Connection Failed"

    # Response parsing below
    price = data.get("Price", "")
    cc_field = data.get("cc")

    if price and "ORDER_PLACED" in response_text:
        return "ORDER_PLACED"
    elif "3DS_REQUIRED" in response_text:
        return "3DS_REQUIRED"
    elif "CARD_DECLINED" in response_text:
        return "CARD_DECLINED"
    elif "HEADER VALUE MUST BE STR OR BYTES, NOT" in response_text:
        return "Product ID ⚠️"
    elif "EXPECTING VALUE: LINE 1 COLUMN 1 (CHAR 0)" in response_text:
        return "IP Rate Limit"
    elif "DECLINED" in response_text:
        return "Site | Card Error"
    else:
        return response_text

@Client.on_message(filters.command("txturl") & filters.private)
async def txturl_handler(client, message: Message):
    args = message.command[1:]

    if len(args) < 1:
        return await message.reply("<b>❌ Please provide at least 1 site URL.</b>\nExample: <code>/txturl site1 site2</code>")

    user_id = str(message.from_user.id)
    clickableFname = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
    start_time = time.time()
    wait_msg = await message.reply("<pre>[🔍 Checking Sites... ]</pre>", reply_to_message_id=message.id)

    if not os.path.exists(TXT_SITES_PATH):
        with open(TXT_SITES_PATH, "w") as f:
            json.dump({}, f)

    with open(TXT_SITES_PATH, "r", encoding="utf-8") as f:
        all_sites = json.load(f)

    user_sites = all_sites.get(user_id, [])
    existing_sites = {entry["site"]: entry for entry in user_sites}
    supported_sites = []

    async with TLSAsyncSession(timeout_seconds=30) as session:
        for site in args:
            if site in existing_sites:
                continue  # Skip duplicates

            try:
                result = await autoshopify(site, TEST_CARD, session)
                if result and result.get("cc"):
                    gateway = result.get("Gateway", "Unknown")
                    price = result.get("Price", "N/A")
                    gate_name = f"{gateway} {price}$"
                    supported_sites.append({"site": site, "gate": gate_name})
            except Exception:
                continue

    if not supported_sites:
        return await wait_msg.edit_text("<pre>No Supported Sites Found!</pre>", parse_mode=ParseMode.HTML)

    # Save updated site list
    user_sites.extend(supported_sites)
    all_sites[user_id] = user_sites

    with open(TXT_SITES_PATH, "w", encoding="utf-8") as f:
        json.dump(all_sites, f, indent=4)

    # Prepare UI
    result_lines = ["<pre>Urls Added For Txt ~ Sync ✦</pre>"]
    for site_entry in supported_sites:
        result_lines.append(f"[⌯] <b>Site:</b> <code>{site_entry['site']}</code>")
        result_lines.append(f"[⌯] <b>Gateway:</b> <code>{site_entry['gate']}</code>\n")

    end_time = time.time()
    result_lines.append(f"[⌯] <b>Cmd:</b> <code>$tslf</code>")
    result_lines.append(f"[⌯] <b>Time Taken:</b> <code>{round(end_time - start_time, 2)} sec</code>")
    result_lines.append("━━━━━━━━━━━━━")
    result_lines.append(f"[⌯] <b>Req By:</b> {clickableFname}")

    await wait_msg.edit_text("\n".join(result_lines), parse_mode=ParseMode.HTML)


TXT_SITES_PATH = "DATA/txtsite.json"

@Client.on_message(filters.command("txtls") & filters.private)
async def txtls_handler(client, message: Message):
    user_id = str(message.from_user.id)
    clickableFname = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"

    # Check if data file exists
    if not os.path.exists(TXT_SITES_PATH):
        return await message.reply("<pre>No sites found.</pre>", parse_mode=ParseMode.HTML)

    # Load JSON
    with open(TXT_SITES_PATH, "r", encoding="utf-8") as f:
        all_sites = json.load(f)

    user_sites = all_sites.get(user_id, [])

    if not user_sites:
        return await message.reply("<pre>No sites found for you.</pre>", parse_mode=ParseMode.HTML)

    # UI message
    lines = [f"<pre>Txt Sites Linked ~ Sync ✦</pre>"]
    for site_entry in user_sites:
        lines.append(f"[⌯] <b>Site:</b> <code>{site_entry['site']}</code>")
        lines.append(f"[⌯] <b>Gateway:</b> <code>{site_entry['gate']}</code>\n")

    lines.append(f"[⌯] <b>Total Sites:</b> <code>{len(user_sites)}</code>")
    lines.append("━━━━━━━━━━━━━")
    lines.append(f"[⌯] <b>Req By:</b> {clickableFname}")

    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)

@Client.on_message(filters.command("rurl") & filters.private)
async def rurl_handler(client, message: Message):
    args = message.command[1:]
    user_id = str(message.from_user.id)

    if not args:
        return await message.reply("<b>❌ Please provide site URL(s) to remove.</b>\nExample: <code>/rurl site1 site2</code>")

    if not os.path.exists(TXT_SITES_PATH):
        return await message.reply("<pre>No sites saved yet.</pre>", parse_mode=ParseMode.HTML)

    with open(TXT_SITES_PATH, "r", encoding="utf-8") as f:
        all_sites = json.load(f)

    user_sites = all_sites.get(user_id, [])

    if not user_sites:
        return await message.reply("<pre>No sites found to remove.</pre>", parse_mode=ParseMode.HTML)

    initial_count = len(user_sites)
    removed = []

    user_sites = [entry for entry in user_sites if entry["site"] not in args or removed.append(entry["site"])]

    all_sites[user_id] = user_sites
    with open(TXT_SITES_PATH, "w", encoding="utf-8") as f:
        json.dump(all_sites, f, indent=4)

    if removed:
        return await message.reply(f"<b>✅ Removed:</b>\n<code>{', '.join(removed)}</code>", parse_mode=ParseMode.HTML)
    else:
        return await message.reply("<pre>❌ No matching site(s) found to remove.</pre>", parse_mode=ParseMode.HTML)
