# from pyrogram import Client, filters
# from pyrogram.types import Message
# from pyrogram.enums import ParseMode
# import httpx, os, json, time

# TXT_SITES_PATH = "DATA/txtsite.json"
# TEST_CARD = "4342562842964445|04|26|568"

# @Client.on_message(filters.command("txturl") & filters.private)
# async def txturl_handler(client, message: Message):
#     args = message.command[1:]

#     if len(args) < 1:
#         return await message.reply("<b>❌ Please provide at least 1 site URL.</b>\nExample: <code>/txturl site1 site2</code>")

#     user_id = str(message.from_user.id)
#     clickableFname = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
#     start_time = time.time()
#     wait_msg = await message.reply("<pre>[🔍 Checking Site..! ]</pre>", reply_to_message_id=message.id)

#     if not os.path.exists(TXT_SITES_PATH):
#         with open(TXT_SITES_PATH, "w") as f:
#             json.dump({}, f)

#     with open(TXT_SITES_PATH, "r", encoding="utf-8") as f:
#         all_sites = json.load(f)

#     user_sites = all_sites.get(user_id, [])
#     existing_sites = {entry["site"]: entry for entry in user_sites}
#     supported_sites = []

#     async with httpx.AsyncClient(timeout=90.0) as http_client:
#         for site in args:
#             if site in existing_sites:
#                 continue  # Skip duplicates

#             try:
#                 # url = f"https://autoshopi-19b130e0563d.herokuapp.com/?site={site}&cc={TEST_CARD}"
#                 url = f"http://69.62.117.8:8000/check?card={TEST_CARD}&site={site}&sync=false"
#                 response = await http_client.get(url)
#                 data = response.json()

#                 if "cc" in data:
#                     gateway = data.get("Gateway", "Unknown")
#                     price = data.get("Price", "N/A")
#                     gate_name = f"{gateway} {price}$"
#                     supported_sites.append({"site": site, "gate": gate_name})

#             except Exception:
#                 continue

#     if not supported_sites:
#         return await wait_msg.edit_text("<pre>No Supported Sites Found!</pre>", parse_mode=ParseMode.HTML)

#     user_sites.extend(supported_sites)
#     all_sites[user_id] = user_sites

#     with open(TXT_SITES_PATH, "w", encoding="utf-8") as f:
#         json.dump(all_sites, f, indent=4)

#     result_lines = ["<pre>Urls Added For Txt ~ Sync ✦</pre>"]
#     for site_entry in supported_sites:
#         result_lines.append(f"[⌯] <b>Site:</b> <code>{site_entry['site']}</code>")
#         result_lines.append(f"[⌯] <b>Gateway:</b> <code>{site_entry['gate']}</code>\n")

#     end_time = time.time()
#     result_lines.append(f"[⌯] <b>Cmd:</b> <code>$tslf</code>")
#     result_lines.append(f"[⌯] <b>Time Taken:</b> <code>{round(end_time - start_time, 2)} sec</code>")
#     result_lines.append("━━━━━━━━━━━━━")
#     result_lines.append(f"[⌯] <b>Req By:</b> {clickableFname}")

#     await wait_msg.edit_text("\n".join(result_lines), parse_mode=ParseMode.HTML)

# TXT_SITES_PATH = "DATA/txtsite.json"

# @Client.on_message(filters.command("txtls") & filters.private)
# async def txtls_handler(client, message: Message):
#     user_id = str(message.from_user.id)
#     clickableFname = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"

#     # Check if data file exists
#     if not os.path.exists(TXT_SITES_PATH):
#         return await message.reply("<pre>No sites found.</pre>", parse_mode=ParseMode.HTML)

#     # Load JSON
#     with open(TXT_SITES_PATH, "r", encoding="utf-8") as f:
#         all_sites = json.load(f)

#     user_sites = all_sites.get(user_id, [])

#     if not user_sites:
#         return await message.reply("<pre>No sites found for you.</pre>", parse_mode=ParseMode.HTML)

#     # UI message
#     lines = [f"<pre>Txt Sites Linked ~ Sync ✦</pre>"]
#     for site_entry in user_sites:
#         lines.append(f"[⌯] <b>Site:</b> <code>{site_entry['site']}</code>")
#         lines.append(f"[⌯] <b>Gateway:</b> <code>{site_entry['gate']}</code>\n")

#     lines.append(f"[⌯] <b>Total Sites:</b> <code>{len(user_sites)}</code>")
#     lines.append("━━━━━━━━━━━━━")
#     lines.append(f"[⌯] <b>Req By:</b> {clickableFname}")

#     await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)

# @Client.on_message(filters.command("rurl") & filters.private)
# async def rurl_handler(client, message: Message):
#     args = message.command[1:]
#     user_id = str(message.from_user.id)

#     if not args:
#         return await message.reply("<b>❌ Please provide site URL(s) to remove.</b>\nExample: <code>/rurl site1 site2</code>")

