# A Universal Kit Delivery System for 6b6t Minecraft Server

A complete kit delivery system consisting of a Discord bot (backend) and a Mineflayer bot (worker) that retrieves kits from chests and delivers them to players on the 6b6t Minecraft server. The system works with both cracked and official mojang accounts. Go down the Online-Accounts section to setup the bot with an official account.

## System Overview

The system has two main components:

1. **Backend (Discord Bot)** - Handles economy, user registration, order placement, gambling games, and communicates with the worker
2. **Worker (Mineflayer Bot)** - A Minecraft bot that pathfinds to chests, extracts items, teleports to players, and waits for collection

## Requirements

### Backend
- Python 3.8+
- discord.py
- requests
- python-dotenv

### Worker
- Node.js 18+
- mineflayer
- mineflayer-pathfinder
- minecraft-data
- express
- dotenv

## Installation

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Worker

```bash
cd worker
npm install
```

## Configuration

### Backend Environment Variables

Create a `.env` file in the `backend` directory:

| Variable | Description | Default |
|----------|-------------|---------|
| `DAILY_FREE_TOKENS` | Number of tokens given daily to each user | 50 |
| `WHETHER_DAILY_FREE_TOKENS_EXPIRE` | Whether daily tokens expire (true/false) | false |
| `COOLDOWN_BETWEEN_ORDERS` | Seconds between order placements | 60 |
| `MAX_ORDER_QTY` | Maximum quantity per order | 3 |
| `DISCORD_BOT_TOKEN` | Your Discord bot token | (required) |
| `ACTIVE_CHANNEL_ID` | Discord channel ID where commands work | (required) |
| `GUILD_ID` | Discord server ID (for invite tracking) | (required) |
| `OWNER_USER_ID` | Discord user ID of the bot owner | (required) |
| `OWNER_IGN` | Minecraft IGN of the bot owner (for admin orders) | (required) |
| `WORKER_URL` | URL of the worker API | http://localhost:3003 |
| `INVITE_REWARD` | Tokens earned per invite | 1 |

### Worker Environment Variables

Create a `.env` file in the `worker` directory:

| Variable | Description | Default |
|----------|-------------|---------|
| `MC_HOST` | Minecraft server address | play.6b6t.org |
| `MC_PORT` | Minecraft server port | 25565 |
| `MC_AUTH` | Authentication type (offline/online) | offline |
| `MC_VERSION` | Minecraft protocol version | 1.20.1 |
| `WORKER_USERNAME` | Minecraft username for the bot | workerbot |
| `WORKER_PASSWORD` | Minecraft password (for /login command) | password |
| `API_PORT` | Port for the worker API | 3003 |

### Kit Configuration

Edit `kits.json` in the worker directory to define available kits:

```json
{
  "pvp": {
    "price": 1,
    "chest": {
      "x": 0,
      "y": 0,
      "z": 0
    }
  },
  "build": {
    "price": 1,
    "chest": {
      "x": 0,
      "y": 0,
      "z": 0
    }
  }
}
```

Each kit needs:
- `price`: Cost in tokens
- `chest.x`, `chest.y`, `chest.z`: Coordinates of the chest containing the kit

## Starting the System

### Start the Worker

```bash
cd worker
node index.js
```

Expected output:
```
Starting...
API on port 3003
[Worker] sudobot spawned
[Worker] Ready
```

### Start the Backend

```bash
cd backend
source venv/bin/activate
python main.py
```

Expected output:
```
Bot is ready and commands are synced.
```

## Registration and Verification

The system uses a verification system to ensure users own the Minecraft IGN they register with:

1. Run `/register_in_economy <your_ign>` - e.g., `/register_in_economy Steve`
2. Check your Minecraft chat - you will receive an 8-digit verification code via /w
3. Run `/verify <code>` - enter the code you received
4. If the code is valid and not expired (5 minutes), you are now registered

If you enter the wrong IGN, simply run `/register_in_economy <correct_ign>` again to get a new code.

## Discord Commands

### User Commands

All users can use these commands in the designated channel:

