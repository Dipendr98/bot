import json
import asyncio
import threading
from pyrogram import Client, idle
from pyrogram.types import BotCommand
from flask import Flask
from BOT.plans.plan1 import check_and_expire_plans as plan1_expiry
from BOT.plans.plan2 import check_and_expire_plans as plan2_expiry
from BOT.plans.plan3 import check_and_expire_plans as plan3_expiry
from BOT.plans.plan4 import check_and_expire_plans as plan4_expiry
from BOT.plans.redeem import check_and_expire_redeem_plans as redeem_expiry

# Load bot credentials
with open("FILES/config.json", "r", encoding="utf-8") as f:
    DATA = json.load(f)
    API_ID = DATA["API_ID"]
    API_HASH = DATA["API_HASH"]
    BOT_TOKEN = DATA["BOT_TOKEN"]

# Pyrogram plugins
plugins = dict(root="BOT")

# Pyrogram client
bot = Client(
    "MY_BOT",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=plugins
)

# Flask App
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=3000)

async def run_bot():
    await bot.start()
    print("✅ Bot is running...")

    # Register bot commands for autocomplete
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show help menu"),
        BotCommand("ping", "Check bot latency"),
        BotCommand("info", "Get user information"),
        BotCommand("cmds", "View all commands"),
        BotCommand("bin", "Check BIN information"),
        BotCommand("mbin", "Mass BIN lookup"),
        BotCommand("fake", "Generate fake identity"),
        BotCommand("gen", "Generate card numbers"),
        BotCommand("mod", "Modify card numbers"),
        BotCommand("sg", "Shopify gateway charge"),
        BotCommand("msg", "Mass Shopify gateway charge"),
        BotCommand("sho", "Shopify checkout"),
        BotCommand("msho", "Mass Shopify checkout"),
        BotCommand("sh", "Shopify charge"),
        BotCommand("msh", "Mass Shopify charge"),
        BotCommand("tsh", "Test Shopify"),
        BotCommand("tslf", "Test SLF"),
        BotCommand("autosh", "AutoShopify charge"),
        BotCommand("mautosh", "Mass AutoShopify charge"),
        BotCommand("br", "Braintree checker"),
        BotCommand("st", "Stripe $20 charge"),
        BotCommand("au", "Stripe Auth $0 check"),
        BotCommand("mau", "Stripe Auth mass check"),
        BotCommand("swc", "Stripe WooCommerce Auth check"),
        BotCommand("mswc", "Mass Stripe WooCommerce Auth check"),
        BotCommand("vbv", "VBV verification check"),
        BotCommand("mvbv", "Mass VBV verification check"),
        BotCommand("mbv", "MBV SecureCode verification check"),
        BotCommand("mmbv", "Mass MBV SecureCode verification check"),
        BotCommand("bt", "Braintree CVV check"),
        BotCommand("btcvv", "Braintree CVV Auth check"),
        BotCommand("mbtcvv", "Mass Braintree CVV Auth check"),
        BotCommand("plans", "View available plans"),
        BotCommand("requestplan", "Request a plan"),
        BotCommand("myrequests", "View your plan requests"),
        BotCommand("cancelrequest", "Cancel a plan request"),
        BotCommand("redeem", "Redeem a plan key"),
        BotCommand("setpx", "Set proxy"),
        BotCommand("getpx", "Get current proxy"),
        BotCommand("delpx", "Delete proxy"),
        BotCommand("groupid", "Get group/chat ID"),
        BotCommand("fl", "Apply filter (reply to message)"),
        BotCommand("fback", "Send feedback (reply to message)"),
        BotCommand("addurl", "Add Shopify site for checking"),
        BotCommand("slfurl", "Add Shopify site (alias)"),
        BotCommand("mysite", "View your current site"),
        BotCommand("delsite", "Remove your saved site"),
        BotCommand("txturl", "Add multiple sites for TXT"),
        BotCommand("txtls", "List your TXT sites"),
        BotCommand("rurl", "Remove TXT sites"),
    ]

    await bot.set_bot_commands(commands)
    print("✅ Bot commands registered for autocomplete")

    # Background plan expiry tasks
    asyncio.create_task(plan1_expiry(bot))
    asyncio.create_task(plan2_expiry(bot))
    asyncio.create_task(plan3_expiry(bot))
    asyncio.create_task(plan4_expiry(bot))
    asyncio.create_task(redeem_expiry(bot))

    await idle()
    await bot.stop()
    print("❌ Bot stopped.")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    # Run Flask in a separate thread
    threading.Thread(target=run_flask).start()

    # Start bot loop
    asyncio.run(run_bot())