#     if not os.path.exists(TXT_SITES_PATH):
#         return await message.reply("<pre>No sites saved yet.</pre>", parse_mode=ParseMode.HTML)

#     with open(TXT_SITES_PATH, "r", encoding="utf-8") as f:
#         all_sites = json.load(f)

#     user_sites = all_sites.get(user_id, [])

#     if not user_sites:
#         return await message.reply("<pre>No sites found to remove.</pre>", parse_mode=ParseMode.HTML)

#     initial_count = len(user_sites)
#     removed = []

#     user_sites = [entry for entry in user_sites if entry["site"] not in args or removed.append(entry["site"])]

#     all_sites[user_id] = user_sites
#     with open(TXT_SITES_PATH, "w", encoding="utf-8") as f:
#         json.dump(all_sites, f, indent=4)

#     if removed:
#         return await message.reply(f"<b>✅ Removed:</b>\n<code>{', '.join(removed)}</code>", parse_mode=ParseMode.HTML)
#     else:
#         return await message.reply("<pre>❌ No matching site(s) found to remove.</pre>", parse_mode=ParseMode.HTML)

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from BOT.Charge.Shopify.slf.api import autoshopify  # ✅ your API function
import httpx, os, json, time

TXT_SITES_PATH = "DATA/txtsite.json"
TEST_CARD = "4342562842964445|04|26|568"

def normalize_url(site: str) -> str:
    """Normalize site URL by adding https:// if missing and cleaning up."""
    site = site.strip()
    # Remove trailing slashes
    site = site.rstrip('/')
    # Add https:// if no protocol specified
    if not site.startswith(('http://', 'https://')):
        site = f'https://{site}'
    return site

@Client.on_message(filters.command("txturl") & filters.private)
async def txturl_handler(client, message: Message):
    args = message.command[1:]

    if len(args) < 1:
        return await message.reply("<b>❌ Please provide at least 1 site URL.</b>\nExample: <code>/txturl site1.com site2.com</code>")

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
    failed_sites = []

    async with httpx.AsyncClient(timeout=30) as session:
        for i, site in enumerate(args, 1):
            # Normalize URL
            try:
                normalized_site = normalize_url(site)
            except Exception as e:
                failed_sites.append({"site": site, "reason": f"Invalid URL format: {str(e)}"})
                continue

            if normalized_site in existing_sites:
                failed_sites.append({"site": site, "reason": "Already exists"})
                continue

            # Update progress
            await wait_msg.edit_text(f"<pre>[🔍 Checking Sites... {i}/{len(args)}]</pre>", parse_mode=ParseMode.HTML)

            try:
                result = await autoshopify(normalized_site, TEST_CARD, session)
                if result and result.get("cc"):
                    gateway = result.get("Gateway", "Unknown")
                    price = result.get("Price", "N/A")
                    gate_name = f"{gateway} {price}$"
                    supported_sites.append({"site": normalized_site, "gate": gate_name})
                else:
                    # Site didn't return valid card info
                    reason = result.get("Response", "Not supported") if result else "No response"
                    # Shorten common DNS errors
                    if "Name or service not known" in reason:
                        reason = "Invalid domain (DNS error)"
                    elif "RECEIPT EMPTY" in reason:
                        reason = "Gateway not supported"
                    failed_sites.append({"site": site, "reason": reason})
            except Exception as e:
                error_msg = str(e)
                if "Name or service not known" in error_msg:
                    error_msg = "Invalid domain (DNS error)"
                failed_sites.append({"site": site, "reason": error_msg})

    # Save supported sites
    if supported_sites:
        user_sites.extend(supported_sites)
        all_sites[user_id] = user_sites
        with open(TXT_SITES_PATH, "w", encoding="utf-8") as f:
            json.dump(all_sites, f, indent=4)

    # Prepare UI
    result_lines = []

    if supported_sites:
        result_lines.append("<pre>✅ Urls Added For Txt ~ Sync ✦</pre>")
        for site_entry in supported_sites:
            result_lines.append(f"[⌯] <b>Site:</b> <code>{site_entry['site']}</code>")
            result_lines.append(f"[⌯] <b>Gateway:</b> <code>{site_entry['gate']}</code>\n")

    if failed_sites:
        result_lines.append("<pre>❌ Failed Sites</pre>")
        for failed in failed_sites:
            result_lines.append(f"[✗] <b>Site:</b> <code>{failed['site']}</code>")
            result_lines.append(f"[✗] <b>Reason:</b> <code>{failed['reason']}</code>\n")

    if not supported_sites and not failed_sites:
        return await wait_msg.edit_text("<pre>No Sites Processed!</pre>", parse_mode=ParseMode.HTML)

    end_time = time.time()
    result_lines.append(f"[⌯] <b>Success:</b> <code>{len(supported_sites)}</code> | <b>Failed:</b> <code>{len(failed_sites)}</code>")
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

