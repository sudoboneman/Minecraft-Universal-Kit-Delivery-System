import discord
from discord.ext import commands, tasks
from discord import app_commands
import requests
import uuid
import sqlite3
from config import Config
import database

INVITE_REWARD = Config.INVITE_REWARD

class KitDeliveryBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.invites = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.invite_cache = {}
        self.ready = False

    async def setup_hook(self):
        database.init_db()
        
        try:
            guild = discord.Object(id=Config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print('slash commands auto-synced on startup.')
        except Exception as e:
            print(f'failed to auto-sync commands: {e}')
        
        # start tasks, but do not wait for the bot here
        self.poll_failed_orders.start()
        self.update_invite_cache.start()

    async def on_ready(self):
        print(f'logged in as {self.user}')
        
        await self.populate_invite_cache()
        self.ready = True
        
        print('bot is fully ready and tasks are started.')


    async def populate_invite_cache(self):
        try:
            guild = self.get_guild(Config.GUILD_ID)
            if not guild:
                print(f'Guild {Config.GUILD_ID} not found. Make sure GUILD_ID is correct.')
                return
            invites = await guild.invites()
            self.invite_cache = {invite.code: invite.uses for invite in invites}
            print(f'Invite cache initialized with {len(self.invite_cache)} invites')
            for inv in invites:
                print(f'  {inv.code}: {inv.uses} uses (by {inv.inviter})')
        except Exception as e:
            print(f'Failed to populate invite cache: {e}')
            import traceback
            traceback.print_exc()

    @tasks.loop(minutes=5)
    async def update_invite_cache(self):
        if not self.ready: return
        try:
            guild = self.get_guild(Config.GUILD_ID)
            if guild:
                invites = await guild.invites()
                self.invite_cache = {invite.code: invite.uses for invite in invites}
                print(f'Invite cache updated: {len(self.invite_cache)} invites')
        except Exception as e:
            print(f'Failed to update invite cache: {e}')

    async def on_member_join(self, member):
        if not self.ready: return
        print(f'Member joined: {member.name} ({member.id}) in guild {member.guild.id}')
        
        if member.guild.id != Config.GUILD_ID:
            print(f'Guild mismatch: {member.guild.id} != {Config.GUILD_ID}')
            return
        
        try:
            guild = member.guild
            invites = await guild.invites()
            print(f'Checking {len(invites)} invites against cache...')
            
            for invite in invites:
                old_uses = self.invite_cache.get(invite.code, 0)
                
                print(f'  {invite.code}: cached={old_uses}, current={invite.uses}')
                
                if invite.uses > old_uses:
                    inviter = invite.inviter
                    print(f'Found! Invited by: {inviter}')
                    
                    # triggering on this same invite forever if the inviter isn't registered.
                    self.invite_cache[invite.code] = invite.uses
                    
                    if inviter and database.user_exists(str(inviter.id)):
                        database.add_invite_tokens(str(inviter.id), INVITE_REWARD)
                        print(f'Awarded {INVITE_REWARD} token to inviter {inviter.id}')
                        try:
                            await inviter.send(f'Someone joined using your invite! You earned {INVITE_REWARD} tokens.')
                        except Exception as e:
                            print(f'Could not DM inviter: {e}')
                    
                    break
                    
        except Exception as e:
            print(f'Invite tracking error: {e}')
            import traceback
            traceback.print_exc()

    @tasks.loop(seconds=15)
    async def poll_failed_orders(self):
        if not self.ready: return
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f'{Config.WORKER_URL}/failed_orders', timeout=5) as resp:
                    if resp.status == 200:
                        failures = await resp.json()
                        for order in failures:
                            order_id = order.get('id')
                            user_id = order.get('discord_id')
                            amount = order.get('refund_amount')
                            ign = order.get('ign')

                            if amount > 0:
                                database.update_tokens(str(user_id), amount)
                                conn = sqlite3.connect(database.DB_NAME)
                                conn.execute('UPDATE users SET orders_placed = MAX(0, orders_placed - 1) WHERE discord_id = ?', (str(user_id),))
                                conn.commit()
                                conn.close()

                            try:
                                user = await self.fetch_user(int(user_id))
                                if user:
                                    if amount > 0:
                                        embed = discord.Embed(color=discord.Color.red(), description=f'your kit order for **{ign}** failed. **{amount}** tokens refunded.')
                                    else:
                                        embed = discord.Embed(color=discord.Color.red(), description=f'admin kit order for **{ign}** failed.')
                                    await user.send(embed=embed)
                            except Exception as e:
                                print(f'could not dm user {user_id}: {e}')

                            async with session.post(f'{Config.WORKER_URL}/clear_failed', json={'id': order_id}, timeout=5) as post_resp:
                                pass
        except Exception as e:
            print(f'poll failed orders error: {e}')

