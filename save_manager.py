"""SaveManager – JSON persistence for Bass RPG Phase 4.

Save file: saves/save_data.json
Auto-save: on every catch
Manual:    F5 save  /  F9 load

Stored data
-----------
money           : int
catch_log       : list[{length, point_name, lure, time}]
personal_best   : {length, point_name, lure, time} | null
discovered_spots: list[str]
player_tile     : [tx, ty]
game_minutes    : int (360 = Day 1  06:00)
"""

from __future__ import annotations

import json
import os
from typing import Optional

SAVE_DIR  = "saves"
SAVE_FILE = os.path.join(SAVE_DIR, "save_data.json")

_GAME_START_MINUTES = 360   # 06:00 on Day 1


class SaveManager:
    """Handles loading, saving, and in-memory game state that persists."""

    def __init__(self) -> None:
        self.money: int = 0
        self.catch_log: list  = []
        self.personal_best: Optional[dict] = None
        self.discovered_spots: list = []
        self.player_tile: list = [25, 38]
        self.game_minutes: int = _GAME_START_MINUTES
        self.env_state: dict = {}
        self.population_state: dict = {}   # Phase 7: FishPopulationManager の状態
        self.npc_state: dict = {}          # Phase 11: NPCManager の状態

    # ── Persistence ─────────────────────────────────────────────────────

    def load(self) -> bool:
        """Load from disk.  Returns True on success, False if no file / error."""
        if not os.path.exists(SAVE_FILE):
            return False
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.money            = int(data.get("money", 0))
            self.catch_log        = list(data.get("catch_log", []))
            self.personal_best    = data.get("personal_best", None)
            self.discovered_spots = list(data.get("discovered_spots", []))
            self.player_tile      = list(data.get("player_tile", [25, 38]))
            self.game_minutes     = int(data.get("game_minutes", _GAME_START_MINUTES))
            self.env_state        = dict(data.get("env_state", {}))
            self.population_state = dict(data.get("population_state", {}))
            self.npc_state        = dict(data.get("npc_state", {}))
            return True
        except Exception:
            return False

    def save(
        self,
        player_tile: Optional[list] = None,
        env_state: Optional[dict] = None,
        population_state: Optional[dict] = None,
        npc_state: Optional[dict] = None,
    ) -> bool:
        """Write current state to disk.  Returns True on success."""
        if player_tile is not None:
            self.player_tile = list(player_tile)
        if env_state is not None:
            self.env_state = dict(env_state)
        if population_state is not None:
            self.population_state = dict(population_state)
        if npc_state is not None:
            self.npc_state = dict(npc_state)
        os.makedirs(SAVE_DIR, exist_ok=True)
        payload = {
            "money":             self.money,
            "catch_log":         self.catch_log,
            "personal_best":     self.personal_best,
            "discovered_spots":  self.discovered_spots,
            "player_tile":       self.player_tile,
            "game_minutes":      self.game_minutes,
            "env_state":         self.env_state,
            "population_state":  self.population_state,
            "npc_state":         self.npc_state,
        }
        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    # ── Game events ─────────────────────────────────────────────────────

    def record_catch(
        self,
        length: float,
        point_name: str,
        lure: str = "Minnow",
        fish_id: str = "",
        action: str = "KEEP",
    ) -> bool:
        """Append catch entry; update personal_best only for KEEP.
        Returns True if this is a new personal best (KEEP only).
        """
        entry: dict = {
            "length":     round(length, 1),
            "point_name": point_name,
            "lure":       lure,
            "time":       self.time_display,
            "action":     action,
        }
        if fish_id:
            entry["fish_id"] = fish_id
        self.catch_log.append(entry)
        if action != "KEEP":
            return False
        is_pb = self.personal_best is None or length > self.personal_best["length"]
        if is_pb:
            self.personal_best = dict(entry)
        return is_pb

    def discover_spot(self, name: str) -> bool:
        """Mark a spot as discovered.  Returns True if newly discovered."""
        if name not in self.discovered_spots:
            self.discovered_spots.append(name)
            return True
        return False

    # ── Clock ────────────────────────────────────────────────────────────

    def advance_minutes(self, minutes: int) -> None:
        """Advance in-game clock by the given number of minutes."""
        self.game_minutes += minutes

    @property
    def game_day(self) -> int:
        """現在のゲーム日数 (1始まり)。"""
        return self.game_minutes // 1440 + 1

    @property
    def time_display(self) -> str:
        """Human-readable in-game time: 'Day X  HH:MM'."""
        total = self.game_minutes
        day   = total // 1440 + 1
        h     = (total % 1440) // 60
        m     = total % 60
        return f"Day {day}  {h:02d}:{m:02d}"

    @property
    def total_catches(self) -> int:
        return len(self.catch_log)

    @property
    def personal_best_str(self) -> str:
        if self.personal_best is None:
            return "—"
        pb = self.personal_best
        return f"{pb['length']:.1f} cm  ({pb['point_name']})"
