import requests
import base64
import logging

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_recaptcha_token(sitekey: str, target_domain: str = 'https://archive.org') -> str | None:
    """
    Attempts to bypass Google's invisible reCAPTCHA v2 to obtain a valid token.

    This function simulates the browser's interaction with the reCAPTCHA API to
    retrieve a token without user interaction or solving a challenge.

    Args:
        sitekey (str): The reCAPTCHA site key for the target website.
        target_domain (str): The domain where the reCAPTCHA is implemented.
                             Defaults to 'https://archive.org'.

    Returns:
        str | None: The reCAPTCHA token string if successful, otherwise None.
    """
    try:
        # --- Configuration ---
        # The co parameter is a base64-encoded version of the target domain
        co_value = base64.b64encode(target_domain.encode()).decode().rstrip('=')

        # These are the standard API endpoints for reCAPTCHA v2
        anchor_url = f'https://www.google.com/recaptcha/api2/anchor?ar=1&k={sitekey}&co={co_value}&hl=en&v=pCoGBhjs9s8EhFOHJFe8cqis&size=invisible'
        reload_url = f'https://www.google.com/recaptcha/api2/reload?k={sitekey}'

        # --- Step 1: Get the initial token from the anchor page ---
        # Use a session to maintain cookies and headers
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        })

        logger.info(f"Requesting initial token from anchor URL for sitekey: {sitekey}")
        r1 = session.get(anchor_url, timeout=30)
        r1.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

        # The initial token is embedded in the HTML response
        if 'recaptcha-token' not in r1.text:
            logger.error("Could not find 'recaptcha-token' in the anchor page response.")
            return None

        # Extract the token value from the HTML
        token1 = r1.text.split('recaptcha-token" value="')[1].split('">')[0]
        logger.info("Successfully retrieved initial token.")

        # --- Step 2: Use the initial token to get the final reload token ---
        # This payload mimics what the browser's JavaScript would send
        payload = (
            f'v=pCoGBhjs9s8EhFOHJFe8cqis'
            f'&reason=q'  # Reason for reload: 'q' often works for invisible reCAPTCHA
            f'&c={token1}'
            f'&k={sitekey}'
            f'&co={co_value}'
            f'&hl=en'
            f'&size=invisible'
        )

        headers = {'content-type': 'application/x-www-form-urlencoded'}

        logger.info("Requesting final token from reload URL.")
        r2 = session.post(reload_url, data=payload, headers=headers, timeout=30)
        r2.raise_for_status()

        # The final token is inside a JavaScript snippet in the response
        if '"rresp","' in r2.text:
            final_token = r2.text.split('"rresp","')[1].split('"')[0]
            logger.info("Successfully retrieved final reCAPTCHA token.")
            return final_token
        else:
            logger.error("Could not find 'rresp' in the reload response. The bypass may have failed or been patched.")
            logger.debug(f"Reload Response Content: {r2.text}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"A network error occurred: {e}")
        return None
    except IndexError as e:
        logger.error(f"Failed to parse the response. The HTML structure may have changed. Error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return None

# --- Example Usage ---
if __name__ == '__main__':
    # This is the sitekey from your original script, for archive.org
    SITEKEY = '6Ld64a8UAAAAAGbDwi1927ztGNw7YABQ-dqzvTN2'
    TARGET_DOMAIN = 'https://archive.org'

    print(f"Attempting to get reCAPTCHA token for {TARGET_DOMAIN}...")
    recaptcha_token = get_recaptcha_token(sitekey=SITEKEY, target_domain=TARGET_DOMAIN)

    if recaptcha_token:
        print("\n--- SUCCESS ---")
        print(f"Obtained reCAPTCHA Token: {recaptcha_token}") # Print first 50 chars
    else:
        print("\n--- FAILURE ---")
        print("Could not obtain reCAPTCHA token.")
