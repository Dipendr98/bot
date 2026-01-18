from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from BOT.helper.start import load_users
from BOT.Charge.Shopify.ash.url_manager import set_user_url, get_user_url, remove_user_url

@Client.on_message(filters.command(["addurl", "seturl"]))
async def handle_addurl(client, message):
    """
    Handle /addurl command to set custom AutoShopify URL

    Usage: /addurl <URL>
    Example: /addurl https://3duxdesign.myshopify.com
    """
    try:
        # Load users and check registration
        users = load_users()
        user_id = str(message.from_user.id)

        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id
            )

        # Extract URL from command
        command_parts = message.text.split(maxsplit=1)

        if len(command_parts) < 2:
            # Show current URL if no URL provided
            current_url = get_user_url(user_id)
            if current_url:
                return await message.reply(
                    f"""<pre>Custom AutoShopify URL</pre>
━━━━━━━━━━━━━━━━
<b>Your current URL:</b>
<code>{current_url}</code>

<b>To change it:</b>
<code>/addurl https://your-new-url.com</code>

<b>To remove it:</b>
<code>/removeurl</code>""",
                    reply_to_message_id=message.id
                )
            else:
                return await message.reply(
                    f"""<pre>Set Custom AutoShopify URL</pre>
━━━━━━━━━━━━━━━━
<b>You don't have a custom URL set.</b>

<b>Usage:</b>
<code>/addurl https://your-store.myshopify.com</code>

<b>Examples:</b>
<code>/addurl https://3duxdesign.myshopify.com</code>
<code>/addurl https://www.bountifulbaby.com</code>

<b>Note:</b> Your custom URL will be used first when checking cards, with automatic fallback to default URLs if it fails.""",
                    reply_to_message_id=message.id
                )

        url = command_parts[1].strip()

        # Set the URL
        success, msg = set_user_url(user_id, url)

        if success:
            await message.reply(
                f"""<pre>Custom URL Set ✅</pre>
━━━━━━━━━━━━━━━━
<b>Success!</b> Your custom AutoShopify URL has been set.

<b>URL:</b>
<code>{url}</code>

<b>How it works:</b>
• Your URL will be tried first when checking cards
• If it fails, system automatically tries 9 fallback URLs
• You can change it anytime with <code>/addurl</code>
• Remove it with <code>/removeurl</code>

<b>Test it now:</b>
<code>/autosh 4405639706340195|03|2029|734</code>""",
                reply_to_message_id=message.id
            )
        else:
            await message.reply(
                f"""<pre>Error Setting URL ❌</pre>
━━━━━━━━━━━━━━━━
<b>Error:</b> <code>{msg}</code>

<b>Make sure your URL:</b>
• Starts with http:// or https://
• Is a valid e-commerce site URL
• Can be either domain-only or full product URL

<b>Examples:</b>
<code>/addurl https://store.myshopify.com</code>
<code>/addurl https://store.myshopify.com/products/item</code>""",
                reply_to_message_id=message.id
            )

    except Exception as e:
        print(f"Error in /addurl: {e}")
        import traceback
        traceback.print_exc()
        await message.reply(
            "<code>Internal Error Occurred. Try again later.</code>",
            reply_to_message_id=message.id
        )


@Client.on_message(filters.command(["removeurl", "deleteurl", "clearurl"]))
async def handle_removeurl(client, message):
    """
    Handle /removeurl command to remove custom AutoShopify URL

    Usage: /removeurl
    """
    try:
        # Load users and check registration
        users = load_users()
        user_id = str(message.from_user.id)

        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id
            )

        # Remove the URL
        success, msg = remove_user_url(user_id)

        if success:
            await message.reply(
                f"""<pre>Custom URL Removed ✅</pre>
━━━━━━━━━━━━━━━━
<b>Your custom URL has been removed.</b>

The system will now use default fallback URLs:
• https://www.bountifulbaby.com
• https://3duxdesign.myshopify.com
• And 7 more Shopify stores

<b>To set a new custom URL:</b>
<code>/addurl https://your-store.com</code>""",
                reply_to_message_id=message.id
            )
        else:
            await message.reply(
                f"""<pre>No Custom URL Found</pre>
━━━━━━━━━━━━━━━━
<b>Message:</b> <code>{msg}</code>

<b>To set a custom URL:</b>
<code>/addurl https://your-store.myshopify.com</code>""",
                reply_to_message_id=message.id
            )

    except Exception as e:
        print(f"Error in /removeurl: {e}")
        import traceback
        traceback.print_exc()
        await message.reply(
            "<code>Internal Error Occurred. Try again later.</code>",
            reply_to_message_id=message.id
        )


@Client.on_message(filters.command(["myurl", "showurl"]))
async def handle_myurl(client, message):
    """
    Handle /myurl command to show current custom AutoShopify URL

    Usage: /myurl
    """
    try:
        # Load users and check registration
        users = load_users()
        user_id = str(message.from_user.id)

        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id
            )

        # Get user's URL
        current_url = get_user_url(user_id)

        if current_url:
            await message.reply(
                f"""<pre>Your Custom AutoShopify URL</pre>
━━━━━━━━━━━━━━━━
<b>Current URL:</b>
<code>{current_url}</code>

<b>Status:</b> Active ✅

This URL is used first when checking cards with <code>/autosh</code> and <code>/mautosh</code> commands.

<b>Commands:</b>
• <code>/addurl URL</code> - Change URL
• <code>/removeurl</code> - Remove URL
• <code>/myurl</code> - Show current URL""",
                reply_to_message_id=message.id
            )
        else:
            await message.reply(
                f"""<pre>No Custom URL Set</pre>
━━━━━━━━━━━━━━━━
<b>You don't have a custom AutoShopify URL set.</b>

<b>Default fallback URLs are being used:</b>
• https://www.bountifulbaby.com
• https://3duxdesign.myshopify.com
• And 7 more Shopify stores

<b>To set your custom URL:</b>
<code>/addurl https://your-store.myshopify.com</code>

<b>Benefits:</b>
✓ Your preferred store tried first
✓ Automatic fallback if it fails
✓ Works with all AutoShopify commands""",
                reply_to_message_id=message.id
            )

    except Exception as e:
        print(f"Error in /myurl: {e}")
        import traceback
        traceback.print_exc()
        await message.reply(
            "<code>Internal Error Occurred. Try again later.</code>",
            reply_to_message_id=message.id
        )
