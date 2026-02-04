import discord
from discord.ext import commands
import json
import os
import asyncio
import logging
import shutil
from typing import Dict, Any, Optional, List

from translation_manager import TranslationManager
from game_logic import BunkerGame, GamePhase, Player

# =========================
# CONFIG & LOGGING
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bunker_bot")

DB_FILE = "users.json"
ACTIVE_GAMES_FILE = "active_games.json"

# =========================
# STYLE & THEME (Ваш новий дизайн)
# =========================
class Theme:
    PRIMARY = 0x9b59b6   # Фіолетовий
    SUCCESS = 0x2ecc71   # Зелений
    ERROR = 0xe74c3c     # Червоний
    WARNING = 0xf1c40f   # Жовтий
    INFO = 0x3498db      # Синій

def create_embed(title: str = None, description: str = "", type: str = "primary", footer: str = None) -> discord.Embed:
    """
    Генерує Embed у стилі bdscript/$description.
    """
    colors = {
        "primary": Theme.PRIMARY,
        "success": Theme.SUCCESS,
        "error": Theme.ERROR,
        "warning": Theme.WARNING,
        "info": Theme.INFO
    }
    
    # Якщо заголовок не передано, але це помилка/успіх, додаємо іконку в опис
    if not title:
        if type == "error": description = f"❌ {description}"
        elif type == "success": description = f"✅ {description}"
    
    embed = discord.Embed(
        title=title,
        description=description,
        color=colors.get(type, Theme.PRIMARY)
    )
    if footer:
        embed.set_footer(text=footer)
    return embed

# =========================
# DATA STORAGE MANAGER
# =========================
class DataManager:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.data = {"users": {}, "servers": {}}
        
    async def load(self):
        if not os.path.exists(DB_FILE):
            await self.save()
            return
        async with self.lock:
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {"users": {}, "servers": {}}

    async def save(self):
        async with self.lock:
            try:
                temp_file = f"{DB_FILE}.tmp"
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=4)
                shutil.move(temp_file, DB_FILE)
            except Exception as e:
                logger.error(f"DB Save Error: {e}")

    def get_server_lang(self, guild_id: int) -> str:
        return self.data["servers"].get(str(guild_id), {}).get("lang", "uk")

    async def set_server_lang(self, guild_id: int, lang: str):
        gid = str(guild_id)
        if gid not in self.data["servers"]: self.data["servers"][gid] = {}
        self.data["servers"][gid]["lang"] = lang
        await self.save()

    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {
                "name": None, "games": 0, "wins": 0, "deaths": 0
            }
        return self.data["users"][uid]

    async def update_stats(self, user_id: int, key: str, val: Any = 1):
        u = self.get_user_stats(user_id)
        if key in u:
            u[key] += val
        await self.save()

