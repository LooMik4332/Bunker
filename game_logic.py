import random
import math
from enum import Enum, auto
from typing import List, Dict, Optional, Tuple, Any

class GamePhase(Enum):
    WAITING = 1
    REVEAL = 2
    VOTING = 3
    FINISHED = 4

class Player:
    def __init__(self, user_id: int, name: str, lang: str):
        self.user_id = user_id
        self.name = name
        self.lang = lang
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
            "opened": self.opened
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Player':
        p = cls(data["user_id"], data["name"], data["lang"])
        p.alive = data["alive"]
        p.cards = data["cards"]
        p.opened = data["opened"]
        return p

    def generate_attributes(self, data_source: Dict[str, Any]) -> None:
        """
        Generates player attributes based on the provided raw data source.
        Expects keys: sexes, bodies, jobs, hobbies, inventory, extra, health, phobias.
        """
        # Helper to safely get list or default
        def get_list(key):
            return data_source.get(key, ["Unknown"])
        
        # Helper to get dict keys
        def get_keys(key):
            d = data_source.get(key, {"None": {}})
            return list(d.keys())

        sex = random.choice(get_list("sexes"))
        # Simple Logic: Assuming first item in sex list is male for stats (can be improved)
        
        self.cards = {
            "sex": sex,
            "age": str(random.randint(18, 90)),
            "height": str(random.randint(150, 210)) + " cm",
            "body": random.choice(get_list("bodies")),
            "job": random.choice(get_list("jobs")),
            "health": random.choice(get_keys("health")),
            "hobby": random.choice(get_list("hobbies")),
            "phobia": random.choice(get_keys("phobia")),
            "inventory": random.choice(get_list("inventory")),
            "extra": random.choice(get_list("extra")),
        }
        self.opened = {k: False for k in self.cards}

class BunkerGame:
    def __init__(self, guild_id: int, host_id: int, max_players: int, lang: str):
        self.guild_id = guild_id
        self.host_id = host_id
        self.max_players = max_players
        self.lang = lang
        self.players: List[Player] = []
        self.phase = GamePhase.WAITING
        self.bunker_spots = 0
        self.lore_text = ""
        self.votes: Dict[int, List[int]] = {}  # voter_id -> [target_ids]
        self.double_elim_next = False
        
        # Infrastructure Metadata (stored here for persistence, but opaque to logic)
        self.board_msg_id: Optional[int] = None
        self.channel_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "host_id": self.host_id,
            "max_players": self.max_players,
            "lang": self.lang,
            "phase": self.phase.value,
            "bunker_spots": self.bunker_spots,
            "lore_text": self.lore_text,
            "votes": self.votes,
            "double_elim_next": self.double_elim_next,
            "board_msg_id": self.board_msg_id,
            "channel_id": self.channel_id,
            "players": [p.to_dict() for p in self.players]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BunkerGame':
        g = cls(data["guild_id"], data["host_id"], data["max_players"], data["lang"])
        g.phase = GamePhase(data["phase"])
        g.bunker_spots = data["bunker_spots"]
        g.lore_text = data["lore_text"]
        g.votes = {int(k): v for k, v in data["votes"].items()}
        g.double_elim_next = data["double_elim_next"]
        g.board_msg_id = data.get("board_msg_id")
        g.channel_id = data.get("channel_id")
        g.players = [Player.from_dict(p) for p in data["players"]]
        return g

    def add_player(self, user_id: int, name: str) -> bool:
        if len(self.players) >= self.max_players:
            return False
        if any(p.user_id == user_id for p in self.players):
            return False
        
        # Basic name sanitization
        safe_name = name[:20]
        self.players.append(Player(user_id, safe_name, self.lang))
        return True

    def get_player(self, user_id: int) -> Optional[Player]:
        return next((p for p in self.players if p.user_id == user_id), None)

    def get_alive_players(self) -> List[Player]:
        return [p for p in self.players if p.alive]

    def start(self, data_source: Dict[str, Any]) -> None:
        count = len(self.players)
        self.bunker_spots = max(1, math.ceil(count / 2))
        self.phase = GamePhase.REVEAL
        
        # Generate Lore
        catastrophes = data_source.get("catastrophes", ["Disaster"])
        locs = data_source.get("bunker_types", ["Bunker"])
        conds = data_source.get("supplies", ["Supplies"])
        times = data_source.get("durations", ["Time"])
        
        self.lore_text = (
            f"{random.choice(catastrophes)}\n\n"
            f"**Loc**: {random.choice(locs)}\n"
            f"**Cond**: {random.choice(conds)}\n"
            f"⏳ {random.choice(times)}"
        )

        # Generate Players
        for p in self.players:
            p.generate_attributes(data_source)

    def register_vote(self, voter_id: int, targets: List[int]) -> None:
        voter = self.get_player(voter_id)
        if not voter or not voter.alive:
            raise ValueError("Player not allowed to vote")
        
        for t_id in targets:
            if t_id == voter_id:
                raise ValueError("Self voting prohibited")
            target = self.get_player(t_id)
            if not target or not target.alive:
                raise ValueError(f"Target {t_id} is dead")
        
        self.votes[voter_id] = targets

    def resolve_votes(self) -> Tuple[List[Player], bool]:
        """
        Returns: (List[Eliminated_Players], Is_Draw_Result)
        """
        alive_ids = {p.user_id for p in self.get_alive_players()}
        active_votes = {k: v for k, v in self.votes.items() if k in alive_ids}
        
        tally = {uid: 0 for uid in alive_ids}
        for targets in active_votes.values():
            for t in targets:
                if t in tally:
                    tally[t] += 1

        if not tally:
            return [], False

        results = sorted(tally.items(), key=lambda x: x[1], reverse=True)
        max_votes = results[0][1]
        candidates = [uid for uid, c in results if c == max_votes]
        
        eliminated = []
        is_draw = False

        if self.double_elim_next:
            self.double_elim_next = False
            # Pick up to 2
            to_kick_ids = list(candidates)
            if len(to_kick_ids) < 2 and len(results) > len(to_kick_ids):
                # Add second highest
                second_max = results[len(to_kick_ids)][1]
                to_kick_ids.extend([uid for uid, c in results if c == second_max])
            
            # Randomize tie breaks if more than 2 total
            random.shuffle(to_kick_ids)
            for uid in to_kick_ids[:2]:
                p = self.get_player(uid)
                if p: eliminated.append(p)
        else:
            if len(candidates) > 1:
                self.double_elim_next = True
                self.phase = GamePhase.REVEAL
                self.votes.clear()
                is_draw = True
            else:
                p = self.get_player(candidates[0])
                if p: eliminated.append(p)

        # Apply Death
        if not is_draw:
            for p in eliminated:
                p.alive = False

        return eliminated, is_draw

    def check_end_condition(self) -> bool:
        alive_count = len(self.get_alive_players())
        return alive_count <= self.bunker_spots