import asyncio
import random
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from .core import (
    ANNOUNCEMENT_LIFETIME,
    BOT_TOKEN,
    BRIEF_MSG_LIFETIME,
    EPHEMERAL_VIEW_TIMEOUT,
    EmbedColors,
    LANGUAGES,
    RESULT_MSG_LIFETIME,
    VOTE_TIMEOUT,
    GamePhase,
    GameState,
    Player,
    T,
    delete_active_game,
    games,
    get_server_lang,
    get_server_stats,
    get_user_data,
    load_active_games_from_disk,
    load_languages,
    load_user_db,
    logger,
    reset_user_stats,
    save_active_games,
    save_user_db_data,
    set_custom_name,
    set_server_lang,
    update_user_stats,
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def get_game_safe(interaction: discord.Interaction):
    if not interaction.guild:
        return None
    return games.get(interaction.guild.id)


def check_bot_perms(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return True
    if not interaction.channel:
        return True
    perms = interaction.channel.permissions_for(interaction.guild.me)
    return perms.send_messages and perms.embed_links and perms.read_message_history


async def auto_del(interaction, delay=3):
    await asyncio.sleep(delay)
    try:
        await interaction.delete_original_response()
    except Exception:
        pass


async def safe_response(
    interaction, content=None, embed=None, view=None, ephemeral=True, delete_after=None
):
    try:
        if interaction.response.is_done():
            msg = await interaction.followup.send(
                content=content,
                embed=embed,
                view=view,
                ephemeral=ephemeral,
                wait=True,
            )
            if delete_after:
                await asyncio.sleep(delete_after)
                try:
                    await msg.delete()
                except Exception:
                    pass
        else:
            await interaction.response.send_message(
                content=content,
                embed=embed,
                view=view,
                ephemeral=ephemeral,
                delete_after=delete_after,
            )
    except Exception as e:
        if "Unknown interaction" not in str(e) and "404 Not Found" not in str(e):
            logger.error(f"UI Error in safe_response: {e}")


# --- HELPERS ---
def tech_embed(text: str, type="success") -> discord.Embed:
    color = EmbedColors.SUCCESS if type == "success" else EmbedColors.ERROR
    if type == "info":
        color = EmbedColors.INFO
    return discord.Embed(description=text, color=color)


class CloseBtn(discord.ui.Button):
    def __init__(self, lang):
        super().__init__(
            label=T("ui.close_btn", lang),
            style=discord.ButtonStyle.danger,
            custom_id="bunker:close:generic",
        )

    async def callback(self, interaction):
        await interaction.response.edit_message(
            content=None,
            embed=tech_embed(
                T("msg.closed", self.view.lang if hasattr(self.view, "lang") else "uk"),
                "info",
            ),
            view=None,
        )
        asyncio.create_task(auto_del(interaction))


class CloseView(discord.ui.View):
    def __init__(self, lang="uk"):
        super().__init__(timeout=EPHEMERAL_VIEW_TIMEOUT)
        self.lang = lang
        self.add_item(CloseBtn(lang))


class LangSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(
            placeholder="Select Language",
            options=options,
            custom_id="bunker:lang_select",
        )

    async def callback(self, interaction):
        if not interaction.guild:
            await safe_response(
                interaction,
                embed=tech_embed("Servers only.", "error"),
                ephemeral=True,
            )
            return
        await set_server_lang(interaction.guild.id, self.values[0])
        await safe_response(
            interaction,
            embed=tech_embed(T("msg.lang_changed", self.values[0]), "success"),
            ephemeral=True,
        )


class NameModal(discord.ui.Modal):
    def __init__(self, lang):
        super().__init__(title=T("modal.title", lang), timeout=None)
        self.lang = lang
        self.name_input = discord.ui.TextInput(
            label=T("modal.label", lang),
            placeholder=T("modal.placeholder", lang),
            min_length=2,
            max_length=20,
            custom_id="bunker:name_input",
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction):
        raw_name = self.name_input.value.strip()
        safe_name = discord.utils.escape_mentions(raw_name)
        safe_name = discord.utils.escape_markdown(safe_name)

        if len(safe_name) < 2:
            await safe_response(
                interaction,
                embed=tech_embed("Name too short.", "error"),
                ephemeral=True,
            )
            return

        await set_custom_name(interaction.user.id, safe_name)

        game = get_game_safe(interaction)
        if game:
            p = game.get_player(interaction.user.id)
            if p:
                p.name = safe_name
                await game.update_board(interaction.client)
                asyncio.create_task(save_active_games())

        await safe_response(
            interaction,
            embed=tech_embed(T("msg.name_changed", self.lang, name=safe_name), "success"),
            ephemeral=True,
        )


class ProfileView(discord.ui.View):
    def __init__(self, lang, is_owner):
        super().__init__(timeout=EPHEMERAL_VIEW_TIMEOUT)
        self.lang = lang
        self.add_item(CloseBtn(lang))
        if is_owner:
            b = discord.ui.Button(
                label=T("ui.change_name_btn", lang),
                style=discord.ButtonStyle.secondary,
                emoji="✏️",
                custom_id="bunker:profile_edit",
            )
            b.callback = self.change_name
            self.add_item(b)

    async def change_name(self, interaction):
        await interaction.response.send_modal(NameModal(self.lang))


class CardSelect(discord.ui.Select):
    def __init__(self, player):
        self.player = player
        lang = player.lang
        titles = T("card_titles", lang)
        opts = []
        opts.append(
            discord.SelectOption(
                label=T("ui.reveal_all_opt", lang),
                value="all",
                description=T("ui.reveal_all_desc", lang),
            )
        )

        for k, v in titles.items():
            emoji = "✅" if player.opened.get(k) else "🔒"
            desc = player.cards[k] if player.opened.get(k) else "???"
            opts.append(
                discord.SelectOption(label=v, value=k, description=desc, emoji=emoji)
            )
        super().__init__(
            placeholder=T("ui.reveal_placeholder", lang),
            min_values=1,
            max_values=len(opts),
            options=opts,
            custom_id=f"bunker:card_sel:{player.user_id}",
        )

    async def callback(self, interaction):
        game = get_game_safe(interaction)
        if not game or not self.player.alive:
            return
        if game.phase == GamePhase.FINISHED:
            await safe_response(
                interaction,
                embed=tech_embed("Game Over", "error"),
                ephemeral=True,
            )
            return

        lang = self.player.lang

        vals = self.values
        if "all" in vals:
            for k in self.player.cards:
                self.player.opened[k] = True
            await interaction.channel.send(
                embed=discord.Embed(
                    title=T("msg.reveal_all_public_title", lang, name=self.player.name),
                    description=T("msg.reveal_all_public_desc", lang),
                    color=EmbedColors.VOTING,
                ),
                delete_after=ANNOUNCEMENT_LIFETIME,
            )
        else:
            titles = T("card_titles", lang)
            rev = []
            for v in vals:
                if not self.player.opened.get(v):
                    self.player.opened[v] = True
                    rev.append(f"**{titles.get(v, v)}**: `{self.player.cards[v]}`")

            if rev:
                await interaction.channel.send(
                    embed=discord.Embed(
                        title=T("msg.reveal_public_title", lang, name=self.player.name),
                        description="\n".join(rev),
                        color=EmbedColors.SUCCESS,
                    ),
                    delete_after=ANNOUNCEMENT_LIFETIME,
                )
                await safe_response(
                    interaction,
                    embed=tech_embed(T("msg.reveal_success", lang), "success"),
                    ephemeral=True,
                    delete_after=BRIEF_MSG_LIFETIME,
                )
            else:
                await safe_response(
                    interaction,
                    embed=tech_embed(T("msg.reveal_nothing", lang), "info"),
                    ephemeral=True,
                    delete_after=BRIEF_MSG_LIFETIME,
                )

        asyncio.create_task(save_active_games())

        await asyncio.sleep(BRIEF_MSG_LIFETIME)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass

        await game.update_board(interaction.client)


class RevealView(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=EPHEMERAL_VIEW_TIMEOUT)
        self.player = player
        self.lang = player.lang

        # Add the dropdown
        self.add_item(CardSelect(player))

        # Add the explicit Reveal All button
        all_btn = discord.ui.Button(
            label=T("ui.reveal_all_opt", self.lang),
            style=discord.ButtonStyle.danger,
            emoji="⚠️",
            custom_id=f"bunker:reveal_all:{player.user_id}",
        )
        all_btn.callback = self.reveal_all_callback
        self.add_item(all_btn)

    async def reveal_all_callback(self, interaction: discord.Interaction):
        game = get_game_safe(interaction)
        if not game or not self.player.alive:
            return
        if game.phase == GamePhase.FINISHED:
            await safe_response(
                interaction,
                embed=tech_embed("Game Over", "error"),
                ephemeral=True,
            )
            return

        for k in self.player.cards:
            self.player.opened[k] = True

        await interaction.channel.send(
            embed=discord.Embed(
                title=T("msg.reveal_all_public_title", self.lang, name=self.player.name),
                description=T("msg.reveal_all_public_desc", self.lang),
                color=EmbedColors.VOTING,
            ),
            delete_after=ANNOUNCEMENT_LIFETIME,
        )

        await interaction.response.edit_message(
            content=None,
            embed=tech_embed(T("msg.reveal_success", self.lang), "success"),
            view=None,
        )

        asyncio.create_task(save_active_games())
        await asyncio.sleep(BRIEF_MSG_LIFETIME)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass

        await game.update_board(interaction.client)


class RevealBtn(discord.ui.Button):
    def __init__(self, player):
        super().__init__(
            label=T("ui.reveal_btn", player.lang),
            style=discord.ButtonStyle.primary,
            custom_id=f"bunker:reveal:{player.user_id}",
        )
        self.player = player

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.player.user_id:
            await safe_response(
                interaction,
                embed=tech_embed("❌ Not your profile.", "error"),
                ephemeral=True,
            )
            return
        if not self.player.alive:
            await safe_response(
                interaction,
                embed=tech_embed("❌ You are dead.", "error"),
                ephemeral=True,
            )
            return
        if not interaction.channel or not interaction.guild:
            return

        await safe_response(
            interaction,
            embed=discord.Embed(
                title=T("ui.reveal_title", self.player.lang),
                description=T("ui.reveal_desc", self.player.lang),
                color=EmbedColors.INFO,
            ),
            view=RevealView(self.player),
            ephemeral=True,
        )


class PlayerView(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=EPHEMERAL_VIEW_TIMEOUT)
        self.add_item(RevealBtn(player))
        self.add_item(CloseBtn(player.lang))


class KickBtn(discord.ui.Button):
    def __init__(self, target: Player, lang: str):
        super().__init__(
            label=target.name,
            style=discord.ButtonStyle.danger,
            custom_id=f"bunker:kick:{target.user_id}",
        )
        self.target = target
        self.lang = lang

    async def callback(self, interaction: discord.Interaction):
        game = get_game_safe(interaction)
        if not game or game.phase == GamePhase.FINISHED:
            return
        if interaction.user.id != game.host_id:
            await safe_response(
                interaction,
                embed=tech_embed(T("msg.only_host", self.lang), "error"),
                ephemeral=True,
            )
            return

        if self.target and self.target.alive:
            self.target.alive = False
            await game.update_board(interaction.client)
            await safe_response(
                interaction,
                embed=tech_embed(
                    T("msg.player_kicked", self.lang, name=self.target.name),
                    "success",
                ),
                ephemeral=True,
            )
            asyncio.create_task(save_active_games())


class KickView(discord.ui.View):
    def __init__(self, players: List[Player], lang: str):
        super().__init__(timeout=EPHEMERAL_VIEW_TIMEOUT)
        for p in players:
            if p.alive:
                self.add_item(KickBtn(p, lang))
        self.add_item(CloseBtn(lang))


class VoteBtn(discord.ui.Button):
    def __init__(self, target: Player, lang: str):
        super().__init__(
            label=target.name,
            style=discord.ButtonStyle.danger,
            custom_id=f"bunker:vote:{target.user_id}",
        )
        self.target = target
        self.lang = lang

    async def callback(self, interaction: discord.Interaction):
        game = get_game_safe(interaction)
        if not game:
            return
        if game.phase != GamePhase.VOTING:
            await safe_response(
                interaction,
                embed=tech_embed("Voting has ended.", "error"),
                ephemeral=True,
            )
            return

        voter = game.get_player(interaction.user.id)
        if not voter or not voter.alive:
            await safe_response(
                interaction,
                embed=tech_embed("You cannot vote.", "error"),
                ephemeral=True,
            )
            return

        try:
            await game.register_vote(interaction.user.id, [self.target.user_id])
            await safe_response(
                interaction,
                embed=tech_embed(T("msg.vote_cast", self.lang), "success"),
                ephemeral=True,
            )
        except Exception as e:
            await safe_response(
                interaction,
                embed=tech_embed(str(e), "error"),
                ephemeral=True,
            )


class VoteView(discord.ui.View):
    def __init__(self, players: List[Player], max_votes: int, lang: str, gid: int):
        super().__init__(timeout=VOTE_TIMEOUT)
        self.max_votes = max_votes
        self.lang = lang
        self.guild_id = gid
        for p in players:
            if p.alive:
                self.add_item(VoteBtn(p, lang))

    async def on_timeout(self):
        game = games.get(self.guild_id)
        if not game:
            return
        if game.phase != GamePhase.VOTING:
            return

        await finish_voting(game, self.lang)


class MultiVoteView(discord.ui.View):
    def __init__(self, players: List[Player], max_votes: int, lang: str, gid: int):
        super().__init__(timeout=VOTE_TIMEOUT)
        self.max_votes = max_votes
        self.lang = lang
        self.guild_id = gid
        for p in players:
            if p.alive:
                self.add_item(VoteBtn(p, lang))

    async def on_timeout(self):
        game = games.get(self.guild_id)
        if not game:
            return
        if game.phase != GamePhase.VOTING:
            return

        await finish_voting(game, self.lang)


class Dashboard(discord.ui.View):
    def __init__(self, lang: str, gid: int):
        super().__init__(timeout=EPHEMERAL_VIEW_TIMEOUT)
        self.lang = lang
        self.guild_id = gid

    @discord.ui.button(style=discord.ButtonStyle.primary)
    async def profile(self, interaction, button):
        game = get_game_safe(interaction)
        if not game:
            await safe_response(
                interaction,
                embed=tech_embed("Game not found.", "error"),
                ephemeral=True,
            )
            return

        p = game.get_player(interaction.user.id)
        if not p:
            await safe_response(
                interaction,
                embed=tech_embed("Not in game.", "error"),
                ephemeral=True,
            )
            return

        await safe_response(
            interaction,
            embed=discord.Embed(
                title=T("ui.profile_title", self.lang),
                description=p.get_profile_text(),
                color=EmbedColors.INFO,
            ),
            view=PlayerView(p),
            ephemeral=True,
        )

    @discord.ui.button(style=discord.ButtonStyle.secondary)
    async def kick(self, interaction, button):
        game = get_game_safe(interaction)
        if not game:
            return

        if interaction.user.id != game.host_id:
            await safe_response(
                interaction,
                embed=tech_embed(T("msg.only_host", self.lang), "error"),
                ephemeral=True,
            )
            return

        await safe_response(
            interaction,
            embed=tech_embed(T("msg.kick_select", self.lang), "info"),
            view=KickView(game.players, self.lang),
            ephemeral=True,
        )

    @discord.ui.button(style=discord.ButtonStyle.success)
    async def start_vote(self, interaction, button):
        game = get_game_safe(interaction)
        if not game:
            return
        if interaction.user.id != game.host_id:
            return

        await game.update_board(interaction.client)
        game.phase = GamePhase.VOTING
        game.votes.clear()

        await safe_response(
            interaction,
            embed=tech_embed(T("msg.vote_started", self.lang), "success"),
            ephemeral=True,
        )

        alive = game.alive_players()
        max_votes = 2 if game.double_elim_next else 1
        game.dashboard_view.stop()
        game.dashboard_view = None

        view = VoteView(alive, max_votes, self.lang, game.guild_id)
        bot.add_view(view)

        if max_votes > 1:
            view = MultiVoteView(alive, max_votes, self.lang, game.guild_id)
            await interaction.channel.send(view=view)
        else:
            await interaction.channel.send(view=view)

        asyncio.create_task(save_active_games())


class JoinView(discord.ui.View):
    def __init__(self, lang: str, gid: int):
        super().__init__(timeout=EPHEMERAL_VIEW_TIMEOUT)
        self.lang = lang
        self.guild_id = gid

    @discord.ui.button(style=discord.ButtonStyle.success)
    async def join(self, interaction, button):
        game = get_game_safe(interaction)
        if not game:
            await safe_response(
                interaction,
                embed=tech_embed("No game found.", "error"),
                ephemeral=True,
            )
            return

        if game.add_player(interaction.user.id, interaction.user.display_name):
            await safe_response(
                interaction,
                embed=tech_embed(T("msg.joined", self.lang), "success"),
                ephemeral=True,
                delete_after=BRIEF_MSG_LIFETIME,
            )
            if len(game.players) >= game.max_players:
                self.children[1].disabled = False
                self.children[1].style = discord.ButtonStyle.success

            emb = discord.Embed(
                title=T("ui.lobby_title", self.lang),
                description=(
                    f"{T('ui.host_label', self.lang)} <@{game.host_id}>\n"
                    f"{T('ui.players_label', self.lang)} {len(game.players)}/{game.max_players}"
                ),
                color=EmbedColors.LOBBY,
            )
            await interaction.message.edit(embed=emb, view=self)
        else:
            await safe_response(
                interaction,
                embed=tech_embed(T("msg.no_seats", self.lang), "error"),
                ephemeral=True,
            )

    @discord.ui.button(style=discord.ButtonStyle.danger, disabled=True)
    async def start(self, interaction, button):
        game = get_game_safe(interaction)
        if not game:
            return
        if interaction.user.id != game.host_id:
            return

        await game.start_game()
        # Delete lobby message to clean up
        await interaction.message.delete()

        await interaction.channel.send(
            embed=discord.Embed(
                title="☢️ INTRO", description=game.lore_text, color=EmbedColors.INTRO
            )
        )

        game.board_message = await interaction.channel.send(embed=game.generate_board_embed())
        game.board_msg_id = game.board_message.id
        game.channel_id = interaction.channel.id
        game.channel = interaction.channel

        game.dashboard_view = Dashboard(self.lang, game.guild_id)
        msg = await interaction.channel.send(view=game.dashboard_view)
        game.dash_msg_id = msg.id

        asyncio.create_task(save_active_games())

    @discord.ui.button(style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        game = get_game_safe(interaction)
        if not game:
            return
        if interaction.user.id != game.host_id:
            await safe_response(
                interaction,
                embed=tech_embed(T("msg.only_host", self.lang), "error"),
                ephemeral=True,
            )
            return

        # NEW CONFIRMATION LOGIC
        confirm_view = discord.ui.View(timeout=60)
        confirm_btn = discord.ui.Button(
            label="Yes, Cancel Game", style=discord.ButtonStyle.danger
        )

        async def confirm_callback(conf_interaction: discord.Interaction):
            await delete_active_game(interaction.guild.id)

            # Update ephemeral confirmation message
            await conf_interaction.response.edit_message(
                content=None,
                embed=tech_embed(T("msg.game_cancelled", self.lang), "error"),
                view=None,
            )

            # Update original lobby message to show cancelled status
            try:
                if interaction.message:
                    await interaction.message.edit(
                        content=None,
                        embed=tech_embed(T("msg.game_cancelled", self.lang), "error"),
                        view=None,
                    )
            except Exception:
                pass

        confirm_btn.callback = confirm_callback
        confirm_view.add_item(confirm_btn)

        await safe_response(
            interaction,
            content="⚠️ Are you sure you want to cancel? This action cannot be undone.",
            view=confirm_view,
            ephemeral=True,
        )


# --- GAME FLOW ---
async def finish_voting(game: GameState, lang: str):
    eliminated, text, is_draw = game.resolve_votes()

    if is_draw:
        await game.update_board(bot)
        await game.channel.send(
            embed=discord.Embed(
                title=T("ui.draw_title", lang),
                description=T("ui.draw_desc", lang),
                color=EmbedColors.VOTING,
            )
        )
        game.phase = GamePhase.REVEAL
        game.votes.clear()
        asyncio.create_task(save_active_games())
        return

    for p in eliminated:
        p.alive = False
        await update_user_stats(p.user_id, "deaths")

    alive = game.alive_players()

    result_text = text
    if eliminated:
        result_text += "\n\n" + "\n".join(f"- {p.name}" for p in eliminated)

    await game.channel.send(
        embed=discord.Embed(
            title=T("ui.vote_result_title", lang),
            description=result_text,
            color=EmbedColors.ELIMINATION,
        ),
        delete_after=RESULT_MSG_LIFETIME,
    )

    if len(alive) <= game.bunker_spots:
        await end_game_flow(game, alive, lang)
    else:
        game.phase = GamePhase.REVEAL
        game.votes.clear()
        await game.update_board(bot)
        await game.channel.send(
            embed=discord.Embed(
                title=T("ui.reveal_phase_title", lang),
                description=T("ui.reveal_phase_desc", lang),
                color=EmbedColors.GAME_INFO,
            )
        )

    asyncio.create_task(save_active_games())


async def end_game_flow(game: GameState, winners: List[Player], lang: str):
    ending = game.calculate_ending()

    for p in winners:
        await update_user_stats(p.user_id, "wins")

    await game.channel.send(
        embed=discord.Embed(
            title=T("ui.win_title", lang),
            description=ending,
            color=EmbedColors.VICTORY,
        )
    )

    await game.end_game(bot)


# --- BOT COMMANDS ---
@bot.event
async def on_ready():
    # 1. Load User DB
    await load_user_db()

    # 2. Load Languages (Async) - MUST BE BEFORE RECOVERING GAMES
    await load_languages()

    # 3. Recover Active Games
    await load_active_games_from_disk()

    recovered_count = 0
    # Re-register persistent views
    for gid, game in games.items():
        bot.add_view(JoinView(game.lang, gid))
        bot.add_view(Dashboard(game.lang, gid))

        # If game was in VOTING, we must also recover the VoteView to allow voting to continue
        if game.phase == GamePhase.VOTING:
            alive = game.alive_players()
            mx = 2 if game.double_elim_next else 1
            bot.add_view(VoteView(alive, mx, game.lang, gid))

        recovered_count += 1

    await bot.tree.sync()
    logger.info(
        "Bot logged in as %s. Recovered %s games.",
        bot.user,
        recovered_count,
    )


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.CommandOnCooldown):
        await safe_response(
            interaction,
            embed=tech_embed(f"Cooldown: {error.retry_after:.1f}s", "error"),
            ephemeral=True,
        )
    elif isinstance(error, app_commands.MissingPermissions):
        await safe_response(
            interaction,
            embed=tech_embed("❌ You do not have permission to use this command.", "error"),
            ephemeral=True,
        )
    else:
        logger.error(f"Command Error: {error}")
        try:
            await safe_response(
                interaction, embed=tech_embed("❌ Internal Error.", "error"), ephemeral=True
            )
        except Exception:
            pass


@bot.tree.command(name="language", description="Change language")
@app_commands.checks.cooldown(1, 30.0, key=lambda i: (i.guild_id))  # 1 use per 30s per guild
async def language(interaction: discord.Interaction):
    if not interaction.guild:
        return

    # Check if languages loaded correctly
    if not LANGUAGES:
        await load_languages()  # Try reloading if empty

    if not LANGUAGES:
        await safe_response(
            interaction,
            embed=tech_embed("❌ Error: Language file is empty or missing.", "error"),
            ephemeral=True,
        )
        return

    # Create options based on loaded languages
    options = [
        discord.SelectOption(label=data.get("name", code), value=code)
        for code, data in LANGUAGES.items()
    ]

    if not options:
        await safe_response(
            interaction,
            embed=tech_embed("❌ No languages available.", "error"),
            ephemeral=True,
        )
        return

    view = discord.ui.View()
    view.add_item(LangSelect(options))
    await safe_response(interaction, "Select Language:", view=view, ephemeral=True)


@bot.tree.command(name="create", description="Start new game")
@app_commands.describe(players="Number of players")
@app_commands.checks.cooldown(1, 60.0)  # 1 use per 60s per user
async def create(interaction: discord.Interaction, players: int):
    if not interaction.guild:
        await safe_response(
            interaction,
            embed=tech_embed("Servers only.", "error"),
            ephemeral=True,
        )
        return
    if not check_bot_perms(interaction):
        await safe_response(
            interaction,
            embed=tech_embed(
                "Missing permissions! I need 'Send Messages' and 'Embed Links'.",
                "error",
            ),
            ephemeral=True,
        )
        return
    if players < 2 or players > 25:
        await safe_response(
            interaction,
            embed=tech_embed("2-25 players.", "error"),
            ephemeral=True,
        )
        return
    if interaction.guild.id in games:
        await safe_response(
            interaction,
            embed=tech_embed("Game already in progress!", "error"),
            ephemeral=True,
        )
        return

    lang = get_server_lang(interaction.guild.id)
    new_game = GameState(players, interaction.user.id, lang, interaction.guild.id)

    # Auto-join the host immediately
    new_game.add_player(interaction.user.id, interaction.user.display_name)

    games[interaction.guild.id] = new_game

    # Save state immediately (non-blocking)
    asyncio.create_task(save_active_games())

    emb = discord.Embed(
        title=T("ui.lobby_title", lang),
        description=(
            f"{T('ui.host_label', lang)} {interaction.user.mention}\n"
            f"{T('ui.players_label', lang)} 1/{players}"
        ),
        color=EmbedColors.LOBBY,
    )

    # CRITICAL FIX: ephemeral=False ensures everyone can see the lobby and join
    await safe_response(
        interaction,
        embed=emb,
        view=JoinView(lang, interaction.guild.id),
        ephemeral=False,
    )


@bot.tree.command(name="profile", description="Stats")
@app_commands.checks.cooldown(1, 10.0)  # 1 use per 10s per user
async def profile(interaction: discord.Interaction, user: Optional[discord.User] = None):
    if not interaction.guild:
        await safe_response(
            interaction,
            embed=tech_embed("Use this command in a server.", "error"),
            ephemeral=True,
        )
        return

    target = user or interaction.user
    lang = get_server_lang(interaction.guild.id)
    d = get_user_data(target.id)

    nm = d["name"] if d["name"] else target.display_name

    base_title = T("profile.title", lang, name=nm)
    emb = discord.Embed(title=f"{base_title} (Global)", color=EmbedColors.INFO)

    emb.set_thumbnail(url=target.display_avatar.url)

    emb.add_field(name=T("profile.games", lang), value=str(d["games"]), inline=True)
    emb.add_field(name=T("profile.wins", lang), value=str(d["wins"]), inline=True)

    winrate = 0
    if d["games"] > 0:
        winrate = (d["wins"] / d["games"]) * 100
    emb.add_field(name=T("profile.winrate", lang), value=f"{winrate:.1f}%", inline=True)

    # Sex Stats Display
    sex_stats = d.get("sex_stats", {"m": 0, "f": 0})
    sex_text = f"♂️ {sex_stats.get('m', 0)} | ♀️ {sex_stats.get('f', 0)}"
    emb.add_field(name=T("profile.sex", lang), value=sex_text, inline=True)

    # Average Age Display
    avg_age = 0
    if d["games"] > 0 and "total_age" in d:
        avg_age = d["total_age"] / d["games"]
    emb.add_field(name=T("profile.age", lang), value=f"{avg_age:.1f}", inline=True)

    srv_games = get_server_stats(interaction.guild.id)
    emb.set_footer(text=T("profile.server_stats", lang, count=srv_games))

    is_owner = target.id == interaction.user.id
    await safe_response(
        interaction, embed=emb, view=ProfileView(lang, is_owner), ephemeral=True
    )


@bot.tree.command(name="dossier", description="In-game dossier")
@app_commands.checks.cooldown(1, 5.0)  # 1 use per 5s per user
async def dossier(interaction: discord.Interaction):
    game = games.get(interaction.guild.id)
    if not game:
        await safe_response(
            interaction,
            embed=tech_embed("No active game.", "error"),
            ephemeral=True,
        )
        return
    p = game.get_player(interaction.user.id)
    lang = get_server_lang(interaction.guild.id)
    if p:
        await safe_response(
            interaction,
            embed=discord.Embed(
                title="📂",
                description=p.get_profile_text(True),
                color=EmbedColors.INFO,
            ),
            ephemeral=True,
            view=CloseView(lang),
        )
    else:
        await safe_response(
            interaction, embed=tech_embed("Not in game", "error"), ephemeral=True
        )


# --- ADMIN COMMANDS ---


@bot.tree.command(name="admin_endgame", description="Force end the current game (Admin)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.cooldown(1, 5.0)
async def admin_endgame(interaction: discord.Interaction):
    if not interaction.guild:
        return
    game = games.get(interaction.guild.id)
    if game:
        await game.end_game(interaction.client)
        await safe_response(
            interaction,
            embed=tech_embed("✅ Game force-ended by admin.", "success"),
            ephemeral=True,
        )
    else:
        await safe_response(
            interaction,
            embed=tech_embed("❌ No active game in this server.", "error"),
            ephemeral=True,
        )


@bot.tree.command(name="admin_reset_stats", description="Reset user stats (Admin)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.cooldown(1, 5.0)
async def admin_reset_stats(interaction: discord.Interaction, user: discord.User):
    if not interaction.guild:
        return
    await reset_user_stats(user.id)
    await safe_response(
        interaction,
        embed=tech_embed(f"✅ Stats reset for {user.mention}.", "success"),
        ephemeral=True,
    )


def run():
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
    else:
        logger.critical("Error: Token not found in config.json or env vars.")
