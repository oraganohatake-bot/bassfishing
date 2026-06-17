"""Fish Population System – Phase 10.

管理方式
--------
< 40 cm  : 群集管理 (small_population count のみ; セッション毎にランダムスポーン)
≥ 40 cm  : 個体管理 (FishIndividual — 永続IDを持つ個体)

FishIndividual フィールド
-------------------------
fish_id              : str    例 "B50012" (B=bass, 50=length整数, 0012=連番)
length               : float  cm
weight               : float  kg (length から推算)
age                  : int    ゲーム日数
home_spot            : str    スポット名
aggression           : float  0.0–1.0  (高い→活性高、bite積極的)
caution              : float  0.0–1.0  (高い→ルアーへの警戒強い)
memory_factor        : float  遺伝的学習速度 0.3–0.9 (高い→覚える速い)
lure_category_memory : dict   カテゴリ別記憶値 {"hard_bait": 0.0, ...}
last_hook_day        : int    最後にフッキングされた日 (-1=未経験)
last_seen_day        : int    最後に目撃された日 (-1=未経験)
legend_candidate     : bool   60cm以上の個体

釣果ルール
----------
- 釣られた個体は managed_fish から即削除 (再スポーンなし)
- 翌日: 過疎スポットに一定確率で新個体が自然補充される
- 毎日: update_memory() で忘却・警戒心減衰
"""

from __future__ import annotations

import random
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Tuple


# ── 体重推算 ──────────────────────────────────────────────────────────
# ラージマウスバス: W(kg) ≈ (L/28.4)^3.26  (L in cm)
def _weight_kg(length_cm: float) -> float:
    return round((length_cm / 28.4) ** 3.26, 3)


# ── ルアーカテゴリ定義 ────────────────────────────────────────────────
LURE_CATEGORIES: Tuple[str, ...] = (
    "hard_bait", "soft_bait", "topwater", "vibration", "bottom_contact"
)


# ── 個体データ ────────────────────────────────────────────────────────

