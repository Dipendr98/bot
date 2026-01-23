import os
import json
import time
import httpx
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
# from BOT.Charge.Shopify.slf.api import autoshopify  # your actual API function

SITES_PATH = "DATA/sites.json"
TEST_CARD = "4342562842964445|04|26|568"

@Client.on_message(filters.command("addurl") & filters.private)
async def add_site_api_based(client, message: Message):
    if len(message.command) < 2:
        return await message.reply("❌ Please provide a site URL.\n\nExample:\n`/txturl https://example.com`")

    site = message.command[1]
    user_id = str(message.from_user.id)

    wait_msg = await message.reply("<pre>[🔍 Checking Site..! ]</pre>", reply_to_message_id=message.id)
    start_time = time.time()

    try:
        url = "http://136.175.187.188:8079/shc.php"
        payload = {
            'cc': TEST_CARD,
            'site': site,
            'proxy': "http://tickets:proxyon145@107.150.71.30:12345"
        }
        
        async with httpx.AsyncClient(timeout=90.0) as session:
            response = await session.post(url, data=payload)
            try:
                data = response.json()
            except json.JSONDecodeError:
                data = {"Response": response.text, "msg": response.text}

        end_time = time.time()
        time_taken = round(end_time - start_time, 2)

        if data.get("cc"):
            price = data.get("Price", "N/A")
            gateway = data.get("Gateway", "Unknown")
            resp = data.get("Response", "N/A")
            gate_name = f"Shopify {gateway} {price}$"

            all_sites = {}
            if os.path.exists(SITES_PATH):
                with open(SITES_PATH, "r", encoding="utf-8") as f:
                    all_sites = json.load(f)

            all_sites[user_id] = {
                "site": site,
                "gate": gate_name
            }

            with open(SITES_PATH, "w", encoding="utf-8") as f:
                json.dump(all_sites, f, indent=4)

            clickableFname = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

            return await wait_msg.edit_text(
                f"""<pre>Site Added ✅~ Sync ✦</pre>
[⌯] <b>Site:</b> <code>{site}</code> 
[⌯] <b>Gateway:</b> <code>{gate_name}</code> 
[⌯] <b>Response:</b> <code>{resp}</code> 
[⌯] <b>Cmd:</b> <code>$slf</code>
[⌯] <b>Time Taken:</b> <code>{time_taken} sec</code> 
━━━━━━━━━━━━━
[⌯] <b>Req By:</b> {clickableFname}
[⌯] <b>Dev:</b> <a href="tg://resolve?domain=SyncUI">Christopher</a>""",
                parse_mode=ParseMode.HTML
            )

        else:
            return await wait_msg.edit_text("<pre>Site Not Supported</pre>", parse_mode=ParseMode.HTML)

    except Exception as e:
        time_taken = round(time.time() - start_time, 2)
        return await wait_msg.edit_text(
            f"⚠️ Error: `{str(e)}`\n⏱️ Time Taken: `{time_taken} sec`", 
            parse_mode=ParseMode.MARKDOWN
        )
