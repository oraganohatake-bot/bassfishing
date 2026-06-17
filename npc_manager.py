"""NPC Information Network – Phase 11.

5種のNPCが湖を観察し、実在する魚・環境・釣果情報を元に会話する。

NPC種別とskill_level:
  Child      : 0.2  (大雑把・曖昧)
  Beginner   : 0.4  (おおよそのサイズ・方角)
  Local      : 0.7  (スポット名・大まかなサイズ)
  Veteran    : 0.9  (詳細な個体情報)
  ShopOwner  : 0.8  (客からの伝聞情報)

友好度(friendship)による情報アンロック:
  0–19  : 一般情報（天気・活性など）
  20–49 : 具体的スポット名
  50–79 : 大型魚情報
  80–100: 秘密ポイント・個体詳細
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict
from typing import List, Optional

# ── NPC種別定数 ──────────────────────────────────────────────────────────────

NPC_CHILD      = "Child"
NPC_BEGINNER   = "Beginner"
NPC_LOCAL      = "Local"
NPC_VETERAN    = "Veteran"
NPC_SHOPOWNER  = "ShopOwner"

_SKILL_LEVEL: dict = {
    NPC_CHILD:     0.2,
    NPC_BEGINNER:  0.4,
    NPC_LOCAL:     0.7,
    NPC_VETERAN:   0.9,
    NPC_SHOPOWNER: 0.8,
}

# マップ上の描画色
NPC_COLORS: dict = {
    NPC_CHILD:     (255, 180, 200),
    NPC_BEGINNER:  (160, 230, 160),
    NPC_LOCAL:     (160, 190, 255),
    NPC_VETERAN:   (255, 200,  50),
    NPC_SHOPOWNER: (255, 145,  50),
}

_TYPE_LABEL: dict = {
    NPC_CHILD:     "子ども",
    NPC_BEGINNER:  "初心者",
    NPC_LOCAL:     "地元民",
    NPC_VETERAN:   "ベテラン",
    NPC_SHOPOWNER: "店主",
}


# ── データクラス ──────────────────────────────────────────────────────────────

@dataclass
class ObservationEntry:
    """NPC日誌の1エントリ。"""
    game_day:  int
    fish_id:   str
    spot_name: str
    note:      str

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ObservationEntry":
        return ObservationEntry(
            game_day  = int(d["game_day"]),
            fish_id   = str(d["fish_id"]),
            spot_name = str(d["spot_name"]),
            note      = str(d["note"]),
        )


@dataclass
class NPCIndividual:
    """NPCの永続データ。"""
    npc_id:    str
    name:      str
    npc_type:  str
    tile_x:    int
    tile_y:    int
    home_spot: str
    skill_level:  float
    friendship:   int   = 0
    known_fish:   List[str] = field(default_factory=list)
    known_spots:  List[str] = field(default_factory=list)
    last_talked_day: int    = -1
    observation_log: List[ObservationEntry] = field(default_factory=list)
    conversation_history: List[dict] = field(default_factory=list)

    # ── クエリ ────────────────────────────────────────────────────────────

    def can_talk_today(self, game_day: int) -> bool:
        return self.last_talked_day != game_day

    def add_friendship(self, amount: int) -> None:
        self.friendship = min(100, self.friendship + amount)

    @property
    def info_tier(self) -> int:
        """友好度ティア (0-3)。"""
        if self.friendship >= 80:
            return 3
        if self.friendship >= 50:
            return 2
        if self.friendship >= 20:
            return 1
        return 0

    @property
    def color(self) -> tuple:
        return NPC_COLORS.get(self.npc_type, (200, 200, 200))

    @property
    def type_label(self) -> str:
        return _TYPE_LABEL.get(self.npc_type, self.npc_type)

    # ── シリアライズ ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "npc_id":    self.npc_id,
            "name":      self.name,
            "npc_type":  self.npc_type,
            "tile_x":    self.tile_x,
            "tile_y":    self.tile_y,
            "home_spot": self.home_spot,
            "skill_level":        self.skill_level,
            "friendship":         self.friendship,
            "known_fish":         list(self.known_fish),
            "known_spots":        list(self.known_spots),
            "last_talked_day":    self.last_talked_day,
            "observation_log":    [e.to_dict() for e in self.observation_log],
            "conversation_history": list(self.conversation_history),
        }

    @staticmethod
    def from_dict(d: dict) -> "NPCIndividual":
        obs = [ObservationEntry.from_dict(e) for e in d.get("observation_log", [])]
        return NPCIndividual(
            npc_id    = str(d["npc_id"]),
            name      = str(d["name"]),
            npc_type  = str(d["npc_type"]),
            tile_x    = int(d["tile_x"]),
            tile_y    = int(d["tile_y"]),
            home_spot = str(d["home_spot"]),
            skill_level  = float(d["skill_level"]),
            friendship   = int(d.get("friendship", 0)),
            known_fish   = list(d.get("known_fish", [])),
            known_spots  = list(d.get("known_spots", [])),
            last_talked_day = int(d.get("last_talked_day", -1)),
            observation_log = obs,
            conversation_history = list(d.get("conversation_history", [])),
        )


# ── NPCManager ───────────────────────────────────────────────────────────────

class NPCManager:
    """全NPC管理・観測・会話生成・噂システム。"""

    # (npc_id, name, npc_type, tile_x, tile_y, home_spot)
    _NPC_DEFS = [
        ("NPC001", "Kenta",  NPC_CHILD,     25, 37, "South Flat"),
        ("NPC002", "Hiro",   NPC_BEGINNER,  20, 34, "SW Brush"),
        ("NPC003", "Yuki",   NPC_LOCAL,     32, 34, "SE Cove"),
        ("NPC004", "Takeda", NPC_VETERAN,   12, 16, "NW Drop-off"),
        ("NPC005", "Mizuki", NPC_SHOPOWNER, 38, 34, "East Shore"),
    ]

    def __init__(self) -> None:
        self.npcs: List[NPCIndividual] = []
        self._rng = random.Random(42)
        self._setup_npcs()

    # ── 初期化 ────────────────────────────────────────────────────────────

    def _setup_npcs(self) -> None:
        for npc_id, name, npc_type, tx, ty, home in self._NPC_DEFS:
            self.npcs.append(NPCIndividual(
                npc_id      = npc_id,
                name        = name,
                npc_type    = npc_type,
                tile_x      = tx,
                tile_y      = ty,
                home_spot   = home,
                skill_level = _SKILL_LEVEL[npc_type],
            ))

    # ── クエリ ────────────────────────────────────────────────────────────

    def get_nearby_npc(self, tx: int, ty: int,
                       radius: int = 2) -> Optional[NPCIndividual]:
        for npc in self.npcs:
            if abs(npc.tile_x - tx) <= radius and abs(npc.tile_y - ty) <= radius:
                return npc
        return None

    # ── 日次観測 ──────────────────────────────────────────────────────────

    def daily_observe(self, population, environment, game_day: int) -> None:
        """毎日呼び出す。各NPCが home_spot の魚を観察して知識を更新する。"""
        for npc in self.npcs:
            self._npc_observe(npc, population, environment, game_day)

    def _npc_observe(self, npc: NPCIndividual, population, _env,
                     game_day: int) -> None:
        spot_fish = population.get_spot_individuals(npc.home_spot)
        for fi in spot_fish:
            if self._rng.random() < npc.skill_level * 0.80:
                if fi.fish_id not in npc.known_fish:
                    npc.known_fish.append(fi.fish_id)
                    npc.observation_log.append(ObservationEntry(
                        game_day  = game_day,
                        fish_id   = fi.fish_id,
                        spot_name = npc.home_spot,
                        note      = f"{fi.length:.1f}cm 目撃",
                    ))
                    # observation_logは最大50件
                    if len(npc.observation_log) > 50:
                        npc.observation_log = npc.observation_log[-50:]

        if npc.home_spot not in npc.known_spots:
            npc.known_spots.append(npc.home_spot)

    # ── 会話生成 ──────────────────────────────────────────────────────────

    def generate_dialogue(self, npc: NPCIndividual, population,
                          environment, catch_log: list,
                          game_day: int) -> List[str]:
        """優先度: 既談話チェック > legend > 大型(50cm+) > C&R魚 > 一般情報。"""

        if not npc.can_talk_today(game_day):
            return [
                "（今日はもう話したな。）",
                "また明日来てくれ。",
            ]

        # ── 1. legend候補 ────────────────────────────────────────────────
        for fish_id in npc.known_fish:
            fi = population.managed_fish.get(fish_id)
            if fi and fi.legend_candidate:
                return self._fish_dialogue(npc, fi)

        # ── 2. 大型魚 50cm以上 ──────────────────────────────────────────
        big_candidates = [
            population.managed_fish[fid]
            for fid in npc.known_fish
            if fid in population.managed_fish
            and population.managed_fish[fid].length >= 50.0
        ]
        if big_candidates:
            fi = max(big_candidates, key=lambda f: f.length)
            return self._fish_dialogue(npc, fi)

        # ── 3. リリースされた個体 ────────────────────────────────────────
        for fish_id in npc.known_fish:
            fi = population.managed_fish.get(fish_id)
            if fi and fi.release_count > 0:
                return self._release_dialogue(npc, fi)

        # ── 4. 一般情報（天気・活性） ─────────────────────────────────────
        return self._general_dialogue(npc, environment)

    # ── ダイアログ生成ヘルパー ─────────────────────────────────────────────

    def _distort_length(self, true_len: float, skill: float) -> float:
        """精度が低いほどサイズを誇張・丸める。"""
        noise = self._rng.uniform(-0.3, 0.6) * (1.0 - skill)
        raw = true_len + noise * true_len * 0.15
        # 精度が低いほど5cm単位で丸める
        if skill < 0.35:
            return round(raw / 5) * 5
        if skill < 0.65:
            return round(raw / 2) * 2
        return round(raw, 1)

    def _vague_spot(self, spot_name: str) -> str:
        """スポット名を方角の曖昧表現に変換する。"""
        s = spot_name.upper()
        if "NORTH" in s or "NW" in s or "NE" in s:
            return "北の方"
        if "SOUTH" in s or "SW" in s or "SE" in s:
            return "南の方"
        if "EAST" in s:
            return "東の方"
        if "WEST" in s:
            return "西の方"
        return "湖のどこか"

    def _fish_dialogue(self, npc: NPCIndividual, fi) -> List[str]:
        skill  = npc.skill_level
        spot   = fi.home_spot
        rlen   = self._distort_length(fi.length, skill)
        is_leg = fi.legend_candidate

        if npc.npc_type == NPC_CHILD:
            if is_leg:
                return [
                    "ねえねえ！すごく大きな魚がいたんだよ！",
                    "お父さんの腕より太かった！",
                    "でも…どこだったっけ。忘れちゃった。",
                ]
            return [
                "大きい魚がいたよー！",
                "めっちゃ速く泳いでた！",
                "また見たいなあ。",
            ]

        elif npc.npc_type == NPC_BEGINNER:
            vspot = self._vague_spot(spot)
            if is_leg:
                return [
                    f"{vspot}で信じられないサイズの魚を見た気がする。",
                    "60cmは余裕で超えてたと思うんだけど…",
                    "自信はないけどね。",
                ]
            return [
                f"{vspot}に{rlen:.0f}cmくらいの魚がいた気がする。",
                "まだ慣れてないからよくわからないんだけど。",
            ]

        elif npc.npc_type == NPC_LOCAL:
            if is_leg:
                return [
                    f"{spot}に最近変わった魚の噂がある。",
                    "地元の人も誰も釣れてないらしい。",
                    f"60cmは超えてるんじゃないかな。",
                ]
            return [
                f"{spot}に{rlen:.0f}cmクラスのバスがいるよ。",
                "最近よく目撃されてる。",
            ]

        elif npc.npc_type == NPC_VETERAN:
            act_label = "活性が高い" if fi.aggression > 0.6 else "警戒心が強い"
            caution_pct = int(fi.caution * 100)
            if is_leg:
                return [
                    f"{spot}の深場に大型がついている。",
                    f"サイズは{fi.length:.1f}cmはあると見てる。",
                    f"{act_label}。警戒度{caution_pct}%。ルアー選びが重要だ。",
                    f"[個体ID: {fi.fish_id}]",
                ]
            return [
                f"{spot}の沈み木周りに{fi.length:.1f}cmのバスが付いてる。",
                f"{act_label}な個体だ。",
            ]

        elif npc.npc_type == NPC_SHOPOWNER:
            if is_leg:
                return [
                    "お客さんから聞いたんだが…",
                    f"{spot}で誰も釣れない怪物みたいな魚の話が出てる。",
                    "伝説の魚って呼ばれてるらしいよ。",
                ]
            return [
                f"最近{spot}から来た客が言ってたが、",
                f"{rlen:.0f}cmクラスが出てるらしい。",
                "ルアーはなんでも試してみるといいよ。",
            ]

        return ["…"]

    def _release_dialogue(self, npc: NPCIndividual, fi) -> List[str]:
        spot  = fi.home_spot
        rlen  = self._distort_length(fi.length, npc.skill_level)

        if npc.npc_type == NPC_CHILD:
            return [
                "お兄さんが魚を逃がしてあげてた！",
                "また会えるといいね！",
            ]
        elif npc.npc_type == NPC_BEGINNER:
            return [
                f"{self._vague_spot(spot)}にリリースされた魚がいるらしい。",
                "また釣れるのかな？",
            ]
        elif npc.npc_type == NPC_LOCAL:
            return [
                f"{spot}に{fi.release_count}回もリリースされた魚がいる。",
                "地元じゃちょっと有名なんだ。",
            ]
        elif npc.npc_type == NPC_VETERAN:
            return [
                f"{spot}に{fi.length:.1f}cmの個体がいる。",
                f"もう{fi.release_count}回リリースされてる。",
                "相当賢くなってるぞ。ルアーを変えないと口を使わない。",
            ]
        elif npc.npc_type == NPC_SHOPOWNER:
            return [
                "リリースアングラーのおかげで、",
                f"{spot}の魚が賢くなってきてる。",
                "いい傾向だよ。",
            ]
        return ["…"]

    def _general_dialogue(self, npc: NPCIndividual, environment) -> List[str]:
        season  = getattr(environment, "season_label", "？")
        weather = getattr(environment, "weather", "晴れ")
        act     = getattr(environment, "activity_modifier", 0.7)

        if npc.npc_type == NPC_CHILD:
            return [
                "今日もいい天気だね！",
                "魚ってどうやって釣るの？",
            ]
        elif npc.npc_type == NPC_BEGINNER:
            return [
                f"今日は{weather}だね。",
                "魚の活性ってどう判断すればいいんだろ。",
                "まだ全然わからないんだよね。",
            ]
        elif npc.npc_type == NPC_LOCAL:
            act_txt = "良さそう" if act >= 0.70 else "あまりよくなさそう"
            return [
                f"{season}の{weather}か。",
                f"今日の活性は{act_txt}だな。",
                "この湖は地元民には話せない場所が何箇所かある。",
            ]
        elif npc.npc_type == NPC_VETERAN:
            act_txt = ("高め" if act >= 0.80 else
                       "普通" if act >= 0.50 else "低め")
            return [
                f"今日は{weather}。魚の活性は{act_txt}だ。",
                f"この季節は{season}特有のパターンがある。",
                "焦らず観察することが大事だ。",
            ]
        elif npc.npc_type == NPC_SHOPOWNER:
            return [
                "いらっしゃい。今日は釣り日和？",
                f"{weather}の日はルアーカラーを意識するといいよ。",
            ]
        return ["…"]

    # ── 会話記録 ──────────────────────────────────────────────────────────

    def record_conversation(self, npc: NPCIndividual, game_day: int,
                            lines: List[str]) -> None:
        """会話を記録し友好度を +1 する。"""
        npc.last_talked_day = game_day
        npc.add_friendship(1)
        npc.conversation_history.append({"day": game_day, "lines": lines})
        if len(npc.conversation_history) > 20:
            npc.conversation_history = npc.conversation_history[-20:]

    # ── シリアライズ ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {"npcs": [n.to_dict() for n in self.npcs]}

    def from_dict(self, d: dict) -> None:
        """セーブデータを読み込み、既存NPCへマージする。"""
        saved = {n["npc_id"]: n for n in d.get("npcs", [])}
        for npc in self.npcs:
            if npc.npc_id in saved:
                r = NPCIndividual.from_dict(saved[npc.npc_id])
                npc.friendship         = r.friendship
                npc.known_fish         = r.known_fish
                npc.known_spots        = r.known_spots
                npc.last_talked_day    = r.last_talked_day
                npc.observation_log    = r.observation_log
                npc.conversation_history = r.conversation_history