@dataclass
class FishIndividual:
    """大型個体の永続データ (AIロジックは Fish クラスが担う)."""
    fish_id:    str
    length:     float   # cm
    weight:     float   # kg
    age:        int     # game-days
    home_spot:  str
    aggression: float   # 0.0–1.0
    caution:    float   # 0.0–1.0
    # Phase 9: Learning & Forgetting
    memory_factor:        float = 0.5    # genetic learning speed 0.3–0.9
    lure_category_memory: dict  = field(default_factory=dict)
    last_hook_day:        int   = -1     # game day of last hook / バラシ
    last_seen_day:        int   = -1     # game day of last APPROACH event
    legend_candidate:     bool  = False  # 60cm+ individual
    # Phase 9.5: Growth System
    genetic_max_size:     float = 0.0   # cm; 0.0 = unset (migrated lazily)
    growth_rate:          float = 0.015 # daily growth rate coefficient
    health:               float = 1.0   # 0.0–1.0 growth modifier
    # Phase 10: Catch & Release
    release_count:        int   = 0     # how many times this individual was released
    last_release_day:     int   = -1    # game day of last release (-1 = never)

    # ── 学習メソッド ─────────────────────────────────────────────────

    def learn(self, event: str, lure_category: str, game_day: int = -1) -> None:
        """釣りイベントから学習する。
        event: "spook" | "miss" (バラシ) | "catch" (C&R)
        lure_category: LURE_CATEGORIES のいずれか
        """
        learn_mult, _ = self._age_factors()
        learn_mult *= self._size_learn_mult()

        if event == "spook":
            mem_delta = 0.01 * self.memory_factor * learn_mult
            cau_delta = 0.0
        elif event == "miss":   # バラシ: フッキング後に逃げた
            mem_delta = 0.05 * self.memory_factor * learn_mult
            cau_delta = 0.03 * learn_mult
            if game_day >= 0:
                self.last_hook_day = game_day
        elif event == "catch":  # C&R (Phase 10 で完全実装)
            mem_delta = 0.10 * self.memory_factor * learn_mult
            cau_delta = 0.05 * learn_mult
            if game_day >= 0:
                self.last_hook_day = game_day
        else:
            return

        if lure_category not in self.lure_category_memory:
            self.lure_category_memory[lure_category] = 0.0
        self.lure_category_memory[lure_category] = min(
            1.0, self.lure_category_memory[lure_category] + mem_delta
        )
        self.caution = min(1.0, self.caution + cau_delta)

        if event in ("spook", "miss", "catch") and game_day >= 0:
            self.last_seen_day = game_day

    def daily_grow(self) -> None:
        """毎日呼び出す成長処理。genetic_max_size に向かって漸近成長する。"""
        self.age += 1

        # 旧セーブデータ互換: genetic_max_size が未設定なら初期化
        if self.genetic_max_size <= 0.0:
            self.genetic_max_size = round(
                self.length + random.uniform(3.0, 12.0), 1
            )

        if self.length >= self.genetic_max_size:
            return

        remaining = self.genetic_max_size - self.length
        growth = self.growth_rate * remaining * 0.10 * self.health
        self.length += growth
        self.weight = _weight_kg(self.length)

        if self.length >= 60.0:
            self.legend_candidate = True

    def daily_forget(self) -> None:
        """毎日呼び出す忘却処理。記憶と警戒心を少しずつ減らす。"""
        _, forget_mult = self._age_factors()
        legend_mod = 0.8 if self.legend_candidate else 1.0  # legend は忘れにくい

        # カテゴリ記憶の忘却 (ベース: 1日 1.0% 減)
        loss_rate = 0.010 * forget_mult * legend_mod
        for cat in list(self.lure_category_memory.keys()):
            v = self.lure_category_memory[cat] * (1.0 - loss_rate)
            self.lure_category_memory[cat] = max(0.0, v)

        # 警戒心の忘却 (ベース: 1日 0.1% 減)
        cau_loss = 0.001 * forget_mult * legend_mod
        self.caution = max(0.1, min(1.0, self.caution * (1.0 - cau_loss)))

    def memory_for_category(self, lure_category: str) -> float:
        """カテゴリの記憶値を返す (未記録 = 0.0)。"""
        return self.lure_category_memory.get(lure_category, 0.0)

    # ── 内部ヘルパー ──────────────────────────────────────────────────

    def _age_factors(self) -> Tuple[float, float]:
        """(learning_mult, forget_mult) を年齢ベースで返す。"""
        if self.age < 3:
            return (0.7, 1.3)   # 若魚: 覚えにくく、忘れやすい
        elif self.age > 8:
            return (1.3, 0.7)   # 老魚: 覚えやすく、忘れにくい
        return (1.0, 1.0)

    def _size_learn_mult(self) -> float:
        """サイズ補正: 大型魚ほど学習効果増加。"""
        if self.length > 60:
            return 1.5
        elif self.length > 50:
            return 1.2
        return 1.0

    # ── シリアライズ ──────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "FishIndividual":
        return FishIndividual(
            fish_id              = str(d["fish_id"]),
            length               = float(d["length"]),
            weight               = float(d["weight"]),
            age                  = int(d["age"]),
            home_spot            = str(d["home_spot"]),
            aggression           = float(d["aggression"]),
            caution              = float(d["caution"]),
            # Phase 9 フィールド (旧セーブデータとの互換性のため defaults あり)
            memory_factor        = float(d.get("memory_factor", 0.5)),
            lure_category_memory = dict(d.get("lure_category_memory", {})),
            last_hook_day        = int(d.get("last_hook_day", -1)),
            last_seen_day        = int(d.get("last_seen_day", -1)),
            legend_candidate     = bool(d.get("legend_candidate", False)),
            # Phase 9.5 フィールド (旧セーブデータ互換: 0.0 のとき daily_grow で遅延初期化)
            genetic_max_size     = float(d.get("genetic_max_size", 0.0)),
            growth_rate          = float(d.get("growth_rate", 0.015)),
            health               = float(d.get("health", 1.0)),
            # Phase 10 フィールド
            release_count        = int(d.get("release_count", 0)),
            last_release_day     = int(d.get("last_release_day", -1)),
        )

    @property
    def size_label(self) -> str:
        """表示用サイズラベル。"""
        if self.length >= 60:
            return "★ LEGEND"
        if self.length >= 50:
            return "★ BIG"
        return ""


