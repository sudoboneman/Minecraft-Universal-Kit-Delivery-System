import sqlite3
import time
import random
from datetime import datetime, timedelta

DB_NAME = "economy.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    discord_id TEXT PRIMARY KEY,
                    ign TEXT,
                    tokens INTEGER DEFAULT 0,
                    last_daily TIMESTAMP,
                    orders_placed INTEGER DEFAULT 0,
                    gambling_wins INTEGER DEFAULT 0,
                    gambling_losses INTEGER DEFAULT 0,
                    invites INTEGER DEFAULT 0
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS pending_verifications (
                    discord_id TEXT PRIMARY KEY,
                    ign TEXT,
                    code TEXT,
                    expires_at INTEGER
                 )''')
    conn.commit()
    conn.close()

def get_user(discord_id: str):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
    res = c.fetchone()
    conn.close()
    return res

def user_exists(discord_id: str):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE discord_id = ?", (discord_id,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def update_tokens(discord_id: str, amount: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET tokens = tokens + ? WHERE discord_id = ?", (amount, discord_id))
    conn.commit()
    conn.close()

def set_all_tokens(amount: int, add: bool = True):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if add:
        c.execute("UPDATE users SET tokens = tokens + ?", (amount,))
    else:
        c.execute("UPDATE users SET tokens = MAX(0, tokens - ?)", (amount,))
    conn.commit()
    conn.close()

def claim_daily(discord_id: str, daily_amount: int):
    user = get_user(discord_id)
    if not user: return False, "Please /register_in_economy first."
    
    last_daily_str = user[3]
    now = datetime.now()
    
    if last_daily_str:
        last_daily = datetime.fromisoformat(last_daily_str)
        if now - last_daily < timedelta(days=1):
            return False, "You have already claimed your daily tokens today."
            
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET tokens = tokens + ?, last_daily = ? WHERE discord_id = ?", 
              (daily_amount, now.isoformat(), discord_id))
    conn.commit()
    conn.close()
    return True, f"Successfully claimed {daily_amount} tokens!"

def increment_stats(discord_id: str):
    conn = sqlite3.connect(DB_NAME)
    conn.execute('UPDATE users SET orders_placed = orders_placed + 1 WHERE discord_id = ?', (discord_id,))
    conn.commit()
    conn.close()

def create_pending_verification(discord_id: str, ign: str):
    code = str(random.randint(10000000, 99999999))
    expires_at = int(time.time()) + 300  # 5 minutes
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("REPLACE INTO pending_verifications (discord_id, ign, code, expires_at) VALUES (?, ?, ?, ?)",
              (discord_id, ign, code, expires_at))
    conn.commit()
    conn.close()
    return code

def verify_code(discord_id: str, code: str):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT ign, code, expires_at FROM pending_verifications WHERE discord_id = ?", (discord_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None, "No pending verification. Run /register_in_economy first."
    
    ign, stored_code, expires_at = row
    if int(time.time()) > expires_at:
        c.execute("DELETE FROM pending_verifications WHERE discord_id = ?", (discord_id,))
        conn.commit()
        conn.close()
        return None, "Code expired. Run /register_in_economy again."
    
    if code != stored_code:
        conn.close()
        return None, "Invalid code. Check Minecraft and try again."
    
    c.execute("DELETE FROM pending_verifications WHERE discord_id = ?", (discord_id,))
    c.execute("INSERT INTO users (discord_id, ign, tokens, gambling_wins, gambling_losses, invites) VALUES (?, ?, 0, 0, 0, 0)", (discord_id, ign))
    conn.commit()
    conn.close()
    return ign, "success"

def record_gambling_result(discord_id: str, won: bool):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if won:
        c.execute("UPDATE users SET gambling_wins = gambling_wins + 1 WHERE discord_id = ?", (discord_id,))
    else:
        c.execute("UPDATE users SET gambling_losses = gambling_losses + 1 WHERE discord_id = ?", (discord_id,))
    conn.commit()
    conn.close()

def add_invite_tokens(inviter_id: str, amount: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET tokens = tokens + ?, invites = invites + 1 WHERE discord_id = ?", (amount, inviter_id))
    conn.commit()
    conn.close()