- `/register_in_economy <ign>` - Start registration (sends verification code to your Minecraft)
- `/verify <code>` - Complete registration with the code received in Minecraft
- `/balance` - Check your token balance
- `/stats` - View your order statistics
- `/claim_daily_tokens` - Claim your daily free tokens
- `/kit_list` - View all available kits and their prices
- `/order_kit <kit_type> <qty>` - Order a kit (e.g., `/order_kit pvp1 2`)
- `/dice <bet>` - Roll dice, higher number wins (2x payout)
- `/coinflip <bet> <heads/tails>` - Flip a coin (2x payout)
- `/slots <bet>` - Spin the slot machine (5x jackpot)
- `/highlow <bet> <high/low>` - High or low card game (2x payout)
- `/gambling_help` - Show information about gambling games
- `/help` - Show all available commands

### Admin Commands

Only the bot owner (defined by OWNER_USER_ID) can use these:

- `/give_tokens_to_player <user> <amount>` - Give tokens to a player
- `/take_tokens_from_player <user> <amount>` - Take tokens from a player
- `/give_all_players_tokens <amount>` - Give tokens to all registered players
- `/take_from_all_players_tokens <amount>` - Take tokens from all registered players
- `/admin_balance <user>` - Check a user's balance
- `/admin_stats <user>` - Check a user's order statistics
- `/refund <user> <amount>` - Manually refund tokens to a player
- `/order_kit <kit_type> <qty>` - Order a kit for free (admin override)

## How It Works

### Registration Flow

1. User runs `/register_in_economy <ign>` with their Minecraft username
2. Backend generates an 8-digit verification code and sends it via the worker bot
3. The code is delivered to the player in-game using `/w`
4. User checks Minecraft chat and runs `/verify <code>` to complete registration
5. Code expires after 5 minutes - if expired, user must start over

This ensures users own the IGN they register with, preventing someone from registering with another person's username to claim their kits.

### Order Flow

1. User registers with their Minecraft IGN using `/register_in_economy` and verifies with `/verify <code>`
2. User orders a kit with `/order_kit <type> <qty>`
3. Tokens are deducted immediately upon order placement
4. Backend sends order to worker via HTTP API
5. Worker bot:
   - Pathfinds to the chest location
   - Opens the chest and extracts items
   - Sends `/tpa` to the player
   - Waits in a loop for the player to come within 50 blocks
   - When player is detected, bot kills itself (`/kill`)
   - Items drop as player loot
   - If the player does not accept within 5 minutes, the order times out and refunds.
6. If delivery fails (bot dies before player pickup), tokens are refunded

### Delivery Detection

The worker detects player pickup by checking distance in a loop:
- Bot waits in infinite loop after sending `/tpa`
- Every 1 second, checks if player is within 50 blocks
- If player detected, bot executes `/kill` to drop items
- If bot dies before detection, order is marked as failed and tokens refunded

### Failed Order Handling

The backend polls for failed orders every 15 seconds:
- If an order fails, it's added to the worker's failedOrders array and saved instantly to failed_orders.json on disk to survive node script restarts and server crashes.
- Backend fetches failed orders and processes refunds
- Refunded tokens are added back to user's balance
- User receives a DM notification about the failed order

### Invite Tracking

The system tracks Discord invites to reward users for bringing new members:
- Bot caches all server invite codes and their use counts on startup
- Cache updates every 5 minutes
- When a new member joins, bot compares current invite uses to cached uses
- If an invite's use count increased, the inviter earns tokens (default: 1 token per invite)
- Inviter receives a DM notification about their reward
- Invite count is shown in /stats and /admin_stats

Note: Bot needs "Manage Server" permission to read invite data.

### Disconnect & Proxy Handover Protection

When using /home to return from the End dimension, or if the server lags, there may be a proxy handover that temporarily disconnects the bot.
To protect the user's tokens and prevent queue corruption, the system treats mid-order disconnects strictly:
- If the bot gets disconnected or shifted to another proxy while actively fetching a kit or waiting for a TPA, the promise instantly rejects.
- The order is immediately marked as failed and secured to the refund disk file.
- When the bot reconnects, it starts fresh with the next person in the queue. This guarantees users never lose tokens to server instability.

## Gambling System

