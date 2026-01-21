import json
import httpx
import asyncio
from BOT.tools.proxy import get_proxy

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
    
    # Prepare headers for the new API
    headers = {
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
    
    # Build URL based on proxy availability
    if proxy:
        url = f"https://autosh-production-b3333.up.railway.app/process?cc={cc}&site={site}&proxy={proxy}"
    else:
        url = f"https://autosh-production-b3333.up.railway.app/process?cc={cc}&site={site}&proxy={proxy}"

    retries = 0
    while retries < 3:
        try:
            async with httpx.AsyncClient(timeout=100.0) as client:
                response = await client.get(url, headers=headers)
                data = response.json()

            # Print data if not declined or 3DS
            if not any(x in str(data.get("Response", "")).upper() for x in ("CARD_DECLINED", "3DS_REQUIRED")):
                print(data)

            response_text = str(data.get("Response", "")).upper()

            # Check for connection errors that require retry
            if (
                "SERVER DISCONNECTED WITHOUT SENDING A RESPONSE" in response_text
                or "PEER CLOSED CONNECTION WITHOUT SENDING COMPLETE MESSAGE BODY (INCOMPLETE CHUNKED READ)" in response_text
                or "552 CONNECTION ERROR" in response_text
            ):
                retries += 1
                continue  # try again
            break  # if no disconnect error, break

        except Exception as e:
            print(f"Request error: {e}")
            return "Connection Failed"

    if retries == 3:
        return "Connection Failed"

    # Response parsing below
    price = data.get("Price", "")
    response_text = str(data.get("Response", "")).upper()
    
    # Get gateway and response for logging/debugging
    gateway = data.get("Gateway", "N/A")
    resp = data.get("Response", "No Response")
    
    # Print gateway and price for debugging
    print(f"Gateway: {gateway}, Price: {price}")
    
    # Check conditions
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
