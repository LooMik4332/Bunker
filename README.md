<<<<<<< HEAD
☢️ Bunker Discord BotA feature-rich Discord bot that hosts the Bunker social deduction game (similar to Mafia or Werewolf). Players must argue their case to survive an apocalypse and secure a spot in the limited bunker.✨ Key FeaturesClean Chat Architecture: unlike traditional bots that spam the chat, Bunker Bot uses a single updating Dashboard message and ephemeral responses (only visible to the user) to keep your channel clean.Immersive UI: All game messages are styled with color-coded embeds for a polished look.Multi-Language Support: Fully localized in English and Ukrainian. Easily switch languages per server.Persistence: Autosaves active games and user statistics to JSON files. If the bot restarts, games can be recovered (logic included in architecture).Game Mechanics:Randomized player attributes (Profession, Health, Phobia, Inventory, etc.).Dynamic voting system with "Double Elimination" mechanics on draws.Automatic win/loss condition checks.🎮 How to PlayLobby: Use /create [players] to open a lobby.Join: Players click the Join button.The Game:The bot generates a catastrophe scenario (Nuclear War, Zombie Virus, etc.) and bunker details.Players have hidden characteristic cards.Dashboard: Shows the status of all players and revealed info.Turns:Players use the Reveal button (ephemeral menu) to show specific cards to the group.Players argue why their traits make them valuable for survival.Voting:The Host starts a vote.Players vote to exile someone.The exiled player reveals all cards and leaves the game.Victory: The game ends when the number of survivors equals the number of bunker spots.🛠️ Installation & SetupPrerequisitesPython 3.8 or higher.A Discord Bot Token (with Message Content Intent enabled).1. Clone the repositorygit clone [https://github.com/yourusername/bunker-bot.git](https://github.com/yourusername/bunker-bot.git)
cd bunker-bot
2. Install dependenciespip install discord.py
3. ConfigurationThe bot will automatically create a config.json file on the first run, or you can create it manually:config.json{
    "token": "YOUR_DISCORD_BOT_TOKEN_HERE"
}
Alternatively, you can set the DISCORD_BOT_TOKEN environment variable.4. Run the botpython discord_bot.py
🤖 CommandsAll interactions are handled via Discord Slash Commands:CommandDescription/create [players]Start a new game lobby (requires player count)./languageChange the language of the bot for the current server./stopForce stop the current game (Host or Admin only)./profileView your global stats (Wins, Games played).📂 Project StructureThe project follows a Clean Architecture approach:discord_bot.py: Main entry point. Handles Discord API events, UI Views, and commands.game_logic.py: Pure Python core logic. Handles game state, player generation, and rules (no Discord dependencies).translation_manager.py: Handles localization loading and string formatting.translations.json: Contains all text strings for supported languages.users.json / active_games.json: Database files (created automatically).🤝 ContributingContributions are welcome! Please feel free to submit a Pull Request.Fork the project.Create your Feature Branch (git checkout -b feature/AmazingFeature).Commit your changes (git commit -m 'Add some AmazingFeature').Push to the Branch (git push origin feature/AmazingFeature).Open a Pull Request.📝 LicenseThis project is licensed under the MIT License.
=======
# ☢️ Bunker Discord Bot

Bunker is a feature-rich, fully interactive Discord bot that facilitates the popular social deduction board game "The Bunker" (also known as Lifeboat).

Players are generated with random characteristics (Job, Health, Phobia, Inventory, etc.). The catch? The bunker has limited spots. Convince others that you are useful, reveal your traits strategically, and vote to decide who gets left behind.

## ✨ Key Features

### 🎮 Clean Chat Architecture: 
Unlike traditional bots that spam the chat, Bunker Bot uses a single updating Dashboard message and ephemeral responses (visible only to the user) to keep your channel clean.

### 🌍 Multi-Language Support: 
Fully localized (currently supports English and Ukrainian). Easy to switch languages per server via /language.

### 💾 Persistence & Recovery: 
Auto-saves active games and user stats to JSON. If the bot restarts, the game state is recovered automatically.

### 🧠 Smart Game Logic:

Random Generation: Unique professions, health conditions, and phobias every round.

Voting System: Includes logic for "Double Elimination" in case of a draw.

Win Conditions: Automatically detects when the survivor count matches the bunker spots.

## 🛠 Installation

Prerequisites

Python 3.8 or higher

A Discord Bot Token (from Discord Developer Portal with Message Content Intent enabled)

Setup Steps

Clone the repository:
```
git clone https://github.com/theloomik/bunker.git
cd bunker
```

Install dependencies:
```
pip install discord.py
```

Configure the bot:
Run the bot once to generate config.json, or create it manually in the root folder:
```
{
    "token": "YOUR_DISCORD_BOT_TOKEN_HERE"
}
```

Run the bot:
```
python discord_bot.py
```

## 🚀 How to Play

**1. Lobby**

Use /create [players] to open a lobby.
Users click Join.
The Host clicks Start Game once the lobby is full.

**2. The Game (Dashboard)**

A persistent Dashboard message appears. It is the main hub of the game.

📂 My Profile: Check your secret stats (Ephemeral - only you see this).

📢 Reveal: Select specific cards to reveal to everyone (Updates the dashboard).

🔴 Start Vote: The Host initiates the voting phase.

**3. Voting**

The Host starts the vote.

The Dashboard is temporarily replaced by a Voting Menu.

Players select who to exile via a Dropdown menu.

Result: The bot displays who was kicked (and their full stats).

The Dashboard reappears at the bottom of the chat for the next round.

**4. Ending**

When the number of survivors matches the bunker spots, the game ends.
The bot announces the survivors and updates the global win stats.

## 🤖 Commands

All interactions are handled via Discord Slash Commands:

**/create [players]**
Start a new game lobby (requires player count).

**/language**
Change the language of the bot for the current server.

**/stop**
Force stop the current game (Host or Admin only).

**/profile**
View your global stats (Wins, Games played).

## 📂 Project Structure

The project follows a Clean Architecture approach:

**discord_bot.py** - The main entry point. Handles Discord API events, UI Views, and commands.

**game_logic.py** - Pure Python core logic. Handles game state, player generation, and rules (no Discord dependencies).

**translation_manager.py** - Handles localization loading and string formatting.

**translations.json** - Contains all text strings for supported languages.

**users.json / active_games.json** - Auto-generated database files.

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the issues page.

>>>>>>> 8632f0035372dfa609e109256da944653f5a0a9b
