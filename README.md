# Vouchy — Discord Vouch Bot

Tracks vouches by counting image attachments in a specific channel and stores totals in `vouches.json`. Provides `!vouches` and `!topvouches` commands.

## Features
- Per-image vouch counting in a configured channel
- JSON persistence (`vouches.json`)
- Leaderboard and per-user query commands

## Requirements
- Python 3.10+
- `discord.py` (see `requirements.txt`)

## Setup
1. Install dependencies:
```powershell
pip install -r requirements.txt
```
2. Enable "Message Content Intent" for your bot in the Discord Developer Portal.
3. Option A — .env file (recommended for local dev):
   - Copy `.env.example` to `.env`
   - Edit `.env` and set your token:
```env
DISCORD_TOKEN=YOUR_BOT_TOKEN
```
   - Run the bot (it auto-loads `.env`):
```powershell
python bot.py
```
4. Option B — Environment variable (no file):
   - PowerShell (one-time for the current window):
```powershell
$env:DISCORD_TOKEN="YOUR_BOT_TOKEN"
```
   - Persist for future sessions:
```powershell
setx DISCORD_TOKEN "YOUR_BOT_TOKEN"
```
5. Configure your channel ID inside `bot.py`:
```python
VOUCH_CHANNEL_ID = 123456789012345678
```
6. Run the bot:
```powershell
python bot.py
```

## Commands
- `!vouches [@member]` — show vouch total for you or a mentioned member
- `!topvouches` — show top 10 leaderboard

## Notes
- The bot awards `POINTS_PER_PICTURE` per image attachment in the vouch channel.
- Vouch data is saved to `vouches.json` in the project directory.