client = KitDeliveryBot()

def check_channel(interaction: discord.Interaction):
    return interaction.channel_id == Config.ACTIVE_CHANNEL_ID

def is_owner(interaction: discord.Interaction):
    return interaction.user.id == Config.OWNER_USER_ID

@client.tree.command(name='register_in_economy', description='Register to start using tokens and ordering kits.')
async def register_in_economy(interaction: discord.Interaction, ign: str):
    if not check_channel(interaction): return await interaction.response.send_message('Wrong channel.', ephemeral=True)
    
    user = database.get_user(str(interaction.user.id))
    if user:
        embed = discord.Embed(color=discord.Color.red(), description='You are already registered. Use /unregister first.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    try:
        code = database.create_pending_verification(str(interaction.user.id), ign)
        resp = requests.post(f'{Config.WORKER_URL}/send_verify', json={'ign': ign, 'code': code}, timeout=5)
        if resp.status_code == 200:
            embed = discord.Embed(color=discord.Color.blue(), description=f'Verification code sent to **{ign}** in Minecraft.\nCheck your chat and use `/verify <code>` to complete registration.\nCode expires in 5 minutes.')
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(color=discord.Color.red(), description='Failed to send verification code. Worker may be offline. Try again later.')
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception:
        embed = discord.Embed(color=discord.Color.red(), description='Failed to communicate with worker.')
        await interaction.response.send_message(embed=embed, ephemeral=True)

@client.tree.command(name='verify', description='Verify your Minecraft account with the code sent in-game.')
async def verify(interaction: discord.Interaction, code: str):
    if not check_channel(interaction): return await interaction.response.send_message('Wrong channel.', ephemeral=True)
    
    ign, result = database.verify_code(str(interaction.user.id), code)
    if result == "success":
        embed = discord.Embed(color=discord.Color.green(), description=f'Verified! You are now registered with IGN: **{ign}**')
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(color=discord.Color.red(), description=result)
        await interaction.response.send_message(embed=embed, ephemeral=True)

@client.tree.command(name='claim_daily_tokens', description='Claim your daily free tokens.')
async def claim_daily_tokens(interaction: discord.Interaction):
    if not check_channel(interaction): return await interaction.response.send_message('Wrong channel.', ephemeral=True)
    
    success, msg = database.claim_daily(str(interaction.user.id), Config.DAILY_FREE_TOKENS)
    embed = discord.Embed(color=discord.Color.green() if success else discord.Color.red(), description=msg)
    await interaction.response.send_message(embed=embed, ephemeral=not success)

@client.tree.command(name='balance', description='Check your token balance.')
async def balance(interaction: discord.Interaction):
    if not check_channel(interaction): return await interaction.response.send_message('Wrong channel.', ephemeral=True)
    
    user = database.get_user(str(interaction.user.id))
    if not user:
        embed = discord.Embed(color=discord.Color.red(), description='You are not registered. Use /register_in_economy.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    embed = discord.Embed(color=discord.Color.green(), description=f'Your current balance is: **{user[2]} tokens**.')
    await interaction.response.send_message(embed=embed)

@client.tree.command(name='stats', description='View your order statistics.')
async def stats(interaction: discord.Interaction):
    if not check_channel(interaction): return await interaction.response.send_message('Wrong channel.', ephemeral=True)
    
    user = database.get_user(str(interaction.user.id))
    if not user:
        embed = discord.Embed(color=discord.Color.red(), description='You are not registered.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    wins = user[5] or 0
    losses = user[6] or 0
    invites = user[7] or 0
    total = wins + losses
    win_rate = f"{(wins/total*100):.1f}%" if total > 0 else "N/A"
    embed = discord.Embed(color=discord.Color.blue(), description=f'**{user[1]}** Stats:\nOrders Placed: {user[4]}\nTokens: {user[2]}\nInvites: {invites}\nGambling Wins: {wins}\nGambling Losses: {losses}\nWin Rate: {win_rate}')
    await interaction.response.send_message(embed=embed)

@client.tree.command(name='kit_list', description='View all available kits and their prices.')
async def kit_list(interaction: discord.Interaction):
    if not check_channel(interaction): return await interaction.response.send_message('Wrong channel.', ephemeral=True)
    
    try:
        resp = requests.get(f'{Config.WORKER_URL}/kits', timeout=5)
        kits = resp.json()
        embed = discord.Embed(title='Available Kits', color=discord.Color.gold())
        for kit_name, details in kits.items():
            price = details.get('price', 'N/A')
            embed.add_field(name=kit_name, value=f'{price} tokens', inline=True)
        await interaction.response.send_message(embed=embed)
    except Exception:
        embed = discord.Embed(color=discord.Color.red(), description='Failed to fetch kits from worker. It might be offline.')
        await interaction.response.send_message(embed=embed, ephemeral=True)

@client.tree.command(name='order_kit', description='Order a specific kit.')
async def order_kit(interaction: discord.Interaction, kit_type: str, qty: int):
    if not check_channel(interaction): return await interaction.response.send_message('Wrong channel.', ephemeral=True)
    if qty < 1 or qty > Config.MAX_ORDER_QTY:
        embed = discord.Embed(color=discord.Color.red(), description=f'Quantity must be between 1 and {Config.MAX_ORDER_QTY}.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    owner_override = is_owner(interaction)
    user = database.get_user(str(interaction.user.id))
    
    if not owner_override and not user:
        embed = discord.Embed(color=discord.Color.red(), description='Register first using /register_in_economy.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    try:
        kits = requests.get(f'{Config.WORKER_URL}/kits', timeout=5).json()
        if kit_type not in kits:
            embed = discord.Embed(color=discord.Color.red(), description=f'Kit `{kit_type}` not found. Check /kit_list.')
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        total_price = kits[kit_type]['price'] * qty
        
        if not owner_override and user[2] < total_price:
            embed = discord.Embed(color=discord.Color.red(), description=f'Insufficient funds! Need {total_price} tokens, you have {user[2]}.')
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        order_uuid = str(uuid.uuid4())
        target_ign = Config.OWNER_IGN if owner_override else user[1]
        refund_amount = 0 if owner_override else total_price

        req = requests.post(f'{Config.WORKER_URL}/order', json={
            'id': order_uuid,
            'discord_id': str(interaction.user.id),
            'ign': target_ign,
            'kit': kit_type,
            'qty': qty,
            'refund_amount': refund_amount
        }, timeout=5)
        
        if req.status_code == 200:
            queue_pos = req.json().get('queuePosition', '?')
            
            if owner_override:
                embed = discord.Embed(color=discord.Color.green(), description=f'Admin override! Ordered {qty}x **{kit_type}** for free.\nQueue: #{queue_pos}\n**Accept /tpa on {target_ign}!**')
                await interaction.response.send_message(embed=embed)
            else:
                database.update_tokens(str(interaction.user.id), -total_price)
                database.increment_stats(str(interaction.user.id))
                embed = discord.Embed(color=discord.Color.green(), description=f'Order confirmed! Deducted {total_price} tokens. Queue: #{queue_pos}\n**Accept /tpa on {target_ign}!**')
                await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(color=discord.Color.red(), description='Worker rejected the order. Try again later.')
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
    except Exception:
        embed = discord.Embed(color=discord.Color.red(), description='Failed to communicate with worker.')
        await interaction.response.send_message(embed=embed, ephemeral=True)

@client.tree.command(name='give_tokens_to_player', description='Admin: Give tokens to a player.')
async def give_tokens_to_player(interaction: discord.Interaction, target_user: discord.Member, amount: int):
    if not is_owner(interaction): return await interaction.response.send_message('Unauthorized.', ephemeral=True)
    if not database.user_exists(str(target_user.id)):
        embed = discord.Embed(color=discord.Color.red(), description='User is not registered.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    database.update_tokens(str(target_user.id), amount)
    embed = discord.Embed(color=discord.Color.green(), description=f'Gave {amount} tokens to {target_user.display_name}.')
    await interaction.response.send_message(embed=embed)

@client.tree.command(name='take_tokens_from_player', description='Admin: Take tokens from a player.')
async def take_tokens_from_player(interaction: discord.Interaction, target_user: discord.Member, amount: int):
    if not is_owner(interaction): return await interaction.response.send_message('Unauthorized.', ephemeral=True)
    if not database.user_exists(str(target_user.id)):
        embed = discord.Embed(color=discord.Color.red(), description='User is not registered.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    database.update_tokens(str(target_user.id), -amount)
    embed = discord.Embed(color=discord.Color.orange(), description=f'Took {amount} tokens from {target_user.display_name}.')
    await interaction.response.send_message(embed=embed)

@client.tree.command(name='give_all_players_tokens', description='Admin: Give tokens to all registered players.')
async def give_all_players_tokens(interaction: discord.Interaction, amount: int):
    if not is_owner(interaction): return await interaction.response.send_message('Unauthorized.', ephemeral=True)
    database.set_all_tokens(amount, add=True)
    embed = discord.Embed(color=discord.Color.green(), description=f'Gave {amount} tokens to all registered players.')
    await interaction.response.send_message(embed=embed)

@client.tree.command(name='take_from_all_players_tokens', description='Admin: Take tokens from all registered players.')
async def take_from_all_players_tokens(interaction: discord.Interaction, amount: int):
    if not is_owner(interaction): return await interaction.response.send_message('Unauthorized.', ephemeral=True)
    database.set_all_tokens(amount, add=False)
    embed = discord.Embed(color=discord.Color.orange(), description=f'Took {amount} tokens from all registered players.')
    await interaction.response.send_message(embed=embed)

@client.tree.command(name='admin_balance', description='Admin: Check a user balance.')
async def admin_balance(interaction: discord.Interaction, target_user: discord.Member):
    if not is_owner(interaction): return await interaction.response.send_message('Unauthorized.', ephemeral=True)
    if not database.user_exists(str(target_user.id)):
        embed = discord.Embed(color=discord.Color.red(), description='User is not registered.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    user = database.get_user(str(target_user.id))
    embed = discord.Embed(color=discord.Color.blue(), description=f'{target_user.display_name} has {user[2]} tokens.')
    await interaction.response.send_message(embed=embed)

@client.tree.command(name='admin_stats', description='Admin: Check a user stats.')
async def admin_stats(interaction: discord.Interaction, target_user: discord.Member):
    if not is_owner(interaction): return await interaction.response.send_message('Unauthorized.', ephemeral=True)
    if not database.user_exists(str(target_user.id)):
        embed = discord.Embed(color=discord.Color.red(), description='User is not registered.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    user = database.get_user(str(target_user.id))
    wins = user[5] or 0
    losses = user[6] or 0
    invites = user[7] or 0
    total = wins + losses
    win_rate = f"{(wins/total*100):.1f}%" if total > 0 else "N/A"
    embed = discord.Embed(color=discord.Color.blue(), description=f'{target_user.display_name} (IGN: {user[1]})\nOrders: {user[4]}\nTokens: {user[2]}\nInvites: {invites}\nGambling Wins: {wins}\nGambling Losses: {losses}\nWin Rate: {win_rate}')
    await interaction.response.send_message(embed=embed)

@client.tree.command(name='refund', description='Admin: Manually refund tokens to a player.')
async def refund_order(interaction: discord.Interaction, target_user: discord.Member, amount: int):
    if not is_owner(interaction): return await interaction.response.send_message('Unauthorized.', ephemeral=True)
    if not database.user_exists(str(target_user.id)):
        embed = discord.Embed(color=discord.Color.red(), description='User is not registered.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    database.update_tokens(str(target_user.id), amount)
    conn = sqlite3.connect(database.DB_NAME)
    conn.execute('UPDATE users SET orders_placed = MAX(0, orders_placed - 1) WHERE discord_id = ?', (str(target_user.id),))
    conn.commit()
    conn.close()
    embed = discord.Embed(color=discord.Color.green(), description=f'Manually refunded {amount} tokens to {target_user.display_name}.')
    await interaction.response.send_message(embed=embed)

import random

@client.tree.command(name='dice', description='roll dice. higher number wins.')
async def dice(interaction: discord.Interaction, bet: int):
    if not check_channel(interaction): return await interaction.response.send_message('wrong channel.', ephemeral=True)
    user = database.get_user(str(interaction.user.id))
    if not user: 
        embed = discord.Embed(color=discord.Color.red(), description='register first with /register_in_economy.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    if bet < 1:
        embed = discord.Embed(color=discord.Color.red(), description='bet must be at least 1 token.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    if user[2] < bet:
        embed = discord.Embed(color=discord.Color.red(), description=f'insufficient funds! you have {user[2]} tokens.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    database.update_tokens(str(interaction.user.id), -bet)
    
    player_roll = random.randint(1, 6)
    bot_roll = random.randint(1, 6)
    
    if random.random() < 0.55:
        # capped at 6 so the bot never rolls a 7
        bot_roll = 6 if player_roll == 6 else player_roll + 1
    
    if player_roll > bot_roll:
        winnings = bet * 2
        database.update_tokens(str(interaction.user.id), winnings)
        database.record_gambling_result(str(interaction.user.id), True)
        embed = discord.Embed(color=discord.Color.green(), description=f'you rolled **{player_roll}**, i rolled **{bot_roll}**. you win **{winnings}** tokens!')
        await interaction.response.send_message(embed=embed)
    elif bot_roll > player_roll:
        database.record_gambling_result(str(interaction.user.id), False)
        embed = discord.Embed(color=discord.Color.red(), description=f'you rolled **{player_roll}**, i rolled **{bot_roll}**. you lose **{bet}** tokens!')
        await interaction.response.send_message(embed=embed)
    else:
        database.update_tokens(str(interaction.user.id), bet)
        embed = discord.Embed(color=discord.Color.blue(), description=f'you rolled **{player_roll}**, i rolled **{bot_roll}**. tie! your bet is returned.')
        await interaction.response.send_message(embed=embed)

@client.tree.command(name='coinflip', description='flip a coin.')
async def coinflip(interaction: discord.Interaction, bet: int, choice: str):
    if not check_channel(interaction): return await interaction.response.send_message('wrong channel.', ephemeral=True)
    user = database.get_user(str(interaction.user.id))
    if not user:
        embed = discord.Embed(color=discord.Color.red(), description='register first with /register_in_economy.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    if bet < 1:
        embed = discord.Embed(color=discord.Color.red(), description='bet must be at least 1 token.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    if user[2] < bet:
        embed = discord.Embed(color=discord.Color.red(), description=f'you have {user[2]} tokens.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    choice = choice.lower()
    if choice not in ['heads', 'tails']:
        embed = discord.Embed(color=discord.Color.red(), description='choose heads or tails.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    database.update_tokens(str(interaction.user.id), -bet)
    
    result = random.choice(['heads', 'tails'])
    
    if random.random() < 0.52:
        # force the opposite of what they picked to ensure they lose the edge flip
        result = 'tails' if choice == 'heads' else 'heads'
    
    if result == choice:
        winnings = bet * 2
        database.update_tokens(str(interaction.user.id), winnings)
        database.record_gambling_result(str(interaction.user.id), True)
        embed = discord.Embed(color=discord.Color.green(), description=f'it\'s **{result}**! you win **{winnings}** tokens!')
        await interaction.response.send_message(embed=embed)
    else:
        database.record_gambling_result(str(interaction.user.id), False)
        embed = discord.Embed(color=discord.Color.red(), description=f'it\'s **{result}**! you lose **{bet}** tokens!')
        await interaction.response.send_message(embed=embed)

@client.tree.command(name='slots', description='Spin the slot machine.')
async def slots(interaction: discord.Interaction, bet: int):
    if not check_channel(interaction): return await interaction.response.send_message('Wrong channel.', ephemeral=True)
    user = database.get_user(str(interaction.user.id))
    if not user:
        embed = discord.Embed(color=discord.Color.red(), description='Register first with /register_in_economy.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    if bet < 1:
        embed = discord.Embed(color=discord.Color.red(), description='Bet must be at least 1 token.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    if user[2] < bet:
        embed = discord.Embed(color=discord.Color.red(), description=f'You have {user[2]} tokens.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    database.update_tokens(str(interaction.user.id), -bet)
    
    symbols = ['🍒', '🍋', '🍇', '💎', '⭐']
    reels = [random.choice(symbols) for _ in range(3)]
    
    win = False
    if random.random() < 0.1:
        win = True
        reels = [random.choice(symbols)] * 3
    else: 
        # PURE TROLL HAHA
        while True:
            reels = [random.choice(symbols) for _ in range(3)]
            if len(set(reels)) > 1:
                break

    if win:
        winnings = bet * 5
        database.update_tokens(str(interaction.user.id), winnings)
        database.record_gambling_result(str(interaction.user.id), True)
        embed = discord.Embed(color=discord.Color.green(), title='JACKPOT!', description=f'{" ".join(reels)}\nYou win **{winnings}** tokens!')
        await interaction.response.send_message(embed=embed)
    else:
        database.record_gambling_result(str(interaction.user.id), False)
        embed = discord.Embed(color=discord.Color.red(), title='No Win', description=f'{" ".join(reels)}\nYou lose **{bet}** tokens.')
        await interaction.response.send_message(embed=embed)

@client.tree.command(name='highlow', description='high or low card.')
async def highlow(interaction: discord.Interaction, bet: int, choice: str):
    if not check_channel(interaction): return await interaction.response.send_message('wrong channel.', ephemeral=True)
    user = database.get_user(str(interaction.user.id))
    if not user:
        embed = discord.Embed(color=discord.Color.red(), description='register first with /register_in_economy.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    if bet < 1:
        embed = discord.Embed(color=discord.Color.red(), description='bet must be at least 1 token.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    if user[2] < bet:
        embed = discord.Embed(color=discord.Color.red(), description=f'you have {user[2]} tokens.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    choice = choice.lower()
    if choice not in ['high', 'low']:
        embed = discord.Embed(color=discord.Color.red(), description='choose high or low.')
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    database.update_tokens(str(interaction.user.id), -bet)
    
    deck = [2,3,4,5,6,7,8,9,10,11,12,13,14] * 4
    random.shuffle(deck)
    
    player_card = deck.pop()
    bot_card = deck.pop()
    
    if random.random() < 0.53:
        if choice == 'high':
            player_card = max(bot_card - 1, 2)
        else:
            player_card = min(bot_card + 1, 14)
    
    rank = {11:'j',12:'q',13:'k',14:'a'}
    p_rank = rank.get(player_card, player_card)
    b_rank = rank.get(bot_card, bot_card)
    
    if player_card > bot_card:
        winnings = bet * 2
        database.update_tokens(str(interaction.user.id), winnings)
        database.record_gambling_result(str(interaction.user.id), True)
        embed = discord.Embed(color=discord.Color.green(), description=f'you: {p_rank}, bot: {b_rank} - you win **{winnings}** tokens!')
        await interaction.response.send_message(embed=embed)
    else:
        database.record_gambling_result(str(interaction.user.id), False)
        embed = discord.Embed(color=discord.Color.red(), description=f'you: {p_rank}, bot: {b_rank} - you lose **{bet}** tokens!')
        await interaction.response.send_message(embed=embed)

@client.tree.command(name='gambling_help', description='Show all gambling games.')
async def gambling_help(interaction: discord.Interaction):
    if not check_channel(interaction): return await interaction.response.send_message('Wrong channel.', ephemeral=True)
    embed = discord.Embed(title='Gambling Games', color=discord.Color.gold(), description=
        '• /dice <bet> - Roll dice, higher wins (2x)\n'
        '• /coinflip <bet> <heads/tails> - Flip coin (2x)\n'
        '• /slots <bet> - Spin slots (5x jackpot)\n'
        '• /highlow <bet> <high/low> - High/Low card (2x)\n'
        'Good luck!'
    )
    await interaction.response.send_message(embed=embed)

@client.tree.command(name='help', description='Show all available commands.')
async def help(interaction: discord.Interaction):
    if not check_channel(interaction): return await interaction.response.send_message('Wrong channel.', ephemeral=True)
    
    is_admin = is_owner(interaction)
    
    user_cmds = (
        '**User Commands:**\n'
        '• /register_in_economy <ign> - Start registration\n'
        '• /verify <code> - Verify your Minecraft account\n'
        '• /balance - Check your token balance\n'
        '• /stats - View your order statistics\n'
        '• /claim_daily_tokens - Get free daily tokens\n'
        '• /kit_list - View available kits and prices\n'
        '• /order_kit <type> <qty> - Order a kit\n'
        '• /dice <bet> - Roll dice (2x)\n'
        '• /coinflip <bet> <heads/tails> - Flip coin (2x)\n'
        '• /slots <bet> - Spin slots (5x jackpot)\n'
        '• /highlow <bet> <high/low> - High/Low card (2x)\n'
        '• /gambling_help - Gambling games info\n'
        '• /help - Show this message'
    )
    
    admin_cmds = (
        '**Admin Commands:**\n'
        '• /give_tokens_to_player <user> <amount> - Give tokens\n'
        '• /take_tokens_from_player <user> <amount> - Take tokens\n'
        '• /give_all_players_tokens <amount> - Give to all\n'
        '• /take_from_all_players_tokens <amount> - Take from all\n'
        '• /admin_balance <user> - Check user balance\n'
        '• /admin_stats <user> - Check user stats\n'
        '• /refund <user> <amount> - Manual refund'
    )
    
    embed = discord.Embed(title='Help', color=discord.Color.blue())
    embed.description = user_cmds + (admin_cmds if is_admin else '\n\n*Run admin commands to see admin help.*')
    await interaction.response.send_message(embed=embed)


client.run(Config.DISCORD_BOT_TOKEN)