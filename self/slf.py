import json
import httpx
import asyncio
from BOT.Charge.Shopify.self.api import autoshopify
# from BOT.tools.proxy import get_proxy_for_user  

def get_site(user_id):
    with open("DATA/sites.json", "r") as f:
        sites = json.load(f)
    return sites.get(str(user_id), {}).get("site")

# def get_proxy():
#     # Your static proxy string (host:port:user:pass)
#     proxy_str = "proxy.rampageproxies.com:5000:package-1111111-country-de:D61iY2RgVSg5l9i9"
#     host, port, user, password = proxy_str.split(":")
#     return f"http://{user}:{password}@{host}:{port}"

# async def check_card(user_id, cc, site=None):
#     if not site:
#         site = get_site(user_id)
#     if not site:
#         return "Site Not Found"

#     proxy = get_proxy()

#     try:
#         async with httpx.AsyncClient(proxy=proxy, timeout=90.0) as session:
#             data = await autoshopify(site, cc, session)
#     except Exception as e:
#         print(f"Error: {e}")
#         return "API Fucked !"

#     response_text = (data.get("Response") or "Error").upper()
#     price = data.get("Price", "Error")
#     cc_field = data.get("cc")

#     if price and "ORDER_PLACED" in response_text:
#         return "ORDER_PLACED"
#     elif "3DS_REQUIRED" in response_text:
#         return "3DS_REQUIRED"
#     elif "CARD_DECLINED" in response_text:
#         return "CARD_DECLINED"
#     elif "DECLINED" in response_text:
#         return "Site | Card Error"
#     else:
#         return response_text

async def check_card(user_id, cc, site=None):
    if not site:
        site = get_site(user_id)
    if not site:
        return "Site Not Found"

    try:
        async with httpx.AsyncClient(timeout=90.0) as session:
            data = await autoshopify(site, cc, session)
    except:
        return "API Fucked !"

    response_text = (data.get("Response") or "Error").upper()
    price = data.get("Price", "Error")
    cc_field = data.get("cc")

    # if cc_field:
    if price and f"ORDER_PLACED".upper() in response_text:
        return "ORDER_PLACED"
    elif "3DS_REQUIRED" in response_text:
        return "3DS_REQUIRED"
    elif "CARD_DECLINED" in response_text:
        return "CARD_DECLINED"
    elif "Declined" in response_text:
        return "Site | Card Error "
    else:
        return response_text

