# Telegram Bot Service Setup

## Environment Detection

This bot is running in a **containerized environment** (not systemd-based).

## Running the Bot

### Option 1: Direct Execution (Recommended for Containers)
```bash
cd /home/user/bot
python3 main.py
```

### Option 2: Using the Start Script
```bash
./start-bot.sh
```

### Option 3: Background Execution with nohup
```bash
nohup python3 main.py > bot.log 2>&1 &
```

### Option 4: Using screen (if available)
```bash
screen -dmS telegram-bot python3 main.py
# To attach: screen -r telegram-bot
# To detach: Ctrl+A, then D
```

## Stopping the Bot

Find the process ID and kill it:
```bash
ps aux | grep main.py
kill <PID>
```

Or kill all python processes running main.py:
```bash
pkill -f "python3 main.py"
```

## Checking if Bot is Running

```bash
ps aux | grep main.py
# OR
curl http://localhost:3000
```

## For Systemd-Based Systems

If you move this bot to a systemd-based system, the `telegram-bot.service` file is included and can be installed with:

```bash
sudo cp telegram-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot
sudo systemctl start telegram-bot
```

## Bot Components

The bot runs two services:
1. **Telegram Bot** (Pyrogram) - Main bot functionality
2. **Flask Web Server** (Port 3000) - Health check endpoint

Both services run in parallel when you start main.py.