# ── Phase 10: 釣果履歴 ───────────────────────────────────────────────

@dataclass
class FishHistory:
    """個体ごとの累積釣果履歴 (KEEP/RELEASE 問わず全キャッチを記録)。"""
    fish_id:           str
    first_caught_day:  int
    last_caught_day:   int
    total_catches:     int
    total_releases:    int
    best_length:       float

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "FishHistory":
        return FishHistory(
            fish_id           = str(d["fish_id"]),
            first_caught_day  = int(d["first_caught_day"]),
            last_caught_day   = int(d["last_caught_day"]),
            total_catches     = int(d["total_catches"]),
            total_releases    = int(d["total_releases"]),
            best_length       = float(d["best_length"]),
        )


# ── 群集・個体管理マネージャ ──────────────────────────────────────────

class FishPopulationManager:
    """全スポットの魚個体群を管理する。Game が 1 インスタンスを保持する。"""

    # グローバル連番 (セッション跨ぎで保存・復元)
    _id_counter: int = 0

    def __init__(self, rng_seed: int = 42) -> None:
        self._rng = random.Random(rng_seed)
        # 大型個体辞書: fish_id → FishIndividual
        self.managed_fish: Dict[str, FishIndividual] = {}
        # 小型群集カウント: spot_name → count (表示・将来の拡張用)
        self.small_population: Dict[str, int] = {}
        # Phase 10: 釣果履歴: fish_id → FishHistory
        self.fish_history: Dict[str, FishHistory] = {}

    # ── ID 生成 ────────────────────────────────────────────────────────

    def _next_id(self, length: float) -> str:
        FishPopulationManager._id_counter += 1
        return f"B{int(length):02d}{FishPopulationManager._id_counter:04d}"

    # ── スポット別クエリ ───────────────────────────────────────────────

    def get_spot_individuals(self, spot_name: str) -> List[FishIndividual]:
        """指定スポットに生息する全個体を返す。"""
        return [fi for fi in self.managed_fish.values()
                if fi.home_spot == spot_name]

    def all_individuals_sorted(self) -> List[FishIndividual]:
        """サイズ降順で全個体を返す (F2デバッグ用)。"""
        return sorted(self.managed_fish.values(),
                      key=lambda fi: fi.length, reverse=True)

    # ── 初期化 ────────────────────────────────────────────────────────

    def initialize_spot(self, spot_name: str) -> None:
        """スポットがまだ未初期化なら 4–8 個体を生成する。"""
        if self.get_spot_individuals(spot_name):
            return  # already populated

        count = self._rng.randint(4, 8)
        for _ in range(count):
            # 5% 確率でレジェンド候補 (60cm+) を生成
            if self._rng.random() < 0.05:
                length = round(self._rng.uniform(60.0, 65.0), 1)
            else:
                length = round(self._rng.uniform(40.0, 55.0), 1)
            is_legend = length >= 60.0
            base_caution = round(self._rng.uniform(0.20, 0.60), 2)
            if is_legend:
                base_caution = min(1.0, round(base_caution * 1.2, 2))
            fi = FishIndividual(
                fish_id          = self._next_id(length),
                length           = length,
                weight           = _weight_kg(length),
                age              = self._rng.randint(1, 6),
                home_spot        = spot_name,
                aggression       = round(self._rng.uniform(0.30, 0.90), 2),
                caution          = base_caution,
                memory_factor    = round(self._rng.uniform(0.30, 0.80), 2),
                legend_candidate = is_legend,
                genetic_max_size = round(length + self._rng.uniform(3.0, 12.0), 1),
                growth_rate      = round(self._rng.uniform(0.003, 0.030), 4),
                health           = 1.0,
            )
            self.managed_fish[fi.fish_id] = fi

    # ── Phase 10: 釣果・リリース履歴 ──────────────────────────────────

    def record_catch_history(
        self, fish_id: str, current_day: int, length: float
    ) -> bool:
        """キャッチ履歴を記録する。再捕獲なら True を返す。"""
        if fish_id in self.fish_history:
            h = self.fish_history[fish_id]
            h.total_catches += 1
            h.last_caught_day = current_day
            if length > h.best_length:
                h.best_length = length
            return True   # recapture
        self.fish_history[fish_id] = FishHistory(
            fish_id          = fish_id,
            first_caught_day = current_day,
            last_caught_day  = current_day,
            total_catches    = 1,
            total_releases   = 0,
            best_length      = length,
        )
        return False

    def record_release_history(self, fish_id: str) -> None:
        """リリース履歴を記録する。"""
        if fish_id in self.fish_history:
            self.fish_history[fish_id].total_releases += 1

    def get_history(self, fish_id: str) -> Optional[FishHistory]:
        return self.fish_history.get(fish_id)

    # ── 釣果処理 ──────────────────────────────────────────────────────

    def remove_caught(self, fish_id: str) -> Optional[FishIndividual]:
        """釣られた個体を削除。削除した個体を返す (なければ None)。"""
        return self.managed_fish.pop(fish_id, None)

    # ── 翌日補充 ──────────────────────────────────────────────────────

    def daily_replenish(self, all_spot_names: List[str]) -> List[FishIndividual]:
        """翌朝呼び出す。個体が少ないスポットへ確率的に新個体を追加。
        新しく追加した個体のリストを返す。"""
        new_fish: List[FishIndividual] = []
        for spot_name in all_spot_names:
            existing = self.get_spot_individuals(spot_name)
            if len(existing) < 2:
                # 40% の確率で補充
                if self._rng.random() < 0.40:
                    length = round(self._rng.uniform(40.0, 50.0), 1)
                    fi = FishIndividual(
                        fish_id          = self._next_id(length),
                        length           = length,
                        weight           = _weight_kg(length),
                        age              = 0,
                        home_spot        = spot_name,
                        aggression       = round(self._rng.uniform(0.30, 0.85), 2),
                        caution          = round(self._rng.uniform(0.20, 0.60), 2),
                        memory_factor    = round(self._rng.uniform(0.30, 0.80), 2),
                        legend_candidate = False,
                        genetic_max_size = round(length + self._rng.uniform(3.0, 12.0), 1),
                        growth_rate      = round(self._rng.uniform(0.003, 0.030), 4),
                        health           = 1.0,
                    )
                    self.managed_fish[fi.fish_id] = fi
                    new_fish.append(fi)
        return new_fish

    # ── 日次成長更新 ─────────────────────────────────────────────────

    def update_growth(self) -> None:
        """全個体の日次成長処理。毎日 advance_day 後に呼び出す。"""
        for fi in self.managed_fish.values():
            fi.daily_grow()

    # ── 日次記憶更新 ─────────────────────────────────────────────────

    def update_memory(self) -> None:
        """全個体の日次忘却処理。毎日 advance_day 後に呼び出す。"""
        for fi in self.managed_fish.values():
            fi.daily_forget()

    # ── 統計 ──────────────────────────────────────────────────────────

    @property
    def total_managed(self) -> int:
        return len(self.managed_fish)

    def spot_summary(self, spot_name: str) -> str:
        """スポット内個体数の簡易表示文字列。"""
        inds = self.get_spot_individuals(spot_name)
        if not inds:
            return "no large fish"
        sizes = sorted([fi.length for fi in inds], reverse=True)
        return "  ".join(f"{s:.0f}cm" for s in sizes)

    # ── シリアライズ ──────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "managed_fish":     {k: v.to_dict() for k, v in self.managed_fish.items()},
            "small_population": self.small_population,
            "_id_counter":      FishPopulationManager._id_counter,
            "fish_history":     {k: v.to_dict() for k, v in self.fish_history.items()},
        }

    def from_dict(self, d: dict) -> None:
        raw = d.get("managed_fish", {})
        self.managed_fish = {k: FishIndividual.from_dict(v) for k, v in raw.items()}
        self.small_population = dict(d.get("small_population", {}))
        FishPopulationManager._id_counter = int(d.get("_id_counter", 0))
        raw_hist = d.get("fish_history", {})
        self.fish_history = {k: FishHistory.from_dict(v) for k, v in raw_hist.items()}
