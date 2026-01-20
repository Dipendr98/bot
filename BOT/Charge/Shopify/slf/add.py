import httpx
import json
import os
import time
import requests
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

SITES_PATH = "DATA/sites.json"
TEST_CARD = "4342562842964445|04|26|568"

# Headers for the requests
HEADERS = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'en-IN',
    'cache-control': 'max-age=0',
    'priority': 'u=0, i',
    'sec-ch-ua': '"Chromium";v="127", "Not)A;Brand";v="99", "Microsoft Edge Simulate";v="127", "Lemur";v="127"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-platform': '"Android"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'none',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36',
}

# Ensure DATA directory exists
os.makedirs(os.path.dirname(SITES_PATH), exist_ok=True) if os.path.dirname(SITES_PATH) else None

@Client.on_message(filters.command("slfurl") & filters.private)
async def add_site_handler(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply("❌ Please provide a site URL.\n\nExample:\n`/slfurl https://example.com`")

    site = message.command[1].strip()
    
    # Basic URL validation and cleanup
    site = site.rstrip('/')  # Remove trailing slash
    if not (site.startswith("http://") or site.startswith("https://")):
        site = f"https://{site}"
    
    # Check if it's a valid Shopify store
    if "myshopify.com" not in site and "shopify.com" not in site:
        return await message.reply("❌ This doesn't appear to be a Shopify store. Please provide a valid Shopify URL.")
    
    # Construct the URL with proper proxy format
    url = f"https://autosh-production-b437.up.railway.app/process?cc={TEST_CARD}&site={site}&proxy=http://tickets:proxyon145@107.150.71.30:12345"
    
    user_id = str(message.from_user.id)

    wait_msg = await message.reply("<pre>[🔍 Checking Site..! ]</pre>", reply_to_message_id=message.id)
    start_time = time.time()

    try:
        # DEBUG: Show the URL being requested
        debug_info = f"<pre>[DEBUG] Requesting URL...</pre>"
        await wait_msg.edit_text(debug_info)
        
        # Using httpx with headers
        async with httpx.AsyncClient(timeout=90.0, headers=HEADERS) as http_client:
            response = await http_client.get(url)
            
            # DEBUG: Show response status
            debug_info += f"\n<pre>[DEBUG] Status Code: {response.status_code}</pre>"
            await wait_msg.edit_text(debug_info)
            
            # Check HTTP status
            if response.status_code != 200:
                debug_info += f"\n<pre>[DEBUG] Response Text: {response.text[:200]}</pre>"
                await wait_msg.edit_text(debug_info)
                return await wait_msg.edit_text(f"❌ API returned status: {response.status_code}\nResponse: {response.text[:200]}")
            
            data = response.json()
            
            # DEBUG: Show raw response
            debug_info += f"\n<pre>[DEBUG] Raw Response:\n{json.dumps(data, indent=2)[:300]}</pre>"
            await wait_msg.edit_text(debug_info)

        end_time = time.time()
        time_taken = round(end_time - start_time, 2)

        # Extract data from response - check multiple possible keys
        gateway = data.get("Gateway") or data.get("gateway") or data.get("gate") or "N/A"
        price = data.get("Price") or data.get("price") or data.get("amount") or "N/A"
        resp = data.get("Response") or data.get("response") or data.get("msg") or data.get("message") or "No Response"
        
        # DEBUG: Show extracted values
        debug_info += f"\n<pre>[DEBUG] Extracted:\nGateway: {gateway}\nPrice: {price}\nResponse: {resp}</pre>"
        await wait_msg.edit_text(debug_info)
        
        # Check if site is working - multiple validation checks
        site_supported = False
        
        # Check 1: If "cc" exists in response
        if "cc" in data:
            site_supported = True
        
        # Check 2: If gateway is valid (not None, not "N/A", not empty string)
        elif gateway and gateway != "N/A" and gateway.strip():
            site_supported = True
            
        # Check 3: If response contains success indicators
        elif isinstance(resp, str) and any(keyword in resp.lower() for keyword in ["success", "approved", "valid", "live", "working"]):
            site_supported = True
            
        # Check 4: If there's any valid price information
        elif price and price != "N/A" and str(price).strip() and str(price) != "0":
            site_supported = True

        if site_supported:
            # Format gateway name
            if gateway == "N/A" or not gateway:
                gate_name = f"Shopify Unknown Gateway"
            else:
                gate_name = f"Shopify {gateway}"
            
            # Add price if available
            if price and price != "N/A":
                gate_name += f" {price}$"

            # Load or create sites.json
            all_sites = {}
            if os.path.exists(SITES_PATH):
                try:
                    with open(SITES_PATH, "r", encoding="utf-8") as f:
                        all_sites = json.load(f)
                except json.JSONDecodeError:
                    all_sites = {}

            # Save/overwrite user's site and gate
            all_sites[user_id] = {
                "site": site,
                "gate": gate_name
            }

            with open(SITES_PATH, "w", encoding="utf-8") as f:
                json.dump(all_sites, f, indent=4, ensure_ascii=False)

            clickableFname = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

            return await wait_msg.edit_text(
                f"""<pre>Site Added ✅~ Chr1shtopher✦</pre>
[⌯] <b>Site:</b> <code>{site}</code> 
[⌯] <b>Gateway:</b> <code>{gate_name}</code> 
[⌯] <b>Response:</b> <code>{resp}</code> 
[⌯] <b>Cmd:</b> <code>$slf</code>
[⌯] <b>Time Taken:</b> <code>{time_taken} sec</code> 
━━━━━━━━━━━━━
[⌯] <b>Req By:</b> {clickableFname}
[⌯] <b>Dev:</b> <a href="tg://resolve?domain=Chr1shtopher">Christopher</a>""",
                parse_mode=ParseMode.HTML
            )
        else:
            # Show detailed error with response data
            error_details = f"<pre>❌ Site Not Supported</pre>\n\n"
            error_details += f"<b>Raw Response:</b>\n<code>{json.dumps(data, indent=2)[:500]}</code>\n\n"
            error_details += f"<b>Gateway:</b> <code>{gateway}</code>\n"
            error_details += f"<b>Price:</b> <code>{price}</code>\n"
            error_details += f"<b>Response:</b> <code>{resp}</code>\n"
            return await wait_msg.edit_text(error_details, parse_mode=ParseMode.HTML)

    except json.JSONDecodeError as e:
        return await wait_msg.edit_text(f"❌ Invalid JSON response from API\nError: {str(e)}\n\nResponse Text: {response.text[:200] if 'response' in locals() else 'No response'}")
    except httpx.TimeoutException:
        return await wait_msg.edit_text("❌ Request timeout (90 seconds)")
    except Exception as e:
        end_time = time.time()
        time_taken = round(end_time - start_time, 2)
        import traceback
        error_details = f"⚠️ Error: `{str(e)}`\n⏱️ Time Taken: `{time_taken} sec`\n\nTraceback:\n```{traceback.format_exc()[:500]}```"
        return await wait_msg.edit_text(error_details, parse_mode=ParseMode.MARKDOWN)

# Test command to check API directly
@Client.on_message(filters.command("testapi") & filters.private)
async def test_api_handler(bot: Client, message: Message):
    """Test the API with a sample URL"""
    test_url = "https://0d187f-c4.myshopify.com"  # Example from your code
    api_url = f"https://autosh-production-b437.up.railway.app/process?cc={TEST_CARD}&site={test_url}&proxy=http://tickets:proxyon145@107.150.71.30:12345"
    
    msg = await message.reply(f"<pre>[TEST] Testing API with:\n{api_url}</pre>", parse_mode=ParseMode.HTML)
    
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
            response = await client.get(api_url)
            
            result = f"<b>API Test Results:</b>\n"
            result += f"<b>Status Code:</b> <code>{response.status_code}</code>\n"
            result += f"<b>Response Headers:</b>\n"
            
            for key, value in response.headers.items():
                if key.lower() in ['content-type', 'content-length', 'server']:
                    result += f"  <code>{key}: {value}</code>\n"
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    result += f"\n<b>JSON Response:</b>\n<code>{json.dumps(data, indent=2)}</code>"
                except:
                    result += f"\n<b>Response Text:</b>\n<code>{response.text[:500]}</code>"
            else:
                result += f"\n<b>Error Response:</b>\n<code>{response.text[:500]}</code>"
                
        await msg.edit_text(result, parse_mode=ParseMode.HTML)
    except Exception as e:
        await msg.edit_text(f"❌ Test failed: {str(e)}")

