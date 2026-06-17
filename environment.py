"""Environment – Phase 5: season, weather, temperature, wind.

Calendar
--------
Year is omitted; dates cycle MM/DD from 01/01 to 12/31 (non-leap).
Game starts on 03/01 (day_of_year = 60).

Season phases (10 stages)
--------------------------
01/01–02/28 : Winter     (厳冬)
03/01–03/31 : EarlySpring (早春)
04/01–04/30 : Spring      (春)
05/01–05/31 : Spawn       (産卵期)
06/01–06/15 : PostSpawn   (アフター)
06/16–07/31 : RainySeason (梅雨)
08/01–08/31 : Midsummer   (盛夏)
09/01–09/30 : EarlyFall   (初秋)
10/01–10/31 : Fall        (秋)
11/01–11/30 : LateFall    (晩秋)
12/01–12/31 : Winter      (厳冬)

Fishing hours
-------------
04:00 – 21:00 per day.  When game clock reaches 21:00 the caller
(game.py) advances to next day 04:00 and calls env.advance_day().
"""

from __future__ import annotations

import math
import random
from typing import Optional, Tuple


class Environment:
    """All environmental state: date, season, weather, temperature, wind."""

    # Non-leap year days-in-month (index 0 unused)
    _DAYS_IN_MONTH: list = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    # (start_doy, japanese_name, english_key, (lo_temp_C, hi_temp_C))
    _SEASONS: list = [
        (  1, "厳冬",    "Winter",      ( 2,  7)),
        ( 60, "早春",    "EarlySpring", ( 8, 14)),
        ( 91, "春",      "Spring",      (14, 20)),
        (121, "産卵期",  "Spawn",       (18, 24)),
        (152, "アフター","PostSpawn",   (22, 26)),
        (167, "梅雨",    "RainySeason", (22, 27)),
        (213, "盛夏",    "Midsummer",   (28, 34)),
        (244, "初秋",    "EarlyFall",   (24, 28)),
        (274, "秋",      "Fall",        (18, 22)),
        (305, "晩秋",    "LateFall",    (10, 16)),
        (335, "厳冬",    "Winter",      ( 2,  7)),
    ]

    # Weather probability tables: [sunny, cloudy, rain, heavy_rain]
    _WEATHER_PROBS: dict = {
        "Winter":      [0.30, 0.45, 0.20, 0.05],
        "EarlySpring": [0.35, 0.40, 0.20, 0.05],
        "Spring":      [0.45, 0.35, 0.15, 0.05],
        "Spawn":       [0.40, 0.35, 0.20, 0.05],
        "PostSpawn":   [0.35, 0.35, 0.20, 0.10],
        "RainySeason": [0.15, 0.25, 0.40, 0.20],
        "Midsummer":   [0.55, 0.25, 0.10, 0.10],
        "EarlyFall":   [0.40, 0.35, 0.20, 0.05],
        "Fall":        [0.40, 0.35, 0.20, 0.05],
        "LateFall":    [0.30, 0.40, 0.25, 0.05],
    }

    WEATHERS = ["Sunny", "Cloudy", "Rain", "Heavy Rain"]
    WIND_DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

    # Colour hints for UI callers
    WEATHER_COLOR = {
        "Sunny":      (240, 220,  60),
        "Cloudy":     (180, 180, 180),
        "Rain":       (100, 180, 255),
        "Heavy Rain": ( 60, 120, 220),
    }

    def __init__(self, rng_seed: int = 42) -> None:
        self._rng = random.Random(rng_seed)

        # Date
        self.day_of_year: int = 60          # 03/01

        # Weather state
        self.weather: str       = "Sunny"
        self._weather_timer: int = 0        # game-minutes remaining

        # Temperature (°C)
        self.air_temp:   float = 10.0
        self.water_temp: float = 10.0

        # Wind
        self.wind_dir:   str   = "N"
        self.wind_speed: float = 2.0        # m/s  0–10

        # Internal clock reference (to avoid re-processing same minute)
        self._last_game_minutes: int = -1

        # Initial weather roll
        self._roll_weather()
        self._roll_wind()

    # ── Public lifecycle ───────────────────────────────────────────────

    def update(self, game_minutes: int) -> None:
        """Call once per game-minute tick.  Updates temperatures and weather."""
        if game_minutes == self._last_game_minutes:
            return
        self._last_game_minutes = game_minutes

        # Air temp: base from season + time-of-day sinusoidal curve
        lo, hi = self._temp_range()
        hour = (game_minutes % 1440) // 60
        # Peaks ~14:00, lowest ~05:00
        if 5 <= hour <= 21:
            t = math.sin(math.pi * (hour - 5) / 16.0)
        else:
            t = -0.3
        t = max(-0.5, min(1.0, t))
        mid = (lo + hi) / 2.0
        half = (hi - lo) / 2.0
        self.air_temp = round(mid + t * half, 1)

        # Water temp lags air temp
        self.water_temp = round(
            self.water_temp + (self.air_temp - self.water_temp) * 0.05, 1
        )

        # Weather timer countdown → re-roll
        if self._weather_timer > 0:
            self._weather_timer -= 1
        else:
            self._roll_weather()

    def advance_day(self) -> None:
        """Called when the in-game day advances (21:00 → 04:00 next day)."""
        self.day_of_year = (self.day_of_year % 365) + 1
        self._roll_wind()
        # Small chance of immediate weather change on new day
        if self._rng.random() < 0.4:
            self._roll_weather()

    # ── Save / load ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "day_of_year":    self.day_of_year,
            "air_temp":       self.air_temp,
            "water_temp":     self.water_temp,
            "weather":        self.weather,
            "weather_timer":  self._weather_timer,
            "wind_dir":       self.wind_dir,
            "wind_speed":     self.wind_speed,
        }

    def from_dict(self, data: dict) -> None:
        self.day_of_year   = int(data.get("day_of_year",   60))
        self.air_temp      = float(data.get("air_temp",    10.0))
        self.water_temp    = float(data.get("water_temp",  10.0))
        self.weather       = data.get("weather",           "Sunny")
        self._weather_timer= int(data.get("weather_timer", 0))
        self.wind_dir      = data.get("wind_dir",          "N")
        self.wind_speed    = float(data.get("wind_speed",  2.0))
        self._last_game_minutes = -1

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def season_phase(self) -> str:
        """Japanese season name."""
        name = self._SEASONS[0][1]
        for start, jp, _, _ in self._SEASONS:
            if self.day_of_year >= start:
                name = jp
        return name

    @property
    def season_en(self) -> str:
        """English season key."""
        key = self._SEASONS[0][2]
        for start, _, en, _ in self._SEASONS:
            if self.day_of_year >= start:
                key = en
        return key

    @property
    def month_day_str(self) -> str:
        """'MM/DD' string for current day_of_year."""
        remaining = self.day_of_year
        for m in range(1, 13):
            md = self._DAYS_IN_MONTH[m]
            if remaining <= md:
                return f"{m:02d}/{remaining:02d}"
            remaining -= md
        return "12/31"

    @property
    def activity_modifier(self) -> float:
        """Fish activity multiplier.  1.0 = normal.  Clamped [0.2, 1.5]."""
        wt = self.water_temp

        # Temperature component
        if wt < 10:
            temp_mod = 0.30 + (wt / 10.0) * 0.20           # 0.30–0.50
        elif wt < 15:
            temp_mod = 0.50 + ((wt - 10) / 5.0) * 0.50     # 0.50–1.00
        elif wt <= 25:
            temp_mod = 1.00
        elif wt <= 30:
            temp_mod = 1.00 - ((wt - 25) / 5.0) * 0.30     # 1.00–0.70
        else:
            temp_mod = max(0.30, 0.70 - ((wt - 30) / 5.0) * 0.20)

        # Weather component
        weather_bonus = {
            "Sunny":      0.00,
            "Cloudy":     0.10,
            "Rain":       0.15,
            "Heavy Rain": -0.10,
        }.get(self.weather, 0.0)

        # Wind component
        wind_penalty = -0.10 if self.wind_speed > 7.0 else 0.0

        return round(max(0.20, min(1.50, temp_mod + weather_bonus + wind_penalty)), 2)

    @property
    def wind_display(self) -> str:
        return f"{self.wind_dir} {self.wind_speed:.1f}m/s"

    @property
    def weather_color(self) -> tuple:
        return self.WEATHER_COLOR.get(self.weather, (200, 200, 200))

    # ── Season label helpers ───────────────────────────────────────────

    _SEASON_DISPLAY: dict = {
        "Winter":      "Winter",
        "EarlySpring": "Early Spring",
        "Spring":      "Spring",
        "Spawn":       "Spawn",
        "PostSpawn":   "Post-Spawn",
        "RainySeason": "Rainy Season",
        "Midsummer":   "Midsummer",
        "EarlyFall":   "Early Fall",
        "Fall":        "Fall",
        "LateFall":    "Late Fall",
    }

    @property
    def season_label(self) -> str:
        """Human-readable English season label."""
        return self._SEASON_DISPLAY.get(self.season_en, self.season_en)

    # ── Private helpers ────────────────────────────────────────────────

    def _temp_range(self) -> Tuple[float, float]:
        lo, hi = 2.0, 7.0
        for start, _, _, tr in self._SEASONS:
            if self.day_of_year >= start:
                lo, hi = tr
        return float(lo), float(hi)

    def _roll_weather(self) -> None:
        probs = self._WEATHER_PROBS.get(self.season_en, [0.25] * 4)
        roll  = self._rng.random()
        cum   = 0.0
        for i, p in enumerate(probs):
            cum += p
            if roll < cum:
                self.weather = self.WEATHERS[i]
                break
        self._weather_timer = self._rng.randint(20, 90)

    def _roll_wind(self) -> None:
        self.wind_dir   = self._rng.choice(self.WIND_DIRS)
        self.wind_speed = round(self._rng.uniform(0.0, 10.0), 1)
