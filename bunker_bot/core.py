import asyncio
import json
import logging
import math
import os
import random
import shutil
from enum import Enum
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord.ext import commands

# =========================
#  LOGGING SETUP
# =========================

def setup_logging() -> logging.Logger:
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    file_handler = RotatingFileHandler(
        "bunker.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_formatter)

    logger = logging.getLogger("bunker_bot")
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


logger = setup_logging()

# =========================
#  CONFIG LOADER
# =========================
if not os.path.exists("config.json"):
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump({"token": ""}, f)

with open("config.json", "r", encoding="utf-8") as f:
    try:
        CONFIG = json.load(f)
    except json.JSONDecodeError:
        CONFIG = {}

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or CONFIG.get("token")

# =========================
#  CONSTANTS
# =========================
DB_FILE = "users.json"
GAME_DB_FILE = "active_games.json"
LANG_FILE = "languages.json"

# Timeouts (in seconds)
LOBBY_TIMEOUT = 3600  # 1 hour
DASHBOARD_TIMEOUT = 7200  # 2 hours
VOTE_TIMEOUT = 900  # 15 minutes (Increased for better UX)
EPHEMERAL_VIEW_TIMEOUT = 180  # 3 minutes

# Message Lifetimes (in seconds)
BRIEF_MSG_LIFETIME = 3
ANNOUNCEMENT_LIFETIME = 15
RESULT_MSG_LIFETIME = 20

# =========================
#  THEME / COLORS
# =========================
class EmbedColors:
    LOBBY = discord.Color.orange()
    GAME_INFO = discord.Color.dark_teal()
    VOTING = discord.Color.gold()
    ELIMINATION = discord.Color.dark_red()
    VICTORY = discord.Color.purple()
    SUCCESS = discord.Color.green()
    ERROR = discord.Color.red()
    INFO = discord.Color.blue()
    INTRO = discord.Color.dark_red()


_user_db_lock = asyncio.Lock()
_game_db_lock = asyncio.Lock()

# In-memory cache for users
global_db: Dict[str, Any] = {"users": {}, "servers": {}}

# =========================
#  DATABASE HELPERS
# =========================

def _load_json_file(filepath: str) -> Dict[str, Any]:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


async def load_user_db() -> Dict[str, Any]:
    global global_db
    if not os.path.exists(DB_FILE):
        await save_user_db_data({"users": {}, "servers": {}})
        return {"users": {}, "servers": {}}

    try:
        async with _user_db_lock:
            def read_primary():
                return _load_json_file(DB_FILE)

            try:
                data = await asyncio.to_thread(read_primary)
            except Exception as e:
                logger.error(
                    f"Primary User DB corrupt: {e}. Attempting backup recovery..."
                )

                # Attempt Backup Recovery
                if os.path.exists(f"{DB_FILE}.backup"):
                    def read_backup():
                        return _load_json_file(f"{DB_FILE}.backup")

                    try:
                        data = await asyncio.to_thread(read_backup)
                        logger.info("Recovered User DB from backup!")
                    except Exception as backup_e:
                        logger.critical(
                            f"Backup User DB also corrupt: {backup_e}. Starting fresh."
                        )
                        data = {"users": {}, "servers": {}}
                else:
                    logger.error("No User DB backup found. Starting fresh.")
                    data = {"users": {}, "servers": {}}

            # Data validation/migration
            if "users" not in data:
                global_db = {"users": data, "servers": {}}
            else:
                global_db = data
            return global_db
    except Exception as e:
        logger.error(f"User DB Load Error: {e}")
        return {"users": {}, "servers": {}}


async def save_user_db_data(data: Dict[str, Any]) -> None:
    try:
        async with _user_db_lock:
            def write():
                # Create backup before overwrite
                if os.path.exists(DB_FILE):
                    try:
                        shutil.copy2(DB_FILE, f"{DB_FILE}.backup")
                    except Exception as e:
                        logger.warning(f"Failed to create User DB backup: {e}")

                with open(DB_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)

            await asyncio.to_thread(write)
    except Exception as e:
        logger.error(f"User DB Write Error: {e}")


async def save_raw_active_games(data_dict: Dict[str, Any]) -> None:
    """Saves the dictionary of active games to JSON file."""
    try:
        async with _game_db_lock:
            def write():
                # Create backup before overwrite
                if os.path.exists(GAME_DB_FILE):
                    try:
                        shutil.copy2(GAME_DB_FILE, f"{GAME_DB_FILE}.backup")
                    except Exception as e:
                        logger.warning(f"Failed to create Game DB backup: {e}")

                with open(GAME_DB_FILE, "w", encoding="utf-8") as f:
                    json.dump(data_dict, f, ensure_ascii=False, indent=4)

            await asyncio.to_thread(write)
    except Exception as e:
        logger.error(f"Game DB Save Error: {e}")


async def load_raw_active_games() -> Dict[str, Any]:
    """Loads raw JSON data for active games."""
    if not os.path.exists(GAME_DB_FILE):
        return {}

    try:
        async with _game_db_lock:
            def read_primary():
                return _load_json_file(GAME_DB_FILE)

            try:
                return await asyncio.to_thread(read_primary)
            except Exception as e:
                logger.error(
                    f"Primary Game DB corrupt: {e}. Attempting backup recovery..."
                )

                # Attempt Backup Recovery
                if os.path.exists(f"{GAME_DB_FILE}.backup"):
                    def read_backup():
                        return _load_json_file(f"{GAME_DB_FILE}.backup")

                    try:
                        data = await asyncio.to_thread(read_backup)
                        logger.info("Recovered Game DB from backup!")
                        return data
                    except Exception as backup_e:
                        logger.critical(f"Backup Game DB also corrupt: {backup_e}.")
                        return {}
                else:
                    logger.error("No Game DB backup found.")
                    return {}

    except Exception as e:
        logger.error(f"Game DB Load Error: {e}")
        return {}


# --- ACCESSORS ---

def get_server_lang(guild_id: int) -> str:
    gid = str(guild_id)
    return global_db["servers"].get(gid, {}).get("lang", "uk")


def get_server_stats(guild_id: int) -> int:
    gid = str(guild_id)
    return global_db["servers"].get(gid, {}).get("games_played", 0)


def get_user_data(user_id: int) -> Dict[str, Any]:
    uid = str(user_id)
    if uid not in global_db["users"]:
        global_db["users"][uid] = {
            "name": None,
            "games": 0,
            "wins": 0,
            "deaths": 0,
            "total_age": 0,
            "sex_stats": {"m": 0, "f": 0},
        }
    u = global_db["users"][uid]
    if "total_age" not in u:
        u["total_age"] = 0
    if "sex_stats" not in u:
        u["sex_stats"] = {"m": 0, "f": 0}
    return u


async def set_server_lang(guild_id: int, lang: str) -> None:
    gid = str(guild_id)
    if gid not in global_db["servers"]:
        global_db["servers"][gid] = {}
    global_db["servers"][gid]["lang"] = lang
    await save_user_db_data(global_db)


async def update_user_stats(user_id: int, key: str, val: Any = 1) -> None:
    u = get_user_data(user_id)
    if key == "game_start" and isinstance(val, dict):
        u["games"] += 1
        u["total_age"] += val.get("age", 0)
        sex_key = "m" if val.get("sex_idx") == 0 else "f"
        u["sex_stats"][sex_key] += 1
    elif key in u:
        u[key] += val
    await save_user_db_data(global_db)


async def reset_user_stats(user_id: int) -> None:
    u = get_user_data(user_id)
    u["games"] = 0
    u["wins"] = 0
    u["deaths"] = 0
    u["total_age"] = 0
    u["sex_stats"] = {"m": 0, "f": 0}
    await save_user_db_data(global_db)


async def update_server_games(guild_id: int) -> None:
    gid = str(guild_id)
    if gid not in global_db["servers"]:
        global_db["servers"][gid] = {}
    srv = global_db["servers"][gid]
    srv["games_played"] = srv.get("games_played", 0) + 1
    await save_user_db_data(global_db)


async def set_custom_name(user_id: int, name: str) -> None:
    u = get_user_data(user_id)
    u["name"] = name
    await save_user_db_data(global_db)


# =========================
#  I18N
# =========================
LANGUAGES: Dict[str, Any] = {}


async def load_languages() -> None:
    """Asynchronously load language data from disk into the global dict."""
    if not os.path.exists(LANG_FILE):
        logger.critical(f"{LANG_FILE} not found.")
        return

    def _read():
        with open(LANG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    try:
        data = await asyncio.to_thread(_read)
        # Update existing dictionary instead of reassigning variable
        LANGUAGES.clear()
        LANGUAGES.update(data)
        logger.info(
            f"Languages loaded successfully. Available: {list(LANGUAGES.keys())}"
        )
    except json.JSONDecodeError as e:
        logger.critical(f"Failed to parse {LANG_FILE}: {e}")
    except Exception as e:
        logger.critical(f"Error loading languages: {e}")


def T(key: str, ctx_or_lang: Any, **kwargs: Any) -> Any:
    """
    Get localized string.
    ctx_or_lang: can be 'uk'/'en' string OR interaction/context object
    """
    lang = "uk"
    if isinstance(ctx_or_lang, str):
        lang = ctx_or_lang
    elif hasattr(ctx_or_lang, "guild") and ctx_or_lang.guild:
        lang = get_server_lang(ctx_or_lang.guild.id)

    # Try to get data for the requested language
    # Default to UK if language itself is missing from file
    data = LANGUAGES.get(lang, LANGUAGES.get("uk", {}))

    keys = key.split(".")

    for k in keys:
        if isinstance(data, dict) and k in data:
            data = data[k]
        else:
            # Key missing in target language
            if lang != "uk":
                logger.warning(
                    f"Translation missing for key '{key}' in language '{lang}', falling back to UK"
                )

            # Fallback to UK (Default)
            data = LANGUAGES.get("uk", {})
            for fk in keys:
                if isinstance(data, dict) and fk in data:
                    data = data[fk]
                else:
                    return f"[{key}]"  # Missing key even in default language
            break

    if isinstance(data, str):
        try:
            return data.format(**kwargs)
        except Exception as e:
            logger.error(f"Formatting error for key '{key}': {e}")
            return data
    return data


# =========================
#  GAME LOGIC
# =========================

games: Dict[int, "GameState"] = {}
_games_lock = asyncio.Lock()


async def get_game(guild_id: int) -> Optional["GameState"]:
    """Thread-safe retrieval of a game instance."""
    async with _games_lock:
        return games.get(guild_id)


async def set_game(guild_id: int, game: "GameState") -> None:
    """Thread-safe assignment of a game instance."""
    async with _games_lock:
        games[guild_id] = game


class SaveManager:
    """
    Handles game state persistence with debouncing to prevent
    disk I/O thrashing and race conditions.
    """

    _save_scheduled = False
    _lock = asyncio.Lock()

    @classmethod
    async def request(cls) -> None:
        """Schedules a save operation in the near future (Debounce).

        This method uses a lock to ensure thread safety when checking and setting
        the schedule flag, preventing multiple concurrent saves.
        """
        async with cls._lock:
            if cls._save_scheduled:
                return
            cls._save_scheduled = True

        # Debounce delay outside the lock to allow other tasks to run
        await asyncio.sleep(2.0)

        await cls.force()

        async with cls._lock:
            cls._save_scheduled = False

    @classmethod
    async def force(cls) -> None:
        """Immediately serializes and saves all active games to disk."""
        async with cls._lock:
            try:
                # Protect iteration over games dict
                async with _games_lock:
                    data = {str(gid): game.to_dict() for gid, game in games.items()}
            except Exception as e:
                logger.error(f"Serialization Error in SaveManager: {e}")
                return

            await save_raw_active_games(data)


class GamePhase(Enum):
    """Enum representing the current phase of the game."""

    WAITING = 1
    REVEAL = 2
    VOTING = 3
    FINISHED = 4


class Player:
    """Represents a single player in the game."""

    def __init__(self, user_id: int, discord_name: str, lang: str):
        self.user_id = user_id
        self.lang = lang
        u = get_user_data(user_id)
        self.name = u["name"] if u["name"] else discord_name
        self.alive = True
        self.cards: Dict[str, str] = {}
        self.opened: Dict[str, bool] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "lang": self.lang,
            "alive": self.alive,
            "cards": self.cards,
            "opened": self.opened,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Player":
        p = cls(data["user_id"], data["name"], data["lang"])
        p.alive = data["alive"]
        p.cards = data["cards"]
        p.opened = data["opened"]
        return p

    def generate(self) -> None:
        D = T("data", self.lang)
        H_Dict = T("health", self.lang)
        P_Dict = T("phobias", self.lang)

        h_keys = list(H_Dict.keys()) if isinstance(H_Dict, dict) else ["Healthy"]
        p_keys = list(P_Dict.keys()) if isinstance(P_Dict, dict) else ["None"]

        self.cards = {
            "sex": D["sexes"][random.randint(0, 1)],
            "age": str(random.randint(18, 90)),
            "height": str(random.randint(150, 210)) + " cm",
            "body": random.choice(D["bodies"]),
            "job": random.choice(D["jobs"]),
            "health": random.choice(h_keys),
            "hobby": random.choice(D["hobbies"]),
            "phobia": random.choice(p_keys),
            "inventory": random.choice(D["inventory"]),
            "extra": random.choice(D["extra"]),
        }
        self.opened = {k: False for k in self.cards}

    def get_profile_text(self, show_hidden: bool = False) -> str:
        lines = []
        titles = T("card_titles", self.lang)
        for key, title in titles.items():
            value = self.cards.get(key, "???")
            is_open = self.opened.get(key, False)
            status = "✅" if is_open or show_hidden else "🔒"
            val_text = value if is_open or show_hidden else "???"
            lines.append(f"{status} **{title}**: {val_text}")
        return "\n".join(lines)


class GameState:
    """Manages the state of a single game session."""

    def __init__(self, max_players: int, host_id: int, lang: str, guild_id: int):
        self.max_players = max_players
        self.host_id = host_id
        self.lang = lang
        self.guild_id = guild_id
        self.players: List[Player] = []
        self.phase = GamePhase.WAITING
        self.bunker_spots = 0
        self.lore_text = ""
        self.votes: Dict[int, List[int]] = {}
        self.double_elim_next = False

        self.board_msg_id: Optional[int] = None
        self.dash_msg_id: Optional[int] = None
        self.channel_id: Optional[int] = None

        self.board_message: Optional[discord.Message] = None
        self.dashboard_view: Optional[discord.ui.View] = None
        self.join_view: Optional[discord.ui.View] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_players": self.max_players,
            "host_id": self.host_id,
            "lang": self.lang,
            "guild_id": self.guild_id,
            "phase": self.phase.value,
            "bunker_spots": self.bunker_spots,
            "lore_text": self.lore_text,
            "votes": self.votes,
            "double_elim_next": self.double_elim_next,
            "board_msg_id": self.board_msg_id,
            "dash_msg_id": self.dash_msg_id,
            "channel_id": self.channel_id,
            "players": [p.to_dict() for p in self.players],
        }

    @classmethod
    def from_dict(cls, guild_id: int, data: Dict[str, Any]) -> "GameState":
        g = cls(data["max_players"], data["host_id"], data["lang"], guild_id)
        g.phase = GamePhase(data["phase"])
        g.bunker_spots = data["bunker_spots"]
        g.lore_text = data["lore_text"]
        g.votes = {
            int(k): [int(uid) for uid in v] for k, v in data["votes"].items()
        }
        g.double_elim_next = data["double_elim_next"]
        g.board_msg_id = data.get("board_msg_id")
        g.dash_msg_id = data.get("dash_msg_id")
        g.channel_id = data.get("channel_id")
        g.players = [Player.from_dict(p_data) for p_data in data["players"]]
        return g

    def validate(self) -> bool:
        """Validates the consistency of the loaded game state."""
        try:
            if not isinstance(self.players, list):
                return False

            alive = sum(1 for p in self.players if p.alive)
            if alive < 0 or alive > len(self.players):
                return False

            known_ids = {p.user_id for p in self.players}
            for voter_id, targets in self.votes.items():
                if voter_id not in known_ids:
                    return False
                if not isinstance(targets, list):
                    return False
                for target_id in targets:
                    if target_id not in known_ids:
                        return False
            return True
        except Exception as e:
            logger.warning(f"Validation failed for guild {self.guild_id}: {e}")
            return False

    def add_player(self, user_id: int, name: str) -> bool:
        if len(self.players) >= self.max_players:
            return False
        if any(p.user_id == user_id for p in self.players):
            return False

        # Security: Sanitize name to prevent exploits
        safe_name = discord.utils.escape_mentions(name)
        safe_name = discord.utils.escape_markdown(safe_name)
        safe_name = safe_name[:20]  # Enforce length limit

        self.players.append(Player(user_id, safe_name, self.lang))
        # Request save instead of saving immediately
        asyncio.create_task(SaveManager.request())
        return True

    def get_player(self, user_id: int) -> Optional[Player]:
        return next((p for p in self.players if p.user_id == user_id), None)

    def alive_players(self) -> List[Player]:
        return [p for p in self.players if p.alive]

    async def start_game(self) -> None:
        logger.info(f"Starting game in guild {self.guild_id}")
        count = len(self.players)
        self.bunker_spots = max(1, math.ceil(count / 2))

        await update_server_games(self.guild_id)
        D = T("data", self.lang)

        for p in self.players:
            p.generate()

        self.lore_text = (
            f"{random.choice(D['catastrophes'])}\n\n"
            f"**Loc**: {random.choice(D['bunker_types'])}\n"
            f"**Cond**: {random.choice(D['supplies'])}\n"
            f"⏳ {random.choice(D['durations'])}"
        )
        self.phase = GamePhase.REVEAL
        asyncio.create_task(SaveManager.request())

    async def end_game(self, bot: commands.Bot) -> None:
        logger.info(f"Ending game in guild {self.guild_id}")
        self.phase = GamePhase.FINISHED

        if self.dashboard_view:
            self.dashboard_view.stop()
        if self.join_view:
            self.join_view.stop()

        if self.channel_id:
            try:
                ch = bot.get_channel(self.channel_id)
                if not ch:
                    try:
                        ch = await bot.fetch_channel(self.channel_id)
                    except Exception:
                        pass

                if ch:
                    if self.dash_msg_id:
                        try:
                            msg = await ch.fetch_message(self.dash_msg_id)
                            await msg.delete()
                        except (discord.NotFound, discord.Forbidden):
                            pass
                        except discord.HTTPException as e:
                            if e.status == 429:
                                logger.warning(
                                    "Guild %s: Rate limited deleting dashboard: %s",
                                    self.guild_id,
                                    e,
                                )
                            else:
                                logger.error(
                                    "Guild %s: HTTP error deleting dashboard: %s",
                                    self.guild_id,
                                    e,
                                )
                        except Exception as e:
                            logger.error(
                                "Guild %s: Unexpected error cleaning dashboard: %s",
                                self.guild_id,
                                e,
                            )

                    if self.board_msg_id:
                        try:
                            msg = await ch.fetch_message(self.board_msg_id)
                            await msg.delete()
                        except (discord.NotFound, discord.Forbidden):
                            pass
                        except discord.HTTPException as e:
                            if e.status == 429:
                                logger.warning(
                                    "Guild %s: Rate limited deleting board: %s",
                                    self.guild_id,
                                    e,
                                )
                            else:
                                logger.error(
                                    "Guild %s: HTTP error deleting board: %s",
                                    self.guild_id,
                                    e,
                                )
                        except Exception as e:
                            logger.error(
                                "Guild %s: Unexpected error cleaning board: %s",
                                self.guild_id,
                                e,
                            )
            except Exception as e:
                logger.warning(f"Guild {self.guild_id}: Channel cleanup error: {e}")

        self.players.clear()
        self.votes.clear()
        self.board_message = None
        self.dashboard_view = None
        self.join_view = None

        # Thread-safe removal from global games
        async with _games_lock:
            if self.guild_id in games:
                del games[self.guild_id]

        asyncio.create_task(SaveManager.force())

    async def register_vote(self, user_id: int, targets: List[int]) -> bool:
        """Registers a vote with validation."""
        voter = self.get_player(user_id)
        if not voter or not voter.alive:
            raise ValueError("Dead players cannot vote.")

        for target_id in targets:
            if target_id == user_id:
                raise ValueError("Self-voting is not allowed.")
            target = self.get_player(target_id)
            if not target or not target.alive:
                raise ValueError("Cannot vote for dead players.")

        self.votes[user_id] = [int(t) for t in targets]
        asyncio.create_task(SaveManager.request())
        return True

    def resolve_votes(self) -> Tuple[List[Player], str, bool]:
        alive_ids = {p.user_id for p in self.alive_players()}
        # Filter votes from dead people
        active_votes = {k: v for k, v in self.votes.items() if k in alive_ids}

        tally = {uid: 0 for uid in alive_ids}
        for vs in active_votes.values():
            for v in vs:
                # Strict check: only count votes for ALIVE targets
                if v in tally:
                    tally[v] += 1
                else:
                    logger.warning(
                        "Guild %s: Vote for invalid/dead target %s ignored.",
                        self.guild_id,
                        v,
                    )

        results = sorted(tally.items(), key=lambda x: x[1], reverse=True)
        if not results:
            return [], "No votes", False

        max_v = results[0][1]
        candidates = [uid for uid, c in results if c == max_v]

        eliminated = []
        text = ""
        is_draw = False

        if self.double_elim_next:
            self.double_elim_next = False
            # Logic: Select 2 candidates
            to_kick = list(candidates)
            if len(to_kick) < 2 and len(results) > len(to_kick):
                second_max = results[len(to_kick)][1]
                second_tier = [uid for uid, c in results if c == second_max]
                to_kick.extend(second_tier)

            random.shuffle(to_kick)
            for uid in to_kick[:2]:
                p = self.get_player(uid)
                if p and p.alive:
                    eliminated.append(p)
            text = T("msg.crit_round", self.lang)
        else:
            if len(candidates) > 1:
                self.double_elim_next = True
                self.phase = GamePhase.REVEAL
                self.votes.clear()
                is_draw = True
            else:
                p = self.get_player(candidates[0])
                if p and p.alive:
                    eliminated.append(p)
                text = T("msg.majority_decision", self.lang)

        asyncio.create_task(SaveManager.request())
        return eliminated, text, is_draw

    def calculate_ending(self) -> str:
        E = T("endings", self.lang)
        return E["neutral"]

    def generate_board_embed(self) -> discord.Embed:
        if self.phase == GamePhase.FINISHED:
            return discord.Embed(
                title=T("ui.win_title", self.lang), color=EmbedColors.VICTORY
            )

        embed = discord.Embed(title="📊 BUNKER DASHBOARD", color=discord.Color.dark_teal())

        host_lbl = T("ui.host_label", self.lang)
        pl_lbl = T("ui.players_label", self.lang)
        places_lbl = T("ui.places_label", self.lang)
        kick_lbl = T("ui.kick_label", self.lang)

        info = (
            f"{host_lbl} <@{self.host_id}>\n"
            f"👥 {pl_lbl} **{len(self.players)}**\n"
            f"🚪 {places_lbl} **{self.bunker_spots}**\n"
            f"☠️ {kick_lbl} **{len(self.players) - self.bunker_spots}**"
        )

        embed.add_field(name="📋 Info", value=info, inline=False)

        ptxt = ""
        titles = T("card_titles", self.lang)
        for p in self.players:
            status = "🟢" if p.alive else "💀"
            if not p.alive:
                ptxt += f"{status} ~~{p.name}~~\n\n"
                continue

            revealed = [
                f"> **{titles.get(k, k)}**: {v}"
                for k, v in p.cards.items()
                if p.opened.get(k)
            ]
            ptxt += (
                f"{status} **{p.name}**\n"
                + ("\n".join(revealed) if revealed else "> *???*")
                + "\n\n"
            )

        if len(ptxt) > 1024:
            ptxt = ptxt[:1020] + "..."
        embed.add_field(name="Players", value=ptxt, inline=False)
        return embed

    async def update_board(self, bot: commands.Bot) -> None:
        if not self.channel_id or not self.board_msg_id:
            return

        if not self.board_message:
            try:
                ch = bot.get_channel(self.channel_id)
                if ch:
                    self.board_message = await ch.fetch_message(self.board_msg_id)
                else:
                    logger.warning(
                        "Guild %s: Channel not found for update_board.",
                        self.guild_id,
                    )
                    return
            except discord.NotFound:
                logger.warning("Guild %s: Board message not found.", self.guild_id)
                self.board_msg_id = None
                return
            except discord.Forbidden:
                logger.warning(
                    "Guild %s: Permission denied for board update.",
                    self.guild_id,
                )
                return
            except discord.HTTPException as e:
                if e.status == 429:
                    logger.warning(
                        "Guild %s: Rate limited fetching board msg. Retry in %.2fs",
                        self.guild_id,
                        e.retry_after,
                    )
                else:
                    logger.error(
                        "Guild %s: HTTP error fetching board msg: %s",
                        self.guild_id,
                        e,
                    )
                return
            except Exception as e:
                logger.error(
                    "Guild %s: Fetch error in update_board: %s", self.guild_id, e
                )
                return

        if self.board_message:
            try:
                await self.board_message.edit(embed=self.generate_board_embed())
            except discord.NotFound:
                logger.warning(
                    "Guild %s: Board message deleted during edit.", self.guild_id
                )
                self.board_message = None
                self.board_msg_id = None
            except discord.HTTPException as e:
                if e.status == 429:
                    logger.warning(
                        "Guild %s: Rate limited editing board. Retry in %.2fs",
                        self.guild_id,
                        e.retry_after,
                    )
                else:
                    logger.error(
                        "Guild %s: HTTP error editing board: %s", self.guild_id, e
                    )
            except Exception as e:
                logger.error(
                    "Guild %s: Edit error in update_board: %s", self.guild_id, e
                )


async def save_active_games() -> None:
    await SaveManager.request()


async def delete_active_game(guild_id: int) -> None:
    if guild_id in games:
        del games[guild_id]
        await SaveManager.force()


async def load_active_games_from_disk() -> None:
    if not os.path.exists(GAME_DB_FILE):
        return
    try:
        data = await load_raw_active_games()
        for gid_str, g_data in data.items():
            gid = int(gid_str)
            try:
                game = GameState.from_dict(gid, g_data)
                # Validation Step
                if game.validate():
                    async with _games_lock:
                        games[gid] = game
                else:
                    logger.warning("Skipping corrupted game state for guild %s", gid)
            except Exception as e:
                logger.error("Failed to recover game %s: %s", gid, e)
    except Exception as e:
        logger.error(f"Game Load Error: {e}")