# =========================
# GAME PERSISTENCE
# =========================
class GameRepository:
    def __init__(self):
        self.games: Dict[int, BunkerGame] = {}
        self.lock = asyncio.Lock()
        
    async def save_all(self):
        async with self.lock:
            data = {str(gid): game.to_dict() for gid, game in self.games.items()}
            try:
                with open(ACTIVE_GAMES_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
            except Exception as e:
                logger.error(f"Game Save Error: {e}")

    async def load_all(self) -> int:
        if not os.path.exists(ACTIVE_GAMES_FILE): return 0
        try:
            with open(ACTIVE_GAMES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = 0
            for gid_str, g_data in data.items():
                try:
                    game = BunkerGame.from_dict(g_data)
                    self.games[int(gid_str)] = game
                    count += 1
                except Exception:
                    pass
            return count
        except Exception:
            return 0

# =========================
# UI VIEWS
# =========================
class BunkerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.tm = TranslationManager()
        self.db = DataManager()
        self.repo = GameRepository()

    async def setup_hook(self):
        self.tm.load_languages()
        await self.db.load()
        await self.repo.load_all()
        
        # Синхронізація команд (оновлення списку в Discord)
        await self.tree.sync()
        logger.info("Command tree synced successfully.")
        
        # Відновлюємо View
        for gid, game in self.repo.games.items():
            if game.phase == GamePhase.WAITING:
                self.add_view(JoinView(self, game))
            elif game.phase == GamePhase.VOTING:
                alive = game.get_alive_players()
                mx = 2 if game.double_elim_next else 1
                self.add_view(VoteView(self, game, alive, mx))
            else:
                self.add_view(DashboardView(self, game))

class JoinView(discord.ui.View):
    def __init__(self, bot: BunkerBot, game: BunkerGame):
        super().__init__(timeout=None)
        self.bot = bot
        self.game = game
        self.update_labels()

    def update_labels(self):
        lang = self.game.lang
        self.join_btn.label = self.bot.tm.get("ui.join_btn", lang)
        self.start_btn.label = self.bot.tm.get("ui.start_btn", lang)
        self.cancel_btn.label = self.bot.tm.get("ui.cancel_btn", lang)

    @discord.ui.button(style=discord.ButtonStyle.success, custom_id="join_btn")
    async def join_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if self.game.add_player(interaction.user.id, interaction.user.display_name):
            # Стилізоване ефемерне повідомлення
            embed = create_embed(description=self.bot.tm.get("msg.joined", self.game.lang), type="success")
            await interaction.response.send_message(embed=embed, ephemeral=True, delete_after=3)
            
            await self.update_lobby_message(interaction)
            await self.bot.repo.save_all()
        else:
            embed = create_embed(description=self.bot.tm.get("msg.no_seats", self.game.lang), type="error")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="start_btn")
    async def start_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if interaction.user.id != self.game.host_id:
            return await interaction.response.send_message(
                embed=create_embed(description=self.bot.tm.get("msg.only_host", self.game.lang), type="error"), 
                ephemeral=True
            )
        
        data_source = self.bot.tm.get_raw("data", self.game.lang)
        self.game.start(data_source)
        
        await interaction.message.delete()
        
        # INTRO EMBED
        intro_embed = create_embed(title="☢️ INTRO", description=self.game.lore_text, type="error")
        await interaction.channel.send(embed=intro_embed)
        
        await self.send_fresh_board(interaction.channel)
        await self.bot.repo.save_all()

    @discord.ui.button(style=discord.ButtonStyle.danger, custom_id="cancel_btn")
    async def cancel_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if interaction.user.id != self.game.host_id: return
        del self.bot.repo.games[self.game.guild_id]
        await interaction.message.delete()
        await self.bot.repo.save_all()
        
        # Cancel Message
        embed = create_embed(description=self.bot.tm.get("msg.game_cancelled", self.game.lang), type="error")
        await interaction.response.send_message(embed=embed, ephemeral=True, delete_after=3)

    async def update_lobby_message(self, interaction):
        # LOBBY EMBED
        desc = f"**Players:** {len(self.game.players)}/{self.game.max_players}\n\nWaiting for host to start..."
        embed = create_embed(title=self.bot.tm.get("ui.lobby_title", self.game.lang), description=desc, type="warning")
        await interaction.message.edit(embed=embed, view=self)

    async def send_fresh_board(self, channel):
        embed = self.generate_board_embed()
        view = DashboardView(self.bot, self.game)
        msg = await channel.send(embed=embed, view=view)
        self.game.board_msg_id = msg.id
        self.game.channel_id = channel.id

    def generate_board_embed(self) -> discord.Embed:
        titles = self.bot.tm.get_raw("card_titles", self.game.lang)
        ptxt = ""
        for p in self.game.players:
            status = "🟢" if p.alive else "💀"
            if not p.alive:
                ptxt += f"{status} ~~{p.name}~~\n\n"
                continue
            
            revealed = []
            for k, v in p.cards.items():
                if p.opened.get(k, False):
                    t = titles.get(k, k)
                    # Форматування списком, як на скріншоті
                    revealed.append(f"**{t}**: {v}")
            
            # Якщо є відкриті карти, показуємо їх красиво
            cards_str = "\n".join([f"> {r}" for r in revealed]) if revealed else "> *???*"
            ptxt += f"{status} **{p.name}**\n{cards_str}\n\n"
        
        stats = f"**Spots:** {self.game.bunker_spots} | **Alive:** {len(self.game.get_alive_players())}"
        
        return create_embed(
            title=self.bot.tm.get("ui.status_title", self.game.lang), 
            description=f"{stats}\n\n{ptxt}", 
            type="primary"
        )

class DashboardView(discord.ui.View):
    def __init__(self, bot: BunkerBot, game: BunkerGame):
        super().__init__(timeout=None)
        self.bot = bot
        self.game = game
        lang = game.lang
        
        self.add_item(discord.ui.Button(label=bot.tm.get("ui.profile_btn", lang), emoji="📂", custom_id=f"dash:prof:{game.guild_id}", row=0))
        self.add_item(discord.ui.Button(label=bot.tm.get("ui.reveal_btn", lang), emoji="📢", custom_id=f"dash:rev:{game.guild_id}", row=0))
        self.add_item(discord.ui.Button(label=bot.tm.get("ui.vote_start_btn", lang), emoji="🔴", style=discord.ButtonStyle.danger, custom_id=f"dash:vote:{game.guild_id}", row=1))

        self.children[0].callback = self.profile_callback
        self.children[1].callback = self.reveal_callback
        self.children[2].callback = self.vote_callback

    async def profile_callback(self, interaction: discord.Interaction):
        p = self.game.get_player(interaction.user.id)
        if not p: 
            return await interaction.response.send_message(embed=create_embed(description="You are not in the game.", type="error"), ephemeral=True)
        
        titles = self.bot.tm.get_raw("card_titles", self.game.lang)
        # Красивий список для профілю
        desc = ""
        for k, v in p.cards.items():
            desc += f"🔹 **{titles.get(k, k)}**: {v}\n"
        
        await interaction.response.send_message(
            embed=create_embed(title=f"📂 {p.name}", description=desc, type="info"), 
            ephemeral=True
        )

    async def reveal_callback(self, interaction: discord.Interaction):
        p = self.game.get_player(interaction.user.id)
        if not p or not p.alive: 
            return await interaction.response.send_message(embed=create_embed(description="Dead or not playing.", type="error"), ephemeral=True)
        
        opts = []
        titles = self.bot.tm.get_raw("card_titles", self.game.lang)
        for k, v in p.cards.items():
            if not p.opened.get(k):
                opts.append(discord.SelectOption(label=titles.get(k, k), value=k, description=str(v)[:50]))
        
        if not opts:
            return await interaction.response.send_message(
                embed=create_embed(description=self.bot.tm.get("msg.reveal_nothing", self.game.lang), type="warning"), 
                ephemeral=True
            )
            
        view = discord.ui.View()
        sel = discord.ui.Select(options=opts, max_values=min(len(opts), 2), placeholder=self.bot.tm.get("ui.reveal_placeholder", self.game.lang))
        
        async def sel_callback(inter):
            rev_txt_parts = []
            for val in sel.values:
                p.opened[val] = True
                rev_txt_parts.append(f"✅ **{titles.get(val, val)}**: {p.cards[val]}")
            
            # Ефемерне підтвердження
            await inter.response.send_message(
                embed=create_embed(description=self.bot.tm.get("msg.reveal_success", self.game.lang), type="success"), 
                ephemeral=True, delete_after=3
            )
            
            await self.update_existing_board(inter)

            # Публічний лог (зникає через 10с)
            name_txt = self.bot.tm.get("msg.reveal_public_title", self.game.lang, name=p.name)
            await inter.channel.send(
                embed=create_embed(title=name_txt, description="\n".join(rev_txt_parts), type="success"),
                delete_after=10 
            )
            
            await self.bot.repo.save_all()
            
        sel.callback = sel_callback
        view.add_item(sel)
        await interaction.response.send_message(
            embed=create_embed(description="Select cards to reveal:", type="primary"), 
            view=view, ephemeral=True
        )

    async def vote_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.host_id:
            return await interaction.response.send_message(
                embed=create_embed(description=self.bot.tm.get("msg.only_host", self.game.lang), type="error"), 
                ephemeral=True
            )
        
        alive = self.game.get_alive_players()
        if len(alive) <= self.game.bunker_spots:
             return await interaction.response.send_message(
                 embed=create_embed(description="Game condition met. Please wait or check logic.", type="warning"), 
                 ephemeral=True
             )

        self.game.phase = GamePhase.VOTING
        self.game.votes.clear()
        
        # Видаляємо старий борд
        if self.game.channel_id and self.game.board_msg_id:
            try:
                old_msg = await interaction.channel.fetch_message(self.game.board_msg_id)
                await old_msg.delete()
            except: pass
            self.game.board_msg_id = None

        mx = 2 if self.game.double_elim_next else 1
        
        # VOTE EMBED
        desc = self.bot.tm.get("ui.vote_desc", self.game.lang)
        if self.game.double_elim_next:
            desc += f"\n\n{self.bot.tm.get('ui.vote_footer_double', self.game.lang)}"
            
        embed = create_embed(title=self.bot.tm.get("ui.vote_title", self.game.lang), description=desc, type="warning")

        await interaction.response.send_message(embed=create_embed(description="Voting started...", type="info"), ephemeral=True, delete_after=1)
        await interaction.channel.send(embed=embed, view=VoteView(self.bot, self.game, alive, mx))
        await self.bot.repo.save_all()

    async def update_existing_board(self, interaction):
        if self.game.channel_id and self.game.board_msg_id:
            try:
                ch = interaction.guild.get_channel(self.game.channel_id)
                msg = await ch.fetch_message(self.game.board_msg_id)
                helper = JoinView(self.bot, self.game)
                await msg.edit(embed=helper.generate_board_embed())
            except: pass

class VoteView(discord.ui.View):
    def __init__(self, bot: BunkerBot, game: BunkerGame, candidates: List[Player], max_sel: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.game = game
        
        opts = [discord.SelectOption(label=p.name, value=str(p.user_id), emoji="👤") for p in candidates]
        sel = discord.ui.Select(placeholder=bot.tm.get("ui.vote_placeholder", game.lang), options=opts, max_values=max_sel)
        sel.callback = self.vote_cb
        self.add_item(sel)
        
        btn = discord.ui.Button(label=self.bot.tm.get("ui.end_vote_btn", game.lang), style=discord.ButtonStyle.secondary, custom_id="end_vote_btn")
        btn.callback = self.end_cb
        self.add_item(btn)

    async def vote_cb(self, interaction: discord.Interaction):
        try:
            targets = [int(v) for v in interaction.data["values"]]
            self.game.register_vote(interaction.user.id, targets)
            await interaction.response.send_message(
                embed=create_embed(description=self.bot.tm.get("msg.vote_accepted", self.game.lang), type="success"), 
                ephemeral=True, delete_after=3
            )
            await self.bot.repo.save_all()
        except ValueError as e:
            await interaction.response.send_message(
                embed=create_embed(description=str(e), type="error"), 
                ephemeral=True
            )

    async def end_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.host_id:
             return await interaction.response.send_message(
                 embed=create_embed(description=self.bot.tm.get("msg.only_host", self.game.lang), type="error"), 
                 ephemeral=True
             )
        
        await interaction.message.delete()
        eliminated, is_draw = self.game.resolve_votes()
        
        result_embed = None
        if is_draw:
            result_embed = create_embed(
                title=self.bot.tm.get("msg.draw", self.game.lang), 
                description=self.bot.tm.get("msg.draw_desc", self.game.lang),
                type="warning"
            )
        else:
            txt = ""
            for p in eliminated:
                txt += f"💀 **{p.name}**\n"
                await self.bot.db.update_stats(p.user_id, "deaths", 1)
            
            result_embed = create_embed(
                title=self.bot.tm.get("ui.results_title", self.game.lang), 
                description=txt, 
                type="error"
            )

        res_msg = await interaction.channel.send(embed=result_embed)
        
        if self.game.check_end_condition():
             await asyncio.sleep(5)
             await res_msg.delete()
             
             winners = self.game.get_alive_players()
             names = ", ".join([p.name for p in winners])
             for p in winners: await self.bot.db.update_stats(p.user_id, "wins", 1)
             
             # FINAL EMBED
             await interaction.channel.send(embed=create_embed(
                 title="🎉 VICTORY", 
                 description=f"**Survivors:** {names}", 
                 type="primary"
             ))
             del self.bot.repo.games[self.game.guild_id]
        else:
            self.game.phase = GamePhase.REVEAL
            asyncio.create_task(self.restore_game_flow(interaction.channel, res_msg))
        
        await self.bot.repo.save_all()

    async def restore_game_flow(self, channel, result_msg):
        await asyncio.sleep(10)
        try: await result_msg.delete()
        except: pass
        
        helper = JoinView(self.bot, self.game)
        await helper.send_fresh_board(channel)
        await self.bot.repo.save_all()

# =========================
# MAIN EXECUTION
# =========================
if __name__ == "__main__":
    if not os.path.exists("config.json"):
        with open("config.json", "w") as f: json.dump({"token": ""}, f)
    
    with open("config.json", "r") as f:
        conf = json.load(f)
    
    token = os.getenv("DISCORD_BOT_TOKEN") or conf.get("token")
    
    bot = BunkerBot()
    
    @bot.tree.command(name="create")
    async def create(interaction: discord.Interaction, players: int):
        if interaction.guild_id in bot.repo.games:
            return await interaction.response.send_message(
                embed=create_embed(description="Game already active in this server.", type="error"), 
                ephemeral=True
            )
        
        lang = bot.db.get_server_lang(interaction.guild_id)
        game = BunkerGame(interaction.guild_id, interaction.user.id, players, lang)
        game.add_player(interaction.user.id, interaction.user.display_name)
        
        bot.repo.games[interaction.guild_id] = game
        
        # Lobby Embed
        desc = f"**Players:** 1/{players}\n\nWaiting for host..."
        await interaction.response.send_message(
            embed=create_embed(title=bot.tm.get("ui.lobby_title", lang), description=desc, type="warning"), 
            view=JoinView(bot, game)
        )
        await bot.repo.save_all()

    @bot.tree.command(name="language")
    async def language(interaction: discord.Interaction):
        opts = [discord.SelectOption(label=n, value=c) for c, n in bot.tm.get_available_languages().items()]
        view = discord.ui.View()
        sel = discord.ui.Select(options=opts)
        
        async def cb(inter):
            await bot.db.set_server_lang(inter.guild_id, sel.values[0])
            await inter.response.send_message(
                embed=create_embed(description="Language updated / Мову змінено.", type="success"), 
                ephemeral=True
            )
        sel.callback = cb
        view.add_item(sel)
        await interaction.response.send_message(
            embed=create_embed(title="Language", description="Select language:", type="primary"), 
            view=view, ephemeral=True
        )

    # NEW STOP COMMAND
    @bot.tree.command(name="stop", description="Force stop the current game (Admin/Host)")
    async def stop(interaction: discord.Interaction):
        game = bot.repo.games.get(interaction.guild_id)
        if not game:
            return await interaction.response.send_message(
                embed=create_embed(description="No active game found / Немає активної гри.", type="error"),
                ephemeral=True
            )

        # Check permissions: Host or Admin
        is_admin = interaction.user.guild_permissions.administrator
        is_host = (interaction.user.id == game.host_id)

        if not (is_host or is_admin):
            return await interaction.response.send_message(
                embed=create_embed(description="Only Host or Admin can stop the game.", type="error"),
                ephemeral=True
            )

        # Cleanup dashboard if exists
        if game.channel_id and game.board_msg_id:
            try:
                ch = interaction.guild.get_channel(game.channel_id)
                msg = await ch.fetch_message(game.board_msg_id)
                await msg.delete()
            except:
                pass
        
        del bot.repo.games[interaction.guild_id]
        await bot.repo.save_all()

        await interaction.response.send_message(
            embed=create_embed(title="🛑 Game Stopped", description="The game was forcibly ended by Admin/Host.", type="error")
        )

    bot.run(token)