All gambling games are slightly biased against the player:

- **Dice**: 55% chance for bot to roll higher
- **Coinflip**: 52% chance for player to win
- **Slots**: 10% base jackpot chance (5x payout)
- **High/Low**: 53% chance for bot to win

## Worker Logs

The worker logs important events with `[Worker]` prefix:

| Log Message | Meaning |
|-------------|---------|
| `sudobot spawned` | Bot has spawned into the game |
| `Ready` | Bot is fully initialized and ready for orders |
| `Order: <ign> x<qty> <kit>` | Processing a new order |
| `Sent /tpa` | Sent teleport request to player |
| `Player detected` | Player came within 50 blocks |
| `Killing bot` | Bot executing /kill to drop items |
| `Died` | Bot has died |
| `Died before player pickup, adding to failed orders` | Order failed, refund triggered |
| `Player was detected before death, no refund needed` | Delivery succeeded |
| `Back from proxy handover, resuming player detection...` | Reconnected during delivery |
| `Error: <message>` | Various errors (chest not found, chest empty, etc.) |

*The new patches have different logging, but its self-explanatory, so i am not updating this*

### Error Types

- `Chest not found` - No chest at the configured coordinates
- `Chest empty` - Chest has no items, tokens refunded
- `Event windowOpen did not fire within timeout` - Chest couldn't be opened (wrong coords, blocked, or in different dimension)

## Database

The backend uses SQLite (`economy.db`) with the following schema:

```sql
CREATE TABLE users (
  discord_id TEXT PRIMARY KEY,
  ign TEXT,
  tokens INTEGER DEFAULT 0,
  last_daily TEXT,
  orders_placed INTEGER DEFAULT 0,
  gambling_wins INTEGER DEFAULT 0,
  gambling_losses INTEGER DEFAULT 0,
  invites INTEGER DEFAULT 0
)
```

## Security Notes

- Keep your `.env` files private (add to .gitignore)
- Never share your Discord bot token
- The worker password is used for `/login <password>` on 6b6t servers
- Ensure the active channel ID is set to prevent unauthorized command usage

## Troubleshooting

### Worker won't connect
- Verify MC_HOST and port are correct
- Check MC_VERSION matches server protocol

### Orders not going through
- Ensure worker API is running (port 3003 by default)
- Verify WORKER_URL in backend .env matches

### Bot dies immediately after spawn
- Check that WORKER_PASSWORD is correct
- Ensure the bot has permission to run commands on the server

### Refunds not working
- Check backend logs for polling errors
- Verify the player has DMs enabled to receive refund notifications

## Online Accounts
- If you want to use an official account put in your microsoft email as `WORKER_USERNAME`, set `MC_AUTH` to `microsoft` and leave `WORKER_PASSWORD` blank.
- When index.js is run, a Microsoft auth link will appear with an auth code, click on that link, put in the code and verify with your microsoft password.
- If successfully verified, the script will acknowledge the microsoft authentication within a few seconds, and the bot will execute its portal entry sequence.

## IMPORTANT
- PLEASE PLEASE PLEASE USE THE PROVIDED PACKAGE.JSON ONLY TO INSTALL THE NPM PACKAGES, IF INSTALLING MANUALLY. I cant stress this enough. 6b6t WILL BREAK YOUR BOT IF YOU USE PACKAGES OF OTHER VERSIONS. I recommend just doing npm install on node 22. That's the safest way to ensure your bot is workable.
- 6b6t's inconsistent tps can cause the bot's login sequence to timeout early, thereby causing it to get stuck in the lobby. This was a recurring phenomena in the testing. To fix it, just restart index.js.
- This framework does not work for stashes in the end, the weird proxy handover bypass to make the bot execute /home is too complicated to implement. Figure it out yourselves.
- The bot is extremely fast and robust (genuinely). If you face any problems, contact me on discord *@1_sudo*.
- Please note that this has been specifically developed for 6b6t, I do not guarantee that will work on other anarchy servers, and will not take any responsibility. Figure it out yourselves.

### Credits:
**sudoboneman (discord: _irodov)**

## With Love, 
### - From TSR CLAN ❤️