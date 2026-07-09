"""FishingView – Phase 3: retrieve actions, staged fish reactions, bite charge."""

from __future__ import annotations

import copy
import math
import random
from typing import Optional, Tuple

import pygame

from constants import (
    BUILD_ID,
    SCREEN_W, SCREEN_H, UW_SIZE, UW_W, UW_H, FISHING_VIEW_WIDTH_SCALE,
    ZOOM_W, PIX_DIV, SIZE_BOOST,
    FS_IDLE, FS_CAST_CHARGE, FS_CASTING, FS_RETRIEVE, FS_BITE,
    FS_WEIGHT, FS_LINE_RUN, FS_FIGHT,
    FS_KEEP_RELEASE, FS_RESULT,
    CAST_PERFECT, CAST_GOOD, CAST_EARLY, CAST_LATE,
    HOOKSET_DELAY, HOOKSET_AUTO, HOOKSET_HYBRID, HOOKSET_VISUAL_DELAY,
    BITE_LIGHT_TICK, BITE_MEDIUM_TICK, BITE_HEAVY_STRIKE,
    ACTION_IDLE, ACTION_RETRIEVE, ACTION_STOP,
    ACTION_TWITCH, ACTION_LIFT, ACTION_FALL,
    REACT_IGNORE, REACT_NOTICE, REACT_APPROACH,
    REACT_CHASE, REACT_BITE, REACT_SPOOK, FISH_CAUGHT,
    REACTION_PRIORITY,
    TERRAIN_WEED, TERRAIN_COVER, TERRAIN_BREAK, TERRAIN_ROCK,
    C_WHITE, C_BLACK, C_GRAY, C_YELLOW, C_GREEN, C_DARK, C_RED,
    C_FISH_IDLE, C_FISH_ACTIVE, C_LURE,
    C_FISH_NOTICE, C_FISH_APPROACH, C_FISH_BITE_COL, C_FISH_SPOOK,
    C_FLAT, C_WEED_CELL, C_COVER_CELL, C_BREAK_CELL, C_ROCK_CELL,
)
from spot_templates import SPOT_CONFIGS, DEFAULT_CONFIG
from underwater_map import UnderwaterMap
from fishing_spots import spot_name_to_id
from fishing_terrain import build_fishing_terrain
from fish import Fish
from lure import Lure
from lure_catalog import (
    LURE_CATALOG, get_spec_by_idx, optimal_slack_range, slack_modifier,
)
from save_manager import SaveManager
from environment import Environment
from fish_population import FishPopulationManager, FishIndividual
from rod import RodController
from fight_system import (
    FightState, T_BLUE, T_GREEN, T_YELLOW,
    OUTCOME_LANDED, OUTCOME_HOOKOUT, OUTCOME_LINE_BREAK,
    LANDING_DIST_M,
)
import tuning as TU

# ── Layout ────────────────────────────────────────────────────────────
MAIN_W    = 990                 # ビューポート幅 (画面に映る釣りビューの横幅)
SIDEBAR_X = 990
SIDEBAR_W = SCREEN_W - SIDEBAR_X

# Exploration v2: 釣りビューの「世界幅」は MAIN_W の 1.5x。
#   1マスのピクセルサイズは据え置き (= MAIN_W/UW_SIZE) のまま横にセルを増やすので、
#   見た目スケールは変わらず、岸と水面が実際に横へ広がる。常時 MAIN_W ぶんだけ表示し、
#   残りはカメラ(cam_x)で左右スクロールして見せる。
WORLD_W   = int(round(MAIN_W * FISHING_VIEW_WIDTH_SCALE))   # = 1485 (世界の横幅 px)
CAM_X_MAX = max(0, WORLD_W - MAIN_W)                        # カメラ可動域 [0, 495]
CAM_FOLLOW = 0.12               # カメラ追従の滑らかさ (lerp係数)

SKY_Y0   = 0
SKY_Y1   = 210
SHORE_Y0 = 210
SHORE_Y1 = 270
WATER_Y0 = 270    # horizon
WATER_Y1 = 510    # gradient end (visual)
WATER_NEAR_Y = 655  # near water edge: リトリーブ/キャスト可能エリアの手前端

CELL_PX    = 8
UW_GRID_X  = SIDEBAR_X + 12
UW_GRID_Y  = 46

# Phase D-1: baked structure layer cache (spot_id → Surface)。
# StructureObject の見た目は spot_id から決定的なので一度焼いたら使い回す。
_STRUCTURE_LAYER_CACHE: dict = {}

# Phase D-3.2: レイヤー切り分けフラグ。
#   旧 _struct_surf は underwater map のセル単位で岩/カバー/ウィード/ブレイクを
#   描く「マス目状」レイヤー。D-2 以降は StructureObject baked layer
#   (_structure_layer) を主表示にする方針なので、通常時は旧レイヤーを止める。
#   True にすると旧セルグリッド描画を復活させられる (デバッグ/比較用)。
SHOW_LEGACY_STRUCT_SURF = False
SHOW_STRUCTURE_LAYER     = True

# Phase D-3.4: StructureObject を「狙うべき場所」として十分な存在感にする。
#   D-3.2で旧グリッド層をOFFにした結果、新レイヤーの主役が広い水面に対して
#   小さすぎ「水に浮いた小物」に見えていた。表示スケールを底上げし、遠近縮小の
#   最小値も引き上げて奥側でも読めるサイズにする。配置(x/y/seed)は据え置きなので
#   baked cache / deterministic seed はそのまま維持される。
STRUCT_VISUAL_SCALE = 1.5     # 全ストラクチャー共通の見た目スケール底上げ

BITE_FRAMES   = 150
RESULT_FRAMES = 200

# ── Cast accuracy ────────────────────────────────────────────────────
CAST_MAX_ERR   = 4
INTENDED_FRAMES = 70

# ── Beta v0.9: Cast charge gauge (パラメータは tuning.py に集約) ─────
CAST_CHARGE_RATE   = TU.CAST_CHARGE_RATE
CAST_CHARGE_MAX    = TU.CAST_CHARGE_MAX
CAST_PERFECT_LO    = TU.CAST_PERFECT_LO
CAST_PERFECT_HI    = TU.CAST_PERFECT_HI
CAST_GOOD_LO       = TU.CAST_GOOD_LO

# Cast quality → (gauss σ, clamp cells)
_CAST_DEVIATION: dict = {
    CAST_PERFECT: TU.CAST_DEV_PERFECT,
    CAST_GOOD:    TU.CAST_DEV_GOOD,
    CAST_EARLY:   TU.CAST_DEV_EARLY,
    CAST_LATE:    TU.CAST_DEV_LATE,
}

# ── Beta v0.9: Hookset mode / bite type per lure name ────────────────
_HOOKSET_MODE: dict = {
    "Minnow":      HOOKSET_HYBRID,
    "Crankbait":   HOOKSET_AUTO,
    "Spinnerbait": HOOKSET_AUTO,
    "Worm":        HOOKSET_DELAY,
    "Jig":         HOOKSET_DELAY,
    "Topwater":    HOOKSET_VISUAL_DELAY,
}
_BITE_TYPE: dict = {
    "Minnow":      BITE_MEDIUM_TICK,
    "Crankbait":   BITE_HEAVY_STRIKE,
    "Spinnerbait": BITE_HEAVY_STRIKE,
    "Worm":        BITE_LIGHT_TICK,
    "Jig":         BITE_MEDIUM_TICK,
    "Topwater":    BITE_HEAVY_STRIKE,   # バシャ! (視覚はSPLASH演出)
}

# Bite-mode timeouts (frames since bite cue)
_BITE_TIMEOUT: dict = {
    HOOKSET_DELAY:        TU.DELAY_TIMEOUT,
    HOOKSET_HYBRID:       TU.HYBRID_TIMEOUT,
    HOOKSET_VISUAL_DELAY: 999,   # weight_on + TOPWATER_TIMEOUT_AFTER で個別判定
    HOOKSET_AUTO:         TU.AUTO_TIMEOUT,
}

# ── Beta v0.9: Fight threshold ───────────────────────────────────────
FIGHT_MIN_SIZE = TU.FIGHT_MIN_SIZE   # このサイズ以上でファイト発生

# ── Beta v0.9: Reel input (パラメータは tuning.py に集約) ─────────────
REEL_TAP_FRAMES   = TU.REEL_TAP_FRAMES
REEL_FAST_CLICKS  = TU.REEL_FAST_CLICKS
REEL_FAST_WINDOW  = TU.REEL_FAST_WINDOW
REEL_FAST_FRAMES  = TU.REEL_FAST_FRAMES
REEL_CREEP_FRAMES = TU.REEL_CREEP_FRAMES

# ── Rod anchor (一人称視点; プレイヤーの手元) ────────────────────────
# バットは画面下端のさらに下から伸びる = プレイヤーの手元から出ている表現。
# x はプレイヤーの立ち位置 (player_stance_x) に連動 (FishingView.rod_anchor)。
ROD_BASE_Y = SCREEN_H + 18
ROD_ANCHOR = (MAIN_W // 2, ROD_BASE_Y)   # 後方互換のデフォルト (中央立ち)

# ── Pin-spot thresholds ──────────────────────────────────────────────
PIN_HIGH_SCORE = 6.0
PIN_LOW_SCORE  = 3.0
PIN_SMALL_LIMIT = 34.0

# ── Bite charge (パラメータは tuning.py に集約) ──────────────────────
BITE_TRIGGER = TU.BITE_TRIGGER     # charge threshold → HIT!

# Charge rate per action when fish is in bite range
_CHARGE_RATE: dict = {
    ACTION_STOP:     TU.BITE_CHARGE_RATE_STOP,
    ACTION_TWITCH:   TU.BITE_CHARGE_RATE_TWITCH,
    ACTION_FALL:     TU.BITE_CHARGE_RATE_FALL,
    ACTION_LIFT:     TU.BITE_CHARGE_RATE_LIFT,
    ACTION_RETRIEVE: TU.BITE_CHARGE_RATE_RETRIEVE,
    ACTION_IDLE:     TU.BITE_CHARGE_RATE_IDLE,
}

# ── Debug ─────────────────────────────────────────────────────────────
_MAX_SCORE_VIS = 12.0


def _score_to_heat(score: float) -> Tuple[int, int, int]:
    t = min(1.0, score / _MAX_SCORE_VIS)
    if t < 0.35:
        k = t / 0.35
        return (int(k * 30), int(k * 90), int(140 + k * 60))
    elif t < 0.70:
        k = (t - 0.35) / 0.35
        return (int(30 + k * 210), int(90 + k * 120), int(200 - k * 150))
    else:
        k = (t - 0.70) / 0.30
        return (240, int(210 - k * 210), max(0, int(50 - k * 50)))


# ── Action display metadata ───────────────────────────────────────────
_ACTION_COLOR: dict = {
    ACTION_IDLE:     (140, 140, 140),
    ACTION_RETRIEVE: ( 70, 160, 220),
    ACTION_STOP:     (255, 220,  50),
    ACTION_TWITCH:   (255, 140,   0),
    ACTION_LIFT:     ( 50, 220, 200),
    ACTION_FALL:     ( 80, 120, 200),
}
_ACTION_LABEL: dict = {
    ACTION_IDLE:     "IDLE",
    ACTION_RETRIEVE: "RETRIEVE",
    ACTION_STOP:     "STOP  ▸",
    ACTION_TWITCH:   "TWITCH",
    ACTION_LIFT:     "LIFT  ▲",
    ACTION_FALL:     "FALL  ▼",
}

# ── Fish reaction display metadata ────────────────────────────────────
_REACT_COLOR: dict = {
    REACT_IGNORE:  (130, 130, 130),
    REACT_NOTICE:  C_FISH_NOTICE,
    REACT_APPROACH:C_FISH_APPROACH,
    REACT_CHASE:   C_FISH_ACTIVE,
    REACT_BITE:    C_FISH_BITE_COL,
    REACT_SPOOK:   C_FISH_SPOOK,
    FISH_CAUGHT:   (60, 60, 60),
}
_REACT_LABEL: dict = {
    REACT_IGNORE:  "ignore",
    REACT_NOTICE:  "notice",
    REACT_APPROACH:"approach",
    REACT_CHASE:   "CHASE",
    REACT_BITE:    "BITE!",
    REACT_SPOOK:   "spooked",
    FISH_CAUGHT:   "caught",
}


def _draw_bar(
    surface: pygame.Surface,
    x: int, y: int, w: int, h: int,
    fill: float,
    color: tuple,
    bg: tuple = (50, 50, 50),
) -> None:
    pygame.draw.rect(surface, bg,    (x, y, w, h))
    fw = max(0, int(w * max(0.0, min(1.0, fill))))
    if fw:
        pygame.draw.rect(surface, color, (x, y, fw, h))
    pygame.draw.rect(surface, (90, 90, 90), (x, y, w, h), 1)


# ══════════════════════════════════════════════════════════════════════
class FishingView:
    """Complete fishing scene: rendering, lure actions, fish AI, catch log."""

    def __init__(
        self,
        spot_name: str,
        seed: int = 42,
        save_manager: Optional[SaveManager] = None,
        environment: Optional[Environment] = None,
        fish_population: Optional[FishPopulationManager] = None,
        test_big_fish: bool = False,
    ) -> None:
        self.spot_name = spot_name
        self.state = FS_IDLE
        self._save_manager = save_manager
        self._env = environment
        self._population = fish_population
        # Beta v0.9: F4 大型魚テストモード (52/58/64cm を追加スポーン)
        self._test_big_fish = test_big_fish

        config = SPOT_CONFIGS.get(spot_name, DEFAULT_CONFIG)
        self.spot_label: str = config.get("label", "")

        # プレイヤーの立ち位置 (足場) — ライン角度/アプローチ角を決める。
        # 釣りビューに入った時点で岸位置から決まる (今は spot/seed から決定的に導出)。
        # 0.0=左端の岸, 0.5=正面, 1.0=右端の岸。将来は釣りビュー内で左右移動可に。
        stance_seed = (hash(spot_name) ^ (seed * 2654435761)) & 0xFFFF
        self.player_stance_x: float = 0.30 + 0.40 * (stance_seed % 1000) / 1000.0

        # Exploration v2: 横スクロールカメラ。player_stance_x(0..1, 世界全幅) を
        # 中央寄せで追従する。cam_x は世界座標→画面座標のオフセット(px)。
        self.cam_x: float = 0.0
        self.cam_x = self._camera_target()   # 初期位置を即合わせ (起動時のスクロール無し)

        # キャストカーソル (キャスト前に十字キーで動かす狙い点; セル単位)。
        # 立ち位置の正面・中距離を初期位置とする。x は広がった幅(UW_W)基準。
        self.cast_cursor_x: float = self.player_stance_x * (UW_W - 1)
        self.cast_cursor_y: float = (UW_H - 1) * 0.40

        rng = random.Random(seed)
        self.uw_map = UnderwaterMap(seed, config=config)
        self._lure_idx: int = 0
        self.lure = Lure(lure_type=LURE_CATALOG[0].name)
        self.fishes = self._spawn_fish(rng)
        self.catch_log: list = []

        self._bite_timer   = 0
        self._result_timer = 0
        self._result_fish: Optional[Fish] = None
        self._result_is_pb: bool = False
        self._splash_timer = 0
        self._frame_count  = 0

        # Phase 10: Catch & Release state
        self._result_action:      str   = ""    # "KEEP" or "RELEASE"
        self._result_reward:      int   = 0
        self._result_size:        float = 0.0   # stored for display after fish removed
        self._result_fish_id:     str   = ""
        self._result_is_recapture: bool = False
        self._recapture_prev: Optional[object] = None  # FishHistory snapshot

        # Cast accuracy
        self._intended_pos: Optional[Tuple[int, int]] = None
        self._intended_timer = 0

        # Bite charge
        self._bite_charge: float = 0.0

        # ── Beta v0.9: Rod / Cast / Reel / Bite / Fight ───────────────
        self.rod = RodController()

        # キャストゲージ (0→100→0 を往復するピンポン式)
        self._cast_charge: float = 0.0
        self._cast_dir: int = 1
        self._cast_aim: Optional[Tuple[int, int]] = None
        self._cast_quality: str = ""
        self._cast_quality_timer: int = 0

        # キャスト飛行演出 (FS_CASTING): ルアーが手元 → 着水点へ放物線で飛ぶ
        self._cast_flight_start: Tuple[float, float] = (0.0, 0.0)   # 画面座標(手元/ティップ)
        self._cast_flight_target: Tuple[float, float] = (0.0, 0.0)  # 画面座標(着水点)
        self._cast_flight_cell: Tuple[int, int] = (0, 0)            # 着水セル
        self._cast_flight_timer: int = 0
        self._cast_flight_duration: int = 0
        self._cast_arc_height: float = 0.0
        self._cast_flight_trail: list = []   # 軌跡 (画面座標)

        # リール入力トラッキング
        self._reel_press_frame: int = -1     # LMB押下開始フレーム (-1=非押下)
        self._reel_clicks: list = []         # 直近クリックのフレーム番号
        self._creep_frames: int = 0          # チョイ巻き残フレーム
        self._fast_frames: int = 0           # 早巻き残フレーム

        # バイト/フッキング
        self._bite_mode: str = ""            # HOOKSET_* (バイト発生時に確定)
        self._bite_type: str = ""            # BITE_* (演出種別)
        self._bite_elapsed: int = 0          # バイトキューからの経過フレーム
        self._weight_on_frame: int = 0       # VISUAL_DELAY: 重みが乗るフレーム
        # Hooking v1: ワーム系 WEIGHT/LINE_RUN 工程
        self._bite_fish: Optional[Fish] = None        # バイト中の魚 (LINE_RUNで走らせる)
        self._line_run_dir: Tuple[float, float] = (0.0, -1.0)  # ライン走行方向 (沖向き)
        # イベント駆動バイト用トラッキング
        self._prev_lure_cell: Tuple[int, int] = (-1, -1)
        self._was_in_range: bool = False
        self._bite_event_cd: int = 0         # イベント発火クールダウン残f
        # Beta v0.96: バイト成立時の slack_m と適正度 (フッキング品質に反映)
        self._bite_slack: float = 0.0
        self._bite_slack_mod: float = 1.0

        # ファイト
        self.fight: Optional[FightState] = None
        # フッキング地点 (画面座標) と開始距離 — ファイト描画の基準
        self._fight_hook_sx: int = MAIN_W // 2
        self._fight_hook_sy: int = (WATER_Y0 + WATER_NEAR_Y) // 2
        self._fight_start_dist: float = 10.0
        self._fight_fish: Optional[Fish] = None
        self._fight_events: list = []        # (msg, timer) フラッシュ表示
        self._result_lost_reason: str = ""

        # Pressure grid (runtime, not saved)
        self._pressure = [[0] * UW_W for _ in range(UW_H)]

        # Phase A: FishingTerrain (InfluenceGrid)
        self.spot_id: str = spot_name_to_id(spot_name)
        self.terrain = build_fishing_terrain(self.spot_id)

        # Debug
        self.debug_mode = False

        # Fonts / surfaces (init_fonts() sets these)
        self.font: Optional[pygame.font.Font] = None
        self.font_lg: Optional[pygame.font.Font] = None
        self.font_sm: Optional[pygame.font.Font] = None
        self._terrain_surf: Optional[pygame.Surface] = None
        self._score_surf:   Optional[pygame.Surface] = None
        self._struct_surf:  Optional[pygame.Surface] = None  # フィールド内ストラクチャー
        self._structure_layer: Optional[pygame.Surface] = None  # Phase D-1: StructureObject焼き込みレイヤー
        self._vgauge_surf:  Optional[pygame.Surface] = None  # テンションゲージ(縦グラデ)
        self._depth_tint_surf: Optional[pygame.Surface] = None  # Phase B: 水深濃淡レイヤー (未使用)
        self._depth_debug_surf: Optional[pygame.Surface] = None  # F2デバッグ用水深グラデ

        # V5: 軽量水面パーティクル (波紋/スプラッシュ/しぶき)
        self._particles: list = []

        # Mobile HUD: Game が毎フレーム touch._touch_active をここへ転写する
        self.is_mobile: bool = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def init_fonts(self) -> None:
        self.font    = pygame.font.Font(None, 28)
        self.font_lg = pygame.font.Font(None, 80)
        self.font_sm = pygame.font.Font(None, 22)
        self._build_terrain_surf()
        self._build_score_surf()
        self._build_field_struct_surf()
        self._structure_layer = self._get_or_build_structure_layer()
        self._build_vgauge_surf()
        self._build_depth_tint_surf()
        self._build_depth_debug_surf()
        # Pixel-art pipeline surfaces (pre-allocated, 24-bit to avoid A=0 transparency on macOS SDL2)
        self._full_off = pygame.Surface((MAIN_W, SCREEN_H), 0, 24)
        self._pix_off  = pygame.Surface((MAIN_W // PIX_DIV, SCREEN_H // PIX_DIV), 0, 24)
        self._pix_crop = pygame.Surface((ZOOM_W // PIX_DIV, SCREEN_H // PIX_DIV), 0, 24)
        self._zoomed   = pygame.Surface((MAIN_W, SCREEN_H), 0, 24)

    def _build_terrain_surf(self) -> None:
        surf = pygame.Surface((UW_W * CELL_PX, UW_H * CELL_PX))
        for cy in range(UW_H):
            for cx in range(UW_W):
                cell = self.uw_map.cell(cx, cy)
                if cell.terrain == TERRAIN_ROCK:
                    color = C_ROCK_CELL
                elif cell.cover:
                    color = C_COVER_CELL
                elif cell.weed:
                    color = C_WEED_CELL
                elif cell.terrain == TERRAIN_BREAK:
                    color = C_BREAK_CELL
                else:
                    d = min(1.0, cell.depth / 3.5)
                    color = (int(20 + d*30), int(60 + d*60), int(140 + d*60))
                pygame.draw.rect(surf, color,
                                 (cx*CELL_PX, cy*CELL_PX, CELL_PX-1, CELL_PX-1))
        self._terrain_surf = surf

    def _build_score_surf(self) -> None:
        surf = pygame.Surface((UW_W * CELL_PX, UW_H * CELL_PX))
        for cy in range(UW_H):
            for cx in range(UW_W):
                color = _score_to_heat(self.uw_map.full_score(cx, cy))
                pygame.draw.rect(surf, color,
                                 (cx*CELL_PX, cy*CELL_PX, CELL_PX-1, CELL_PX-1))
        self._score_surf = surf

    # 縦型テンションゲージ (画面右側)。下=SLACK(青) 上=DANGER(赤)。
    _VGAUGE_W = 22
    _VGAUGE_H = 300
    _VGAUGE_X = MAIN_W - 50
    _VGAUGE_Y = 200

    def _build_vgauge_surf(self) -> None:
        """テンションゲージの縦グラデーションを事前生成 (下:青→上:赤)。

        色は zone 境界 (T_BLUE/T_GREEN/T_YELLOW) をアンカーに滑らかに補間する。
        下端 = テンション0 (SLACK)、上端 = テンション1 (DANGER)。
        """
        W, H = self._VGAUGE_W, self._VGAUGE_H
        surf = pygame.Surface((W, H))
        # (テンション位置 0..1, RGB) のアンカー。
        stops = [
            (0.00, (40,  90, 200)),   # SLACK 濃い青
            (T_BLUE, (60, 130, 220)),  # 青
            ((T_BLUE + T_GREEN) / 2, (50, 180, 90)),   # SAFE 緑
            (T_GREEN, (120, 200, 60)),
            (T_YELLOW, (235, 200, 50)),  # 黄
            (0.92, (220, 70, 45)),    # DANGER 赤
            (1.00, (180, 40, 30)),
        ]
        def lerp(a, b, t):
            return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
        for yy in range(H):
            v = 1.0 - yy / (H - 1)   # 上端=1(DANGER) 下端=0(SLACK)
            for i in range(len(stops) - 1):
                p0, c0 = stops[i]
                p1, c1 = stops[i + 1]
                if p0 <= v <= p1:
                    tt = (v - p0) / (p1 - p0) if p1 > p0 else 0.0
                    col = lerp(c0, c1, tt)
                    break
            else:
                col = stops[-1][1]
            pygame.draw.line(surf, col, (0, yy), (W, yy))
        self._vgauge_surf = surf

    def _build_depth_tint_surf(self) -> None:
        """Phase B: terrain.cells の水深を水面に薄く投影するレイヤーを事前生成。

        WORLD_W×SCREEN_H の SRCALPHA サーフェスを作り、
        terrain のセルごとに浅い=薄め / 深い=暗め の色矩形を塗る。
        _draw_scene で (-cam_x, 0) にブリットする。
        既存描画の上に重ねるだけなので黒画面化しない。
        """
        from fishing_spots import get_fishing_spot

        surf = pygame.Surface((WORLD_W, SCREEN_H), pygame.SRCALPHA)
        tr = self.terrain
        if not tr.cells:
            self._depth_tint_surf = surf
            return

        spot = get_fishing_spot(self.spot_id)
        depth_range = max(0.1, spot.max_depth_m - spot.base_depth_m)
        water_h = WATER_NEAR_Y - WATER_Y0
        cell_w = WORLD_W / tr.grid_cols
        cell_h = water_h / tr.grid_rows

        for row in range(tr.grid_rows):
            y0 = int(WATER_Y0 + row * cell_h)
            y1 = min(int(WATER_Y0 + (row + 1) * cell_h) + 1, WATER_NEAR_Y)
            if y1 <= y0:
                continue
            for col in range(tr.grid_cols):
                x0 = int(col * cell_w)
                x1 = int((col + 1) * cell_w) + 1
                tc = tr.cell(col, row)
                t = max(0.0, min(1.0, (tc.depth_m - spot.base_depth_m) / depth_range))
                # 浅い(t=0): ほぼ透明 / 深い(t=1): 暗い紺でやや不透明
                alpha = int(12 + t * 48)     # 12 → 60
                r_val = int(8  * (1.0 - t))  # 8  → 0
                g_val = int(30 * (1.0 - t))  # 30 → 0
                b_val = int(80 + t * 40)     # 80 → 120
                surf.fill((r_val, g_val, b_val, alpha), (x0, y0, x1 - x0, y1 - y0))

        self._depth_tint_surf = surf

    def _build_depth_debug_surf(self) -> None:
        """F2デバッグ時だけ表示する水深グラデーションオーバーレイ。

        浅い=シアン / 中間=青 / 深い=濃紺。slope 高い箇所はオレンジで強調。
        通常プレイ時には使用しない (_draw_scene で debug_mode 時のみ blit)。
        """
        from fishing_spots import get_fishing_spot

        surf = pygame.Surface((WORLD_W, SCREEN_H), pygame.SRCALPHA)
        tr = self.terrain
        if not tr.cells:
            self._depth_debug_surf = surf
            return

        spot = get_fishing_spot(self.spot_id)
        min_depth = spot.base_depth_m
        max_depth = spot.max_depth_m
        depth_range = max(0.1, max_depth - min_depth)
        water_h = WATER_NEAR_Y - WATER_Y0
        cell_w = WORLD_W / tr.grid_cols
        cell_h = water_h / tr.grid_rows

        for row in range(tr.grid_rows):
            y0 = int(WATER_Y0 + row * cell_h)
            y1 = min(int(WATER_Y0 + (row + 1) * cell_h) + 1, WATER_NEAR_Y)
            if y1 <= y0:
                continue
            for col in range(tr.grid_cols):
                x0 = int(col * cell_w)
                x1 = int((col + 1) * cell_w) + 1
                tc = tr.cell(col, row)
                t = max(0.0, min(1.0, (tc.depth_m - min_depth) / depth_range))
                # 浅い(t=0): シアン / 中間(t=0.5): 青 / 深い(t=1): 濃紺
                if t < 0.5:
                    k = t / 0.5
                    r_v = int(80 * (1.0 - k) + 40 * k)
                    g_v = int(220 * (1.0 - k) + 110 * k)
                    b_v = int(230 * (1.0 - k) + 220 * k)
                    alpha = int(90 + k * 5)
                else:
                    k = (t - 0.5) / 0.5
                    r_v = int(40 * (1.0 - k) + 20 * k)
                    g_v = int(110 * (1.0 - k) + 20 * k)
                    b_v = int(220 * (1.0 - k) + 120 * k)
                    alpha = int(95 + k * 15)
                surf.fill((r_v, g_v, b_v, alpha), (x0, y0, x1 - x0, y1 - y0))
                # slope 強調 (オレンジ): 駆け上がりを薄く広めに示す。
                # 細い1セル幅の線で溝のように見せないよう alpha を抑える。
                if tc.slope > 0.25:
                    over_a = int(min(22, tc.slope * 22))
                    surf.fill((255, 190, 40, over_a), (x0, y0, x1 - x0, y1 - y0))
                # グリッド線 (非常に薄い)
                pygame.draw.line(surf, (255, 255, 255, 20), (x0, y0), (x0, y1 - 1))
                pygame.draw.line(surf, (255, 255, 255, 20), (x0, y0), (x1 - 1, y0))

        self._depth_debug_surf = surf

    def _build_field_struct_surf(self) -> None:
        """釣りビュー内のストラクチャー描画 (常時表示) を事前生成する。

        水中: ウィード/カバー/ロック/ブレイクのセルを半透明の色味で水面に投影。
        水上: ウィードの穂先・カバーの立ち木/杭・水面を割るロックを
              セル位置から上方向へ描き込む (奥ほど小さく = 簡易パース)。
        """
        # Exploration v2: 世界幅(WORLD_W)で構築し、毎フレーム -cam_x で blit する。
        # ※ カメラ込みの _uw_to_screen ではなく、カメラ無しの _uw_to_world を使う
        #    (二重適用の防止)。
        surf = pygame.Surface((WORLD_W, SCREEN_H), pygame.SRCALPHA)

        for cy in range(UW_H):
            scale = (0.35 + 0.65 * (cy / (UW_H - 1))) * SIZE_BOOST
            for cx in range(UW_W):
                cell = self.uw_map.cell(cx, cy)
                sx, sy = self._uw_to_world(cx, cy)
                x0, y0 = self._uw_to_world(cx - 0.5, cy - 0.5)
                x1, y1 = self._uw_to_world(cx + 0.5, cy + 0.5)
                w, h = max(2, x1 - x0), max(2, y1 - y0)
                j = (cx * 73 + cy * 131) % 7   # セル固有の揺らぎ

                if cell.terrain == TERRAIN_ROCK:
                    # 水中の岩影 + 水面を割る岩頭
                    pygame.draw.ellipse(surf, (95, 95, 105, 70), (x0, y0, w, h))
                    rw = int((6 + j) * scale)
                    rh = int((4 + j // 2) * scale)
                    if rw >= 2 and rh >= 2:
                        pygame.draw.ellipse(
                            surf, (110, 110, 120, 230),
                            (sx - rw, sy - rh, rw * 2, rh + 2))
                        pygame.draw.ellipse(
                            surf, (200, 215, 230, 90),
                            (sx - rw - 3, sy - 2, rw * 2 + 6, 4), 1)
                elif cell.cover:
                    # 水中のカバー影 + 立ち木/杭
                    pygame.draw.ellipse(surf, (110, 75, 35, 75), (x0, y0, w, h))
                    th = int((16 + j * 3) * scale)
                    tw = max(1, int(3 * scale))
                    tx = sx + (j - 3) * 2
                    pygame.draw.line(surf, (85, 58, 30, 235),
                                     (tx, sy + 2), (tx, sy - th), tw)
                    pygame.draw.line(surf, (85, 58, 30, 200),
                                     (tx, sy - th + 4),
                                     (tx + int(6 * scale) * (1 if j % 2 else -1),
                                      sy - th), max(1, tw - 1))
                elif cell.weed:
                    # 水中のウィード + 水面に出る穂先
                    pygame.draw.ellipse(surf, (40, 110, 55, 80), (x0, y0, w, h))
                    for k in range(2 + j % 2):
                        gx = sx + (k * 5 - 4) + (j % 3)
                        gh = int((7 + (j + k * 2) % 6) * scale)
                        pygame.draw.line(surf, (55, 130, 60, 220),
                                         (gx, sy + 1), (gx + 1, sy - gh), 1)
                elif cell.terrain == TERRAIN_BREAK:
                    # ブレイク: 水中のみ。色味を落とした帯で段差を示す
                    pygame.draw.rect(surf, (15, 45, 95, 70), (x0, y0, w, h))
                    pygame.draw.line(surf, (130, 170, 210, 60),
                                     (x0, y1 - 1), (x1, y1 - 1), 1)

        self._struct_surf = surf

    # ── Phase D-1: baked structure layer ────────────────────────────────
    # spot.structures (StructureObject) を一度だけ簡易シルエットで焼き込み、
    # 毎フレームは blit するだけにする。強化描画は次フェーズ以降。

    # D-3.4: HERO を一段大きく (主役の存在感)、LOW も豆粒化しない下限に。
    _TIER_MULT_D = {"LOW": 0.85, "MID": 1.0, "HERO": 1.4}

    # D-2.5: 重なり時の表示優先度。大きいほど強い(主役)。
    #   3 = 硬い構造物 (倒木/岩/杭/ブラッシュ/切株)
    #   2 = 植生 (葦/リリー)
    #   1 = 下地 (ウィード)
    _STRUCT_PRIORITY = {
        "laydown": 3, "rock_pile": 3, "stake_cluster": 3,
        "brush_pile": 3, "stump_field": 3,
        "reed_bed": 2, "lily_pads": 2,
        "weed_bed": 1,
    }

    # D-3.3: 植生 suppression の下限 (alpha_mult, count_mult, min_alpha)。
    #   強構造物の近くでも下地植生が完全に消えないようにする。
    _VEG_SUPP_FLOOR = {
        "weed_bed":  (0.45, 0.45, 90),
        "reed_bed":  (0.60, 0.60, 100),
        "lily_pads": (0.60, 0.60, 100),
    }

    def _get_or_build_structure_layer(self) -> pygame.Surface:
        """spot_id ごとに structure_layer をキャッシュして返す。"""
        cached = _STRUCTURE_LAYER_CACHE.get(self.spot_id)
        if cached is not None:
            return cached
        surf = self._build_structure_layer()
        _STRUCTURE_LAYER_CACHE[self.spot_id] = surf
        return surf

    def _build_structure_layer(self) -> pygame.Surface:
        """StructureObject を WORLD_W×SCREEN_H のレイヤーへ簡易シルエット描画。

        座標: struct.x [0..view_width_m] → world_x, struct.y [0..view_depth_m] →
        WATER_Y0(奥/深) .. WATER_NEAR_Y(手前/浅) へマップ (_bake_structures と同じ向き)。
        奥ほど小さく薄く、手前ほど大きく濃く。seed 固定で毎回同じ見た目。
        """
        surf = pygame.Surface((WORLD_W, SCREEN_H), pygame.SRCALPHA)
        tr = self.terrain
        vw = max(0.1, tr.view_width_m)
        vd = max(0.1, tr.view_depth_m)
        water_h = WATER_NEAR_Y - WATER_Y0

        drawers = {
            "stake_cluster": self._sl_stake_cluster,
            "laydown":       self._sl_laydown,
            "weed_bed":      self._sl_weed_bed,
            "reed_bed":      self._sl_reed_bed,
            "lily_pads":     self._sl_lily_pads,
            "rock_pile":     self._sl_rock_pile,
            "stump_field":   self._sl_stump_field,
            "brush_pile":    self._sl_brush_pile,
        }

        # world 位置を先に確定 (重なり優先判定 / stake variant 判定に使う)
        placed = []
        for st in tr.structures:
            depth_t = max(0.0, min(1.0, getattr(st, "y", 0.0) / vd))
            wx = int((getattr(st, "x", 0.0) / vw) * WORLD_W)
            wy = int(WATER_Y0 + depth_t * water_h)
            placed.append((st, wx, wy, depth_t))

        # 葦原の world 中心 (近くの stake_cluster を reed_fence に寄せる)
        reed_centers = [(w, y) for st, w, y, _ in placed
                        if getattr(st, "type", None) == "reed_bed"]

        # 奥 → 手前 の順で描くと手前が上に重なって自然 (y昇順 = 奥から)
        for st, wx, wy, depth_t in sorted(placed, key=lambda p: getattr(p[0], "y", 0.0)):
            stype = getattr(st, "type", None)
            drawer = drawers.get(stype)
            if drawer is None:
                continue
            # D-3.4: 遠近縮小の最小値を 0.55→0.75 に引き上げ、奥側でも葦/杭/岩が
            #        読めるサイズにする。全体に STRUCT_VISUAL_SCALE を掛けて底上げ。
            persp = 0.75 + 0.65 * depth_t                       # 手前=大 / 奥も豆粒化しない
            sc = (st.scale * self._TIER_MULT_D.get(st.tier, 1.0)
                  * persp * STRUCT_VISUAL_SCALE)
            alpha = max(120, min(235, int(150 + depth_t * 70)))  # 手前=濃
            rng = random.Random(st.seed)
            # 上位ストラクチャーの近くでは下位を薄く/間引く
            supp_a, supp_c = self._structure_suppression(st, wx, wy, placed)
            if stype in ("weed_bed", "reed_bed", "lily_pads"):
                # D-3.3: suppression で完全消滅しないよう下限を設ける。
                #   旧グリッドレイヤーが担っていた量感を新レイヤーで復活させる。
                a_floor, c_floor, min_a = self._VEG_SUPP_FLOOR[stype]
                sa = max(supp_a, a_floor)
                sc_supp = max(supp_c, c_floor)
                veg_alpha = max(int(alpha * sa), min_a)
                drawer(surf, wx, wy, sc, st, rng, veg_alpha, suppress=sc_supp)
            elif stype == "stake_cluster":
                variant = self._stake_variant(st, wx, wy, reed_centers)
                drawer(surf, wx, wy, sc, st, rng, alpha, variant=variant)
            else:
                drawer(surf, wx, wy, sc, st, rng, alpha)

        return surf

    def _structure_suppression(self, st, wx, wy, placed):
        """上位優先ストラクチャーが近いとき (alpha_mult, count_mult) を返す。

        下位 (植生/下地) は強い構造物 (杭/岩/倒木) と重なる領域で薄く/間引く。
        上位側 (priority>=3) は常に主役なので抑制しない。
        """
        pr = self._STRUCT_PRIORITY.get(getattr(st, "type", None), 2)
        if pr >= 3:
            return (1.0, 1.0)
        worst = 1.0
        for other, owx, owy, _ in placed:
            if other is st:
                continue
            opr = self._STRUCT_PRIORITY.get(getattr(other, "type", None), 2)
            if opr <= pr:
                continue
            r = 70.0 * max(0.6, getattr(other, "scale", 1.0))
            d = math.hypot(wx - owx, wy - owy)
            if d < r:
                worst = min(worst, 0.35 + 0.65 * (d / r))   # 近いほど薄い
        return (worst, 0.5 + 0.5 * worst)

    def _stake_variant(self, st, wx, wy, reed_centers):
        """stake_cluster の由来タイプを文脈から決める。

        葦原が近ければ reed_fence (葦縁の古い杭列)、それ以外は old_pier_remnant。
        近くに葦が無いスポット(岩場/桟橋跡)では決定的に old_pier_remnant にする。
        """
        thr = 160.0 * max(0.6, getattr(st, "scale", 1.0))
        for rwx, rwy in reed_centers:
            if math.hypot(wx - rwx, wy - rwy) < thr:
                return "reed_fence"
        return "old_pier_remnant"

    @staticmethod
    def _sl_base_shadow(surf, wx, wy, rw, rh, a):
        """根元の暗い楕円影 (水中馴染ませ)。"""
        rw = max(2, int(rw)); rh = max(2, int(rh))
        pygame.draw.ellipse(surf, (8, 24, 42, min(120, a)),
                            (wx - rw, wy - rh // 2, rw * 2, rh))

    def _draw_one_stake(self, surf, px, base_wy, sc, rng, a, broken_p, h_boost=1.0):
        """1本の杭を描く (幹・影・水際の黒ずみ・天面/折れ)。

        h_boost: 杭頭を水面上へ突き出させるための高さ倍率 (>1で高くなる)。
        """
        h = int(rng.uniform(16, 42) * sc * h_boost)          # 高さ差(大)
        w = max(2, int(rng.uniform(2.6, 4.2) * sc))          # 太さ差
        tilt = int(rng.uniform(-0.16, 0.16) * h)             # 傾き(混在方向)
        top_x, top_y = px + tilt, base_wy - h
        # 杭ごとの小さな根元影
        pygame.draw.ellipse(surf, (8, 24, 42, int(a * 0.5)),
                            (px - w, base_wy - 2, w * 2, 6))
        # 幹本体 (茶〜灰茶)
        pygame.draw.line(surf, (94, 68, 38, a), (px, base_wy), (top_x, top_y), w)
        # 影側 (暗い茶) を片側に薄く
        off = max(1, w // 3)
        pygame.draw.line(surf, (60, 42, 22, int(a * 0.55)),
                         (px + off, base_wy), (top_x + off, top_y), max(1, w // 2))
        # 水際の黒ずみ (根元付近の変色帯)
        band_h = int(h * rng.uniform(0.18, 0.32))
        bx = px + int(tilt * (band_h / max(1, h)))
        pygame.draw.line(surf, (34, 26, 20, int(a * 0.8)),
                         (px, base_wy), (bx, base_wy - band_h), w)
        # 天面 (切断面ハイライト / たまに折れ・欠け)
        broken = rng.random() < broken_p
        cap = (110, 84, 50, a) if broken else (150, 118, 70, a)
        pygame.draw.circle(surf, cap, (top_x, top_y),
                           max(1, w // 2 + (0 if broken else 1)))
        if broken:
            pygame.draw.circle(surf, (70, 52, 30, a),
                               (top_x + rng.randint(-1, 1), top_y), max(1, w // 3))

    def _sl_stake_cluster(self, surf, wx, wy, sc, st, rng, a, variant="old_pier_remnant"):
        # D-3.1: 由来タイプで「意味のある並び」にする。
        #   old_pier_remnant … 桟橋跡。沖へ向かう斜めライン + たまに2列(桟橋の足)。
        #                       高さ差・折れ杭が多く「朽ちた桟橋」に見せる。
        #   reed_fence        … 葦縁の杭列。弧状/折れ線で葦の縁に沿う。不規則・折れ少。
        reed_fence = (variant == "reed_fence")
        count = max(3, min(7, int(3 + 4 * st.density)))
        spread = int(count * 4 * sc)
        # cluster全体のうっすら影
        self._sl_base_shadow(surf, wx, wy, spread * 0.8, 9, a)
        broken_p = 0.10 if reed_fence else 0.32
        # D-3.4: 杭は必ず水面上に頭が出るよう高さを底上げする。
        #   桟橋跡(old_pier_remnant)はより高く突き出し「足場の柱」に、
        #   葦縁の杭(reed_fence)も水面上に頭が見えるよう控えめに高くする。
        h_boost = 1.35 if reed_fence else 1.7

        if reed_fence:
            # 葦縁に沿う弧状ライン (中央がせり出す)
            arc = rng.uniform(0.20, 0.44)
            arc_sign = rng.choice((-1, 1))
            for i in range(count):
                base_t = (i - (count - 1) / 2) / max(1, count - 1)   # -0.5..0.5
                px = wx + int(base_t * spread * 2) + rng.randint(-4, 4)
                y_arc = int(arc_sign * arc * spread * (1.0 - (2 * base_t) ** 2))
                self._draw_one_stake(surf, px, wy + y_arc, sc, rng, a, broken_p,
                                     h_boost=h_boost)
        else:
            # 桟橋跡: 沖(奥/上)へ向かう斜めの主ライン。たまに2列にして「足場」に。
            slope = rng.uniform(0.22, 0.5) * rng.choice((-1, 1))     # 斜め方向
            two_rows = rng.random() < 0.45
            row_dx = int(spread * 0.5)                               # 2列目の横ずれ
            row_dy = int(6 * sc)                                     # 2列目の奥ずれ
            for i in range(count):
                base_t = (i - (count - 1) / 2) / max(1, count - 1)   # -0.5..0.5
                px = wx + int(base_t * spread * 2) + rng.randint(-2, 2)
                py = wy + int(base_t * spread * slope)               # 斜めライン
                self._draw_one_stake(surf, px, py, sc, rng, a, broken_p,
                                     h_boost=h_boost)
                # 2列目 (桟橋の反対側の足): 本数は間引く
                if two_rows and rng.random() < 0.7:
                    self._draw_one_stake(surf, px + row_dx + rng.randint(-2, 2),
                                         py + row_dy, sc, rng, a, broken_p,
                                         h_boost=h_boost)

    def _sl_laydown(self, surf, wx, wy, sc, st, rng, a):
        """倒木: 太さ・根元(root ball)・枝・影を持つ水中カバーとして描く。

        hotspot 対応: root_hole=根元の暗いえぐれ(中心), branch_tip=枝の張り出し先,
        shade_line=幹下の影。幹は根元太→枝先細のテーパー、少し曲がりと節を持つ。
        """
        ang = math.radians(st.rotation)
        ca, sa = math.cos(ang), math.sin(ang)
        length = 62 * sc
        root_w = max(4, 9 * sc)                 # 根元の幹太さ
        tip_w = max(2.0, 3.0 * sc)              # 枝先側の細さ
        lift = 0.55                             # 奥行きによる y 方向の縮み
        bend = rng.uniform(-0.16, 0.16)         # 幹全体のたわみ

        # ── 幹の中心線 (少し曲がる) と各点の太さ ───────────────────
        root = (wx, wy - int(3 * sc))
        steps = 9
        pts, widths = [], []
        for i in range(steps + 1):
            t = i / steps
            along = length * t
            off = math.sin(t * math.pi) * bend * length      # 法線方向のたわみ
            px = root[0] + ca * along - sa * off
            py = root[1] + sa * along * lift + ca * off * lift - 7 * sc * t
            pts.append((px, py))
            widths.append(root_w * (1.0 - 0.75 * t) + tip_w * 0.25)

        # ── 幹下の影 (shade_line): 中心線を少し下にずらした暗帯 ─────
        self._sl_base_shadow(surf, wx, wy, 18 * sc, 13, a)
        for i in range(steps):
            (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            sh_w = max(2, int(widths[i] * 1.1))
            pygame.draw.line(surf, (6, 20, 34, int(a * 0.5)),
                             (int(x0 + 2), int(y0 + widths[i] * 0.7 + 3)),
                             (int(x1 + 2), int(y1 + widths[i + 1] * 0.7 + 3)), sh_w)

        # ── 幹ポリゴン (テーパー): 法線オフセットで左右エッジを作る ──
        left, right = [], []
        for i in range(len(pts)):
            if i < len(pts) - 1:
                dx = pts[i + 1][0] - pts[i][0]; dy = pts[i + 1][1] - pts[i][1]
            else:
                dx = pts[i][0] - pts[i - 1][0]; dy = pts[i][1] - pts[i - 1][1]
            dl = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / dl, dx / dl
            hw = widths[i] * 0.5
            left.append((pts[i][0] + nx * hw, pts[i][1] + ny * hw))
            right.append((pts[i][0] - nx * hw, pts[i][1] - ny * hw))
        trunk_poly = [(int(x), int(y)) for x, y in left + right[::-1]]
        # 沈んだ暗い本体
        pygame.draw.polygon(surf, (58, 42, 24, a), trunk_poly)
        # 上面の陽当り (中心線をわずかに上へずらした少し明るいテーパー線)
        for i in range(steps):
            (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            up0 = widths[i] * 0.16; up1 = widths[i + 1] * 0.16
            lw = max(1, int(widths[i] * 0.5))
            pygame.draw.line(surf, (92, 66, 36, int(a * 0.85)),
                             (int(x0), int(y0 - up0)), (int(x1), int(y1 - up1)), lw)
        # 節 (幹の途中の暗い横筋を数本)
        for i in (2, 4, 6):
            nx0 = pts[i]
            pygame.draw.circle(surf, (40, 28, 16, int(a * 0.8)),
                               (int(nx0[0]), int(nx0[1])), max(1, int(widths[i] * 0.45)))

        # ── 根元 / root ball (root_hole): 暗い塊 + 絡んだ根 + えぐれ影 ─
        rbx, rby = int(root[0]), int(root[1])
        rball = max(5, int(root_w * 1.5))
        # 根元周囲の暗い楕円影 (terrain の root_hole えぐれに対応)
        pygame.draw.ellipse(surf, (4, 16, 28, int(a * 0.6)),
                            (rbx - rball, rby - rball // 2 + 2, rball * 2, rball))
        rb_pts = []
        rn = 7
        for k in range(rn):
            pa = 2 * math.pi * k / rn
            rad = rball * rng.uniform(0.7, 1.15)
            rb_pts.append((int(rbx + math.cos(pa) * rad),
                           int(rby - math.sin(pa) * rad * 0.75)))
        pygame.draw.polygon(surf, (46, 34, 20, a), rb_pts)
        # 根が絡んだ短い枝線 (放射状)
        for _r in range(rng.randint(4, 6)):
            ra = rng.uniform(-math.pi, math.pi)
            rl = rball * rng.uniform(0.8, 1.4)
            pygame.draw.line(surf, (38, 27, 15, a), (rbx, rby),
                             (int(rbx + math.cos(ra) * rl),
                              int(rby - math.sin(ra) * rl * 0.7)),
                             max(1, int(root_w * 0.28)))
        # えぐれの黒い芯
        pygame.draw.circle(surf, (2, 12, 22, int(a * 0.85)), (rbx, rby),
                           max(2, int(rball * 0.4)))

        # ── 枝 (branch_tip): 2〜5本を先端寄りから左右にばらけて出す ──
        n_branch = max(2, min(5, int(2 + 3 * st.density)))
        for k in range(n_branch):
            t = rng.uniform(0.45, 0.95)
            # 中心線上の分岐点
            idx = min(steps, int(t * steps))
            bx, by = pts[idx]
            side = -1 if (k % 2 == 0) else 1
            bang = ang + side * math.radians(rng.uniform(22, 62))
            blen = length * rng.uniform(0.22, 0.42) * (0.6 + 0.4 * (1.0 - t))
            bw = max(2, int((tip_w + (root_w - tip_w) * (1.0 - t)) * 0.7))
            tx = int(bx + math.cos(bang) * blen)
            ty = int(by + math.sin(bang) * blen * lift - 4 * sc)
            pygame.draw.line(surf, (70, 50, 26, a), (int(bx), int(by)), (tx, ty), bw)
            # 枝先の細り + 小影 + 藻っぽい緑
            pygame.draw.line(surf, (54, 38, 20, int(a * 0.8)),
                             (tx, ty), (int(tx + math.cos(bang) * blen * 0.3),
                                        int(ty + math.sin(bang) * blen * 0.3 * lift)),
                             max(1, bw - 1))
            if rng.random() < 0.6:
                pygame.draw.circle(surf, (58, 84, 46, int(a * 0.7)), (tx, ty),
                                   max(1, int(2 * sc)))
            pygame.draw.ellipse(surf, (6, 20, 32, int(a * 0.35)),
                                (tx - int(3 * sc), ty + 1, int(6 * sc), int(3 * sc)))

        # ── 根元側の水中青被り (沈んでいる感) ───────────────────────
        submerged = [(int(pts[i][0]), int(pts[i][1])) for i in range(4)]
        if len(submerged) >= 2:
            pygame.draw.lines(surf, (34, 64, 88, int(a * 0.30)), False, submerged,
                              max(2, int(root_w * 0.6)))

    def _sl_rock_pile(self, surf, wx, wy, sc, st, rng, a):
        """岩場: 主塊(core) + 周辺の散り石(side) + 暗い隙間(crevice) の3層で描く。

        D-3.1: 箱状の均等ばら撒きをやめ、傾いた楕円分布 + 片寄り + 抜け(gap) で
        「寄っている所は寄っている、ない所はない」自然な岩場にする。
        hotspot 対応: rock_crevice=岩と岩の暗い隙間, hard_bottom_edge=岩場の外周
        (主塊外周の一部として視認)。角張った polygon の大小混在で岩場感を出す。
        """
        spread = int(26 * sc)

        # ── 岩場全体の向き / 偏り (行・列感を壊す) ────────────────────
        clus_ang = rng.uniform(-0.55, 0.55)                 # 傾いた楕円
        cca, csa = math.cos(clus_ang), math.sin(clus_ang)
        ax_r = 1.0
        ay_r = rng.uniform(0.42, 0.62)                      # 縦横比
        bias_ang = rng.uniform(0, 2 * math.pi)              # 散りの片寄り方向
        bias_x = math.cos(bias_ang) * spread * 0.30
        bias_y = math.sin(bias_ang) * spread * 0.16
        gap0 = rng.uniform(0, 2 * math.pi)                  # 抜けセクター
        gap_w = rng.uniform(0.7, 1.25)

        def _in_gap(theta):
            return ((theta - gap0) % (2 * math.pi)) < gap_w

        def _place(rad_n, theta):
            ex = math.cos(theta) * rad_n * ax_r
            ey = math.sin(theta) * rad_n * ay_r
            dx = (ex * cca - ey * csa) * spread
            dy = (ex * csa + ey * cca) * spread
            return (wx + dx + bias_x * rad_n, wy + dy + bias_y * rad_n)

        # ── hard_bottom_edge: 主塊外周の一部 (弧・欠けあり) ──────────
        self._sl_base_shadow(surf, wx, wy, spread * 1.3, 15, a)
        ew, eh = int(spread * 1.2), int(spread * 0.78)
        edge_rect = (wx - ew, wy - eh // 2 + 5, ew * 2, eh)
        e0 = rng.uniform(0, math.pi)                        # 縁は一部だけ描く
        pygame.draw.arc(surf, (22, 32, 38, int(a * 0.5)), edge_rect,
                        e0, e0 + rng.uniform(2.6, 4.2), max(2, int(2.2 * sc)))
        pygame.draw.arc(surf, (64, 74, 76, int(a * 0.18)),
                        (edge_rect[0] + 3, edge_rect[1] + 2,
                         edge_rect[2] - 6, edge_rect[3] - 4),
                        e0 + 0.2, e0 + rng.uniform(2.2, 3.6), max(1, int(1.2 * sc)))

        # ── 1) core stones: 主塊 (2〜4個, やや大, 互いに接する/重なる) ─
        centers = []
        n_core = rng.randint(2, 4)
        core_r = spread * 0.22                              # 主塊は狭い範囲に密集
        for _i in range(n_core):
            ang = rng.uniform(0, 2 * math.pi)
            cx = wx + int(math.cos(ang) * core_r * rng.uniform(0.0, 1.0))
            cy = wy + int(math.sin(ang) * core_r * 0.6 * rng.uniform(0.0, 1.0))
            rr = (11 + rng.uniform(0, 7)) * sc
            centers.append([cx, cy, rr])

        # ── 2) side stones: 周辺の小岩 (中心密・外周疎, 抜けあり, 片寄り) ─
        n_side = max(3, min(7, int(3 + 4 * st.density)))
        for _i in range(n_side):
            theta = rng.uniform(0, 2 * math.pi)
            if _in_gap(theta):                             # 抜け側は置かない
                continue
            rad_n = 0.4 + 0.6 * (rng.random() ** 0.7)      # 外周ほど疎
            sx, sy = _place(rad_n, theta)
            rr = (5 + rng.uniform(0, 5)) * sc
            centers.append([int(sx), int(sy), rr])

        # ── crevice: 近接する岩ペアの間に暗い隙間を作る ─────────────
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                ax, ay, ar = centers[i]; bx, by, br = centers[j]
                d = math.hypot(ax - bx, ay - by)
                if d < (ar + br) * 0.95:
                    mx, my = (ax + bx) / 2, (ay + by) / 2
                    pygame.draw.circle(surf, (8, 12, 16, int(a * 0.7)),
                                       (int(mx), int(my)),
                                       max(2, int(min(ar, br) * 0.55)))

        # ── 岩本体: 奥(上) → 手前(下) の順。近いほど大きく暗め ────────
        y_lo = wy - spread * 0.5
        for rx, ry, rr in sorted(centers, key=lambda c: c[1]):
            if rr < 3:
                continue
            near = max(0.0, min(1.0, (ry - y_lo) / max(1.0, spread)))
            dk = int(18 * near)                     # 近いほど暗く
            base = (92 - dk, 96 - dk, 104 - dk + 6)  # わずかに青み
            # 角張った岩ポリゴン
            n = rng.randint(6, 8)
            a0 = rng.uniform(0, math.pi)
            pts = []
            for k in range(n):
                pa = a0 + 2 * math.pi * k / n
                rad = rr * rng.uniform(0.68, 1.15)
                pts.append((int(rx + math.cos(pa) * rad),
                            int(ry - math.sin(pa) * rad * 0.78)))
            # 下側/奥側の影 (岩の足元)
            pygame.draw.ellipse(surf, (26, 30, 40, int(a * 0.55)),
                                (int(rx - rr), int(ry + rr * 0.15),
                                 int(rr * 2), int(rr * 0.7)))
            pygame.draw.polygon(surf, (*base, a), pts)
            # 上面ハイライト (左上の面)
            hl = [(int(rx - rr * 0.15), int(ry - rr * 0.6)),
                  (int(rx + rr * 0.5), int(ry - rr * 0.35)),
                  (int(rx - rr * 0.55), int(ry - rr * 0.1))]
            pygame.draw.polygon(surf, (base[0] + 55, base[1] + 58, base[2] + 58,
                                       int(a * 0.6)), hl)
            # 下側の暗い面 (陰影)
            pygame.draw.polygon(surf, (34, 38, 50, int(a * 0.5)), [
                (int(rx - rr * 0.5), int(ry + rr * 0.05)),
                (int(rx + rr * 0.5), int(ry + rr * 0.05)),
                (int(rx), int(ry + rr * 0.55))])
            # 岩の縁の暗い割れ目 (rock_crevice のニュアンス)
            if rng.random() < 0.5:
                cvx = int(rx + rng.uniform(-0.4, 0.4) * rr)
                pygame.draw.line(surf, (12, 16, 22, int(a * 0.7)),
                                 (cvx, int(ry - rr * 0.4)),
                                 (cvx + int(rng.uniform(-3, 3) * sc), int(ry + rr * 0.3)),
                                 max(1, int(1.4 * sc)))

    def _sl_weed_bed(self, surf, wx, wy, sc, st, rng, a, suppress=1.0):
        # D-3.3: 旧グリッド層OFF後の量感を復活。広めに散る 3〜6個の小クラスター
        # の集合にし、各クラスタの本数/alphaを上げる。ただし均等配置には戻さず、
        # 中心密・外周疎・ところどころ抜けを維持する。
        spread = int(48 * sc)
        # D-3.5: 面積と密度をやや増やす。濃い塊(中心) + 薄い周縁の構成は維持。
        n_cl = max(4, int((4 + 4 * st.density) * (0.6 + 0.4 * suppress)))
        clus_ang = rng.uniform(-0.4, 0.4)                   # 群れ全体の傾き
        cca, csa = math.cos(clus_ang), math.sin(clus_ang)
        # 下地の薄い暗色帯 (端はにじんで終わる)
        pygame.draw.ellipse(surf, (12, 44, 28, int(min(95, a) * 0.9)),
                            (wx - spread, wy - 6, spread * 2, 14))
        w = max(1, int(1.6 * sc))
        for _cl in range(n_cl):
            if rng.random() < 0.12:                         # 意図的な抜け
                continue
            # サブクラスタ中心: 傾き楕円上・中心寄せ (rad**0.85 でやや広がる)
            rad = rng.random() ** 0.85
            cang = rng.uniform(0, 2 * math.pi)
            ex = math.cos(cang) * rad
            ey = math.sin(cang) * rad * 0.5
            ccx = wx + int((ex * cca - ey * csa) * spread)
            ccy = wy + int((ex * csa + ey * cca) * spread * 0.6)
            dens = rng.uniform(0.55, 1.0)                   # クラスタごとの濃淡
            blades = max(5, int(rng.randint(6, 11) * dens))
            cw = int(rng.uniform(7, 13) * sc)
            aa = int(a * (0.72 + 0.28 * dens))
            for _b in range(blades):
                t = rng.uniform(-1, 1); t = t * abs(t)      # 房内も中心密
                gx = ccx + int(t * cw)
                gy = ccy + rng.randint(-3, 3)               # 個別y (行感を壊す)
                gh = int((10 + rng.randint(0, 10)) * sc)
                r = rng.random()
                col = (40, 104, 50) if r < 0.4 else (
                       (56, 128, 62) if r < 0.75 else (80, 150, 74))
                pygame.draw.line(surf, (*col, aa),
                                 (gx, gy), (gx + rng.randint(-3, 3), gy - gh), w)

    def _sl_reed_bed(self, surf, wx, wy, sc, st, rng, a, suppress=1.0):
        # D-3.3: 岸際の葦群生として量感を強める。房を増やし、茎を太く/濃くし、
        # 房ごとに水際の暗い根元帯を足す。中心密・外周疎・ポケットは維持。
        spread = int(46 * sc)
        # D-3.5: 植生のみ量感アップ。房数を増やして群生感を強める (pocket/edge は残す)。
        n_clumps = max(5, min(9, int((5 + 4 * st.density) * (0.6 + 0.4 * suppress))))
        # 群生全体の下地 (薄い暗色帯)
        pygame.draw.ellipse(surf, (18, 48, 30, int(min(105, a) * 0.9)),
                            (wx - spread, wy - 3, spread * 2, 13))
        # ポケット(切れ目): 群生内の空きゾーンを 1〜2個。房中心がここに来たら間引く。
        pockets = [(rng.uniform(-0.7, 0.7), rng.uniform(-0.5, 0.5))
                   for _ in range(rng.randint(1, 2))]
        w = max(2, int(2.0 * sc))
        for _c in range(n_clumps):
            rad = rng.random() ** 0.5                 # 中心寄せ (外周は疎)
            cang = rng.uniform(0, 2 * math.pi)
            fx, fy = math.cos(cang) * rad, math.sin(cang) * rad
            if any((fx - px) ** 2 + (fy - py) ** 2 < 0.09 for px, py in pockets):
                continue                              # 切れ目を作る
            cx = wx + int(fx * spread)
            base_wy = wy + int(fy * spread * 0.35)    # 奥行き方向に少しずらす
            edge_fade = 1.0 - 0.4 * rad               # 外周は本数/濃度を落とす
            cw = int(rng.uniform(7, 13) * sc)
            base_h = rng.uniform(24, 46) * sc * (0.7 + 0.3 * (1.0 - rad))  # 中心=高い
            lean = rng.uniform(-0.18, 0.18)           # 房ごとの傾き癖
            blades = max(4, int(rng.uniform(7, 12) * (0.6 + 0.6 * st.density) * edge_fade))
            ca = int(a * (0.78 + 0.22 * (1.0 - rad)))  # 外周は薄い alpha
            # 房の水際の暗い根元帯 (葦が生える岸際の陰)
            pygame.draw.ellipse(surf, (14, 40, 26, int(ca * 0.7)),
                                (cx - cw, base_wy - 2, cw * 2, max(3, int(4 * sc))))
            for _b in range(blades):
                t = rng.uniform(-1, 1)
                t = t * abs(t)                        # 房内も中心密・外側疎
                gx = cx + int(t * cw)
                gy = base_wy + rng.randint(-2, 2)          # D-3.1: 個別yで行感を壊す
                gh = int(base_h * rng.uniform(0.7, 1.12))
                tip_dx = int((lean + rng.uniform(-0.12, 0.12)) * gh)
                rr = rng.random()
                if rr < 0.4:
                    col = (60, 96, 44, ca)            # 影側の暗い緑
                elif rr < 0.7:
                    col = (96, 132, 58, ca)           # 本体 黄緑〜オリーブ
                else:
                    col = (120, 150, 70, ca)          # 明るめ
                pygame.draw.line(surf, col, (gx, gy), (gx + tip_dx, gy - gh), w)
                if rng.random() < 0.3:               # 数本だけ穂先を明るく
                    pygame.draw.line(surf, (170, 155, 80, int(ca * 0.85)),
                                     (gx + tip_dx, gy - gh),
                                     (gx + tip_dx, gy - gh - int(5 * sc)),
                                     max(1, w - 1))

    def _sl_lily_pads(self, surf, wx, wy, sc, st, rng, a, suppress=1.0):
        # D-3.3: 水面カバーとしての量感を強める。葉数を増やし少し大きくする。
        #        pad_hole / pad_lane / 大小・欠け・外周散りは維持。
        spread = int(40 * sc)
        # D-3.5: 葉数を増やし水面カバー感を強める (pad_hole / lane は残す)。
        pads = max(8, int(max(9, min(18, int(10 + 8 * st.density))) * suppress))
        # 群生全体の薄い暗色 (水面シェード感)
        pygame.draw.ellipse(surf, (6, 26, 34, int(a * 0.32)),
                            (wx - spread, wy - int(spread * 0.4) + 3,
                             spread * 2, int(spread * 0.9)))
        # pad hole 中心 (葉のない穴 1〜2個)
        holes = [(rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5))
                 for _ in range(rng.randint(1, 2))]
        # lane: 群生を横切る細い空き筋 (法線方向に近い葉を除外)
        lane_ang = rng.uniform(0, math.pi)
        lane_nx, lane_ny = -math.sin(lane_ang), math.cos(lane_ang)
        placed, attempts = 0, 0
        while placed < pads and attempts < pads * 5:
            attempts += 1
            rad = rng.random() ** 0.6                   # 中心密・外周疎
            ang = rng.uniform(0, 2 * math.pi)
            fx, fy = math.cos(ang) * rad, math.sin(ang) * rad * 0.6
            # 穴付近には葉を置かない (穴の周りに葉が寄る)
            if any((fx - hx) ** 2 + (fy - hy) ** 2 < 0.045 for hx, hy in holes):
                continue
            # lane 上には葉を置かない (通せる筋)
            if abs(fx * lane_nx + fy * lane_ny) < 0.12:
                continue
            px = wx + int(fx * spread) + rng.randint(-2, 2)   # 外周ギザつき
            py = wy + int(fy * spread * 0.7)
            r = rng.random()                            # 大小 3クラス (幅を少し広げる)
            base = 5 if r < 0.30 else (9 if r < 0.75 else 13)
            pr = int(base * sc * rng.uniform(0.82, 1.22))
            if pr < 2:
                continue
            pw, ph = pr * 2, int(pr * rng.uniform(1.3, 1.7))  # 潰れた楕円
            # 葉下の薄い影
            pygame.draw.ellipse(surf, (6, 28, 36, int(a * 0.35)),
                                (px - pr + 1, py - ph // 2 + 2, pw, ph))
            # 葉本体 (緑〜黄緑 / 影葉 / たまに黄色い葉)
            if rng.random() < 0.18:
                col = (120, 150, 66, a)
            elif rng.random() < 0.4:
                col = (48, 96, 52, a)
            else:
                col = (66, 128, 70, a)
            pygame.draw.ellipse(surf, col, (px - pr, py - ph // 2, pw, ph))
            # V字切れ込み (大きめの葉に数枚だけ)
            if pr >= 6 and rng.random() < 0.5:
                pygame.draw.polygon(surf, (18, 52, 40, a), [
                    (px, py),
                    (px + int(pr * 0.5), py - ph // 2 - 1),
                    (px - int(pr * 0.5), py - ph // 2 - 1)])
            # 葉脈っぽい短線 (ごく少数)
            elif pr >= 7 and rng.random() < 0.35:
                pygame.draw.line(surf, (100, 150, 96, int(a * 0.6)),
                                 (px, py), (px, py - ph // 2), 1)
            placed += 1

    def _sl_stump_field(self, surf, wx, wy, sc, st, rng, a):
        count = max(2, min(6, int(2 + 4 * st.density)))
        spread = int(30 * sc)
        for _i in range(count):
            px = wx + rng.randint(-spread, spread)
            h = int((10 + rng.randint(0, 8)) * sc)
            w = max(3, int(6 * sc))
            pygame.draw.ellipse(surf, (8, 24, 42, int(a * 0.5)),
                                (px - w, wy - 3, w * 2, 8))
            pygame.draw.line(surf, (78, 56, 30, a), (px, wy), (px, wy - h), w)
            pygame.draw.ellipse(surf, (100, 74, 42, a),
                                (px - w // 2, wy - h - 2, w, 5))

    def _sl_brush_pile(self, surf, wx, wy, sc, st, rng, a):
        twigs = max(6, min(16, int(7 + 9 * st.density)))
        spread = int(26 * sc)
        self._sl_base_shadow(surf, wx, wy, spread, 12, a)
        for _i in range(twigs):
            x0 = wx + rng.randint(-spread // 2, spread // 2)
            y0 = wy - rng.randint(0, int(6 * sc))
            ln = int((14 + rng.randint(0, 16)) * sc)
            twang = math.radians(rng.uniform(20, 160))
            pygame.draw.line(surf, (72, 54, 32, int(a * 0.9)), (x0, y0),
                             (int(x0 + math.cos(twang) * ln),
                              int(y0 - math.sin(twang) * ln)),
                             max(1, int(1.4 * sc)))

    _STRUCT_DBG_LABEL = {
        "stake_cluster": "stake", "laydown": "laydown", "weed_bed": "weed",
        "reed_bed": "reed", "lily_pads": "lily", "rock_pile": "rock",
        "stump_field": "stump", "brush_pile": "brush",
    }

    # D-3.2: 各タイプの概算 描画半径 (sc=1.0 基準)。bbox デバッグ表示用。
    _STRUCT_DBG_HALF = {
        "stake_cluster": 24, "laydown": 62, "weed_bed": 30,
        "reed_bed": 44, "lily_pads": 38, "rock_pile": 34,
        "stump_field": 30, "brush_pile": 26,
    }

    def _draw_structure_debug(self, surface: pygame.Surface) -> None:
        """F2デバッグ: StructureObject 中心にマーカー + type/variant/hotspot を表示。

        D-2.5 診断: stake_cluster は variant (reed_fence / old_pier_remnant) を、
        構造物ごとに近傍の hotspot 種別 (reed_gap / pad_lane 等) を並べて描く。
        """
        tr = self.terrain
        vw = max(0.1, tr.view_width_m)
        vd = max(0.1, tr.view_depth_m)
        water_h = WATER_NEAR_Y - WATER_Y0
        # variant 判定用の reed world 中心 (blit と同じ計算)
        reed_centers = [
            (int((float(getattr(s, "x", 0.0)) / vw) * WORLD_W),
             int(WATER_Y0 + max(0.0, min(1.0, float(getattr(s, "y", 0.0)) / vd)) * water_h))
            for s in tr.structures if getattr(s, "type", None) == "reed_bed"
        ]
        for st in tr.structures:
            wx_full = int((st.x / vw) * WORLD_W)
            sx = wx_full - int(self.cam_x)
            wy_full = int(WATER_Y0 + max(0.0, min(1.0, st.y / vd)) * water_h)
            sy = wy_full
            if not (-20 <= sx <= MAIN_W + 20):
                continue
            # D-3.2: 描画範囲 bbox (新レイヤーが実際にどこを占めているか確認用)
            depth_t = max(0.0, min(1.0, st.y / vd))
            sc = (st.scale * self._TIER_MULT_D.get(st.tier, 1.0)
                  * (0.75 + 0.65 * depth_t) * STRUCT_VISUAL_SCALE)
            half = int(self._STRUCT_DBG_HALF.get(st.type, 30) * sc)
            pygame.draw.rect(surface, (80, 230, 255),
                             (sx - half, sy - int(half * 1.1), half * 2, int(half * 1.4)), 1)
            pygame.draw.circle(surface, (255, 60, 200), (sx, sy), 4)
            pygame.draw.circle(surface, (255, 255, 255), (sx, sy), 4, 1)
            if self.font_sm is None:
                continue
            rows = [f"{self._STRUCT_DBG_LABEL.get(st.type, st.type)}·{st.tier}"
                    f" x={st.x:.1f} y={st.y:.1f}"]
            if st.type == "stake_cluster":
                rows.append(self._stake_variant(st, wx_full, wy_full, reed_centers))
            # この構造物由来の hotspot 種別を列挙 (source == st.type で近いもの)
            col_c = int(st.x / vw * tr.grid_cols)
            row_c = int(st.y / vd * tr.grid_rows)
            kinds = []
            for hs in getattr(tr, "hotspots", []) or []:
                if hs.get("source") != st.type:
                    continue
                hc = hs["x"] / vw * tr.grid_cols
                hr = hs["y"] / vd * tr.grid_rows
                if ((hc - col_c) ** 2 + (hr - row_c) ** 2) ** 0.5 <= 6.0:
                    kinds.append(hs["kind"])
            rows.extend(kinds[:4])
            for j, rtxt in enumerate(rows):
                surface.blit(self.font_sm.render(rtxt, True, (255, 200, 240)),
                             (sx + 6, sy - 8 + j * 15))

    def _spawn_fish(self, rng: random.Random) -> list:
        """スポーン: <40cm は群集管理 (ランダム)、≥40cm は個体管理。"""
        best    = self.uw_map.best_positions(10)
        act_mod = self._env.activity_modifier if self._env else 1.0
        fishes  = []

        # ── 小型魚: 群集管理 (<40 cm) ────────────────────────────────
        for i, sz in enumerate([22.0, 25.0, 27.0, 30.0, 32.0, 35.0, 38.0]):
            pos = best[i % len(best)]
            fx  = max(1.0, min(float(UW_W - 2), pos[0] + rng.uniform(-2, 2)))
            fy  = max(1.0, min(float(UW_H - 2), pos[1] + rng.uniform(-2, 2)))
            fish = Fish(fx, fy, sz, self.uw_map, rng)
            fish.activity = max(0.20, min(1.0, fish.activity * act_mod))
            fishes.append(fish)

        # ── 大型魚: 個体管理 (≥40 cm) ────────────────────────────────
        if self._population:
            self._population.initialize_spot(self.spot_name)
            individuals = self._population.get_spot_individuals(self.spot_name)
            for j, fi in enumerate(individuals):
                pos = best[(3 + j) % len(best)]   # 小型魚ポジションとずらす
                fx  = max(1.0, min(float(UW_W - 2), pos[0] + rng.uniform(-3, 3)))
                fy  = max(1.0, min(float(UW_H - 2), pos[1] + rng.uniform(-3, 3)))
                fish = Fish(fx, fy, fi.length, self.uw_map, rng)
                # aggression を activity ベースに使用; caution は spook 感度に反映済
                fish.activity = max(0.20, min(1.0, fi.aggression * act_mod))
                fish.fish_id  = fi.fish_id   # 個体ID紐付け
                fishes.append(fish)
        else:
            # フォールバック: population 未接続時は固定サイズで生成
            for i, sz in enumerate([40.0, 43.0, 45.0, 48.0]):
                pos = best[(3 + i) % len(best)]
                fx  = max(1.0, min(float(UW_W - 2), pos[0] + rng.uniform(-2, 2)))
                fy  = max(1.0, min(float(UW_H - 2), pos[1] + rng.uniform(-2, 2)))
                fish = Fish(fx, fy, sz, self.uw_map, rng)
                fish.activity = max(0.20, min(1.0, fish.activity * act_mod))
                fishes.append(fish)

        # ── Beta v0.9: F4 テストモード — 高活性の50UPを追加スポーン ──
        # fish_id なし = 個体管理外。学習・永続化に影響しない使い捨てテスト魚。
        if self._test_big_fish:
            for k, (sz, act) in enumerate(TU.TEST_BIG_FISH):
                pos = best[k % len(best)]
                fx  = max(1.0, min(float(UW_W - 2), pos[0] + rng.uniform(-1.5, 1.5)))
                fy  = max(1.0, min(float(UW_H - 2), pos[1] + rng.uniform(-1.5, 1.5)))
                fish = Fish(fx, fy, sz, self.uw_map, rng)
                fish.activity = act
                fishes.append(fish)

        return fishes

    # ── Lure switching ────────────────────────────────────────────────

    def _switch_lure(self, idx: int) -> None:
        """Switch to lure at *idx*.  Resets lure if currently in water."""
        if idx == self._lure_idx:
            return
        self._lure_idx = idx
        spec = get_spec_by_idx(idx)
        # Preserve in_water=False; if lure was in water, retract it
        self.lure.reset()
        self.lure.lure_type = spec.name
        if self.state == FS_RETRIEVE:
            self.state = FS_IDLE
            self._intended_pos = None
            self._bite_charge  = 0.0

    # ── Events ─────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> Optional[str]:
        # ── マウス押下 ────────────────────────────────────────────────
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.state == FS_IDLE:
                # キャスト溜め開始 (狙い点は十字キーで動かしたキャストカーソル)
                iux = int(round(self.cast_cursor_x))
                iuy = int(round(self.cast_cursor_y))
                self._cast_aim    = (iux, iuy)
                self._cast_charge = 0.0
                self._cast_dir    = 1
                self.state = FS_CAST_CHARGE
            elif self.state == FS_RETRIEVE:
                # リール: 押下開始記録 + 連打検出
                self._reel_press_frame = self._frame_count
                self._reel_clicks.append(self._frame_count)
                self._reel_clicks = [
                    f for f in self._reel_clicks
                    if self._frame_count - f <= REEL_FAST_WINDOW
                ]
                if len(self._reel_clicks) >= REEL_FAST_CLICKS:
                    self._fast_frames = REEL_FAST_FRAMES
                self.rod.notify_reel()

        # ── マウスリリース ────────────────────────────────────────────
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.state == FS_CAST_CHARGE:
                self._release_cast()
            elif self.state == FS_RETRIEVE:
                # 短押し → チョイ巻き
                if (self._reel_press_frame >= 0
                        and self._frame_count - self._reel_press_frame
                        <= REEL_TAP_FRAMES):
                    self._creep_frames = REEL_CREEP_FRAMES
                self._reel_press_frame = -1

        # ── キー入力 ──────────────────────────────────────────────────
        if event.type == pygame.KEYDOWN:
            if (self.state in (FS_BITE, FS_WEIGHT, FS_LINE_RUN)
                    and event.key in (pygame.K_DOWN, pygame.K_SPACE)):
                # ↓ = フッキング (SPACE は補助として残す)
                self._attempt_hookset()
            elif event.key == pygame.K_k and self.state == FS_KEEP_RELEASE:
                self._keep_fish()
            elif event.key == pygame.K_r and self.state == FS_KEEP_RELEASE:
                self._release_fish()
            elif event.key == pygame.K_F2:
                # 水中デバッグ表示トグル (旧 D キー; A/D 足場移動と衝突のため移設)
                self.debug_mode = not self.debug_mode
            elif event.key == pygame.K_ESCAPE:
                if self.state == FS_FIGHT:
                    # ファイト中のESC = ギブアップ (バラシ扱い)
                    self._lose_fight(OUTCOME_HOOKOUT, give_up=True)
                    return None
                self.rod.reset()   # 釣りビューを抜ける時: ロッドを中立へ戻す
                return "exit_fishing"
            elif self.state in (FS_IDLE, FS_RETRIEVE):
                # Keys 1-6: switch lure type (溜め/バイト/ファイト中は不可)
                lure_key_map = {
                    pygame.K_1: 0,
                    pygame.K_2: 1,
                    pygame.K_3: 2,
                    pygame.K_4: 3,
                    pygame.K_5: 4,
                    pygame.K_6: 5,
                }
                if event.key in lure_key_map:
                    self._switch_lure(lure_key_map[event.key])

        return None

    # ── Update ─────────────────────────────────────────────────────────

    # ── V5: 軽量水面パーティクル ──────────────────────────────────────

    _PARTICLE_CAP = 60   # 同時上限 (60FPS維持のため少なめ)

    def _spawn_ripple(self, sx: int, sy: int, rings: int = 2) -> None:
        """着水/重み乗り: 同心円が広がる波紋。"""
        for k in range(rings):
            if len(self._particles) >= self._PARTICLE_CAP:
                break
            self._particles.append({
                "kind": "ripple", "x": sx, "y": sy,
                "life": 0, "max": 26 + k * 6, "delay": k * 6,
            })

    def _spawn_splash(self, sx: int, sy: int, n: int = 8,
                      power: float = 1.0) -> None:
        """トップバイト/フッキング: 上方向へ飛ぶ水しぶき (重力で落ちる)。"""
        for _ in range(n):
            if len(self._particles) >= self._PARTICLE_CAP:
                break
            ang = random.uniform(-2.5, -0.65)   # 主に上向き
            spd = random.uniform(2.2, 5.0) * power
            self._particles.append({
                "kind": "drop", "x": float(sx), "y": float(sy),
                "vx": math.cos(ang) * spd, "vy": math.sin(ang) * spd,
                "life": 0, "max": random.randint(16, 30),
                "r": random.randint(2, 3),
            })
        self._spawn_ripple(sx, sy, rings=1)

    def _update_particles(self) -> None:
        alive = []
        for p in self._particles:
            p["life"] += 1
            if p["life"] >= p["max"]:
                continue
            if p["kind"] == "drop":
                p["x"] += p["vx"]
                p["y"] += p["vy"]
                p["vy"] += 0.45   # 重力
            alive.append(p)
        self._particles = alive

    def _draw_particles(self, surface: pygame.Surface) -> None:
        if not self._particles:
            return
        ov = pygame.Surface((MAIN_W, SCREEN_H), pygame.SRCALPHA)
        for p in self._particles:
            if p["life"] < p.get("delay", 0):
                continue
            prog = p["life"] / p["max"]
            a = int(220 * (1.0 - prog))
            if p["kind"] == "ripple":
                r = int(4 + prog * 26)
                pygame.draw.circle(ov, (220, 235, 255, max(0, a)),
                                   (int(p["x"]), int(p["y"])), r, 2)
            else:  # drop
                pygame.draw.circle(ov, (235, 245, 255, max(0, a)),
                                   (int(p["x"]), int(p["y"])), p["r"])
        surface.blit(ov, (0, 0))

    def update(self) -> None:
        self._frame_count += 1
        self._update_camera()
        self._update_particles()
        if self._splash_timer > 0:
            self._splash_timer -= 1
        if self._intended_timer > 0:
            self._intended_timer -= 1
        if self._cast_quality_timer > 0:
            self._cast_quality_timer -= 1
        # ファイトイベントフラッシュのタイマー
        self._fight_events = [
            (msg, t - 1) for msg, t in self._fight_events if t > 1
        ]

        if self.state == FS_CAST_CHARGE:
            # キャストゲージ: 0→100→0 を往復 (ピンポン式、自動リリースなし)
            self._cast_charge += CAST_CHARGE_RATE * self._cast_dir
            if self._cast_charge >= CAST_CHARGE_MAX:
                self._cast_charge = CAST_CHARGE_MAX
                self._cast_dir = -1
            elif self._cast_charge <= 0.0:
                self._cast_charge = 0.0
                self._cast_dir = 1
            for fish in self.fishes:
                if fish.state not in (FISH_CAUGHT, REACT_BITE):
                    fish.update(None)

        elif self.state == FS_CASTING:
            self._update_casting()

        elif self.state == FS_RETRIEVE:
            self._update_retrieve()

        elif self.state == FS_BITE:
            self._update_bite()

        elif self.state in (FS_WEIGHT, FS_LINE_RUN):
            self._update_worm_bite()

        elif self.state == FS_FIGHT:
            self._update_fight()

        elif self.state == FS_KEEP_RELEASE:
            # Phase 10: waiting for K/R key — non-caught fish keep patrolling
            for fish in self.fishes:
                if fish.state not in (FISH_CAUGHT, REACT_BITE):
                    fish.update(None)

        elif self.state == FS_RESULT:
            self._result_timer -= 1
            if self._result_timer <= 0:
                # Fish handling already done in _keep_fish() / _release_fish()
                self._result_fish = None
                self.rod.reset()   # FS_IDLE復帰時: 前回ファイトのロッド角を確実に消す
                self.state        = FS_IDLE
                self._bite_charge = 0.0

        else:  # FS_IDLE
            self._update_idle()

    def _update_idle(self) -> None:
        """キャスト前: A/D=足場移動, 十字キー=キャストカーソル移動。"""
        keys = pygame.key.get_pressed()

        # ── 足場移動 (A/D)。キャスト前のみ。立ち位置でアプローチ角が決まる ──
        move = (1 if keys[pygame.K_d] else 0) - (1 if keys[pygame.K_a] else 0)
        if move != 0:
            old_stance_x = self.player_stance_x
            self.player_stance_x = max(
                TU.STANCE_MIN,
                min(TU.STANCE_MAX,
                    self.player_stance_x + move * TU.STANCE_MOVE_SPEED))
            # キャストカーソルを立ち位置と連動させる (見失い防止)
            actual_dx = self.player_stance_x - old_stance_x
            self.cast_cursor_x = max(0.0, min(float(UW_W - 1),
                self.cast_cursor_x + actual_dx * (UW_W - 1)))

        # ── キャストカーソル移動 (十字キー) ──
        cdx = (1 if keys[pygame.K_RIGHT] else 0) - (1 if keys[pygame.K_LEFT] else 0)
        cdy = (1 if keys[pygame.K_DOWN] else 0) - (1 if keys[pygame.K_UP] else 0)
        if cdx or cdy:
            self.cast_cursor_x = max(0.0, min(float(UW_W - 1),
                self.cast_cursor_x + cdx * TU.CAST_CURSOR_SPEED))
            self.cast_cursor_y = max(0.0, min(float(UW_H - 1),
                self.cast_cursor_y + cdy * TU.CAST_CURSOR_SPEED))

        for fish in self.fishes:
            if fish.state not in (FISH_CAUGHT, REACT_BITE):
                fish.update(None)

    def _lure_match(self) -> float:
        """Return match score [0.10, 1.00] for current lure vs environment/terrain.

        Used as a bite-charge multiplier and displayed in the HUD.
        """
        spec = get_spec_by_idx(self._lure_idx)
        score = 0.50  # neutral baseline

        # ── Action bonus ──────────────────────────────────────────────
        if self.lure.in_water and self.lure.action in spec.best_actions:
            score += 0.15

        # ── Environment conditions ────────────────────────────────────
        if self._env:
            gm = self._env._last_game_minutes
            if gm >= 0:
                hour = (gm % 1440) // 60
            else:
                hour = 6  # default morning if env not yet ticked
            weather    = self._env.weather
            wind_speed = self._env.wind_speed
            act_mod    = self._env.activity_modifier

            for cond in spec.best_conditions:
                if   cond == "morning"      and 4  <= hour < 8:          score += 0.12
                elif cond == "evening"      and 17 <= hour < 21:         score += 0.12
                elif cond == "cloudy"       and weather == "Cloudy":     score += 0.10
                elif cond == "rain"         and weather in ("Rain", "Heavy Rain"): score += 0.10
                elif cond == "clear"        and weather == "Sunny":      score += 0.08
                elif cond == "wind"         and wind_speed > 4.0:        score += 0.12
                elif cond == "low_activity" and act_mod < 0.65:          score += 0.15
                elif cond == "pressure":
                    if self.lure.in_water:
                        lx = int(self.lure.x); ly = int(self.lure.y)
                        if 0 <= lx < UW_W and 0 <= ly < UW_H:
                            if self._pressure[ly][lx] >= 5:
                                score += 0.12

        # ── Terrain match ─────────────────────────────────────────────
        if self.lure.in_water:
            lx = int(self.lure.x); ly = int(self.lure.y)
            if 0 <= lx < UW_W and 0 <= ly < UW_H:
                cell = self.uw_map.cell(lx, ly)
                for terrain in spec.best_terrain:
                    if   terrain == "weed"    and cell.weed:                          score += 0.10
                    elif terrain == "cover"   and cell.cover:                         score += 0.10
                    elif terrain == "break"   and cell.terrain == TERRAIN_BREAK:      score += 0.10
                    elif terrain == "rock"    and cell.terrain == TERRAIN_ROCK:       score += 0.10
                    elif terrain == "shallow" and cell.depth < 1.0:                   score += 0.08

        return round(min(1.00, max(0.10, score)), 2)

    def _update_retrieve(self) -> None:
        """Per-frame logic when lure is in water."""
        # ── Beta v0.9: 十字キー=ロッド / マウス=リール ────────────────
        keys  = pygame.key.get_pressed()
        mouse = pygame.mouse.get_pressed()
        self.rod.update(keys)
        if self._creep_frames > 0:
            self._creep_frames -= 1
        if self._fast_frames > 0:
            self._fast_frames -= 1

        action, mult = self._determine_action(mouse)
        self.lure.retrieve_mult = mult
        self.lure.steer_x = self.rod.steer_x
        # リトリーブは立ち位置基準の自然なラインへ寄せる (急吸収しない)
        self.lure.retrieve_target_x = self._retrieve_target_cell_x()
        self.lure.set_action(action)
        reached = self.lure.update()
        if reached:
            self.state       = FS_IDLE
            self._intended_pos = None
            self._bite_charge = 0.0
            return

        # ── Pressure tracking ──
        lx, ly = int(self.lure.x), int(self.lure.y)
        if 0 <= lx < UW_W and 0 <= ly < UW_H:
            if self._frame_count % 18 == 0:
                self._pressure[ly][lx] = min(15, self._pressure[ly][lx] + 1)

        # ── Fish AI ──
        lure_score   = self._lure_spot_score()
        any_in_range = False
        in_range_fish = None

        # Phase 9: APPROACH → SPOOK 学習検出のため更新前の状態を記録
        prev_states = {
            id(f): f.state
            for f in self.fishes
            if f.fish_id and f.state not in (FISH_CAUGHT, REACT_BITE)
        }

        for fish in self.fishes:
            if fish.state in (FISH_CAUGHT, REACT_BITE):
                continue
            visible = self._visible_lure_for(fish, lure_score)
            fx, fy  = int(fish.x), int(fish.y)
            pressure = (
                self._pressure[fy][fx]
                if 0 <= fx < UW_W and 0 <= fy < UW_H
                else 0
            )
            result = fish.update(visible, cell_pressure=pressure)
            if result == "in_range":
                any_in_range = True
                if in_range_fish is None:
                    in_range_fish = fish

        # Phase 9: 見切り (APPROACH → SPOOK) 学習
        for fish in self.fishes:
            if not fish.fish_id:
                continue
            prev = prev_states.get(id(fish))
            if prev == REACT_APPROACH and fish.state == REACT_SPOOK:
                fi = self._get_individual(fish)
                if fi:
                    fi.learn(
                        "spook",
                        self._current_lure_category(),
                        self._current_game_day(),
                    )

        # ── イベント駆動バイト ──
        # 魚が射程内に「いるだけ」では食わない。実釣的な「触る/吸う/弾く」瞬間
        # (停止・フォール開始・ロッドアクション直後・ストラクチャ通過・追いついた瞬間)
        # に bite_check を走らせる。近接ゲージは弱い保険に降格。
        if self._bite_event_cd > 0:
            self._bite_event_cd -= 1

        if any_in_range:
            act_mod   = self._env.activity_modifier if self._env else 1.0
            lure_mod  = self._lure_match()
            mem_mod   = self._memory_modifier_for(in_range_fish) if in_range_fish else 1.0
            cast_mod  = (
                TU.CAST_PERFECT_BIG_FISH_MULT
                if (self._cast_quality == CAST_PERFECT
                    and in_range_fish and in_range_fish.size >= 40.0)
                else 1.0
            )
            # Beta v0.96: スラック適合度。適正スラックで使えているほど食う。
            # → worm/jig はフォール(スラック)で、hard_bait は張りで最大化する。
            slack_mod = self._slack_modifier()
            modifier = act_mod * lure_mod * mem_mod * cast_mod * slack_mod

            # ── トリガーイベント検出 ──
            event = None
            if self.lure.action_changed:
                if self.lure.action == ACTION_STOP:
                    event = "stop"
                elif self.lure.action == ACTION_FALL:
                    event = "fall"
                elif self.lure.action in (ACTION_TWITCH, ACTION_LIFT):
                    event = "rod"
            if event is None:
                # ストラクチャ通過直後 (新しいセルに入り、そこが地形)
                if (lx, ly) != self._prev_lure_cell and 0 <= lx < UW_W and 0 <= ly < UW_H:
                    cell = self.uw_map.cell(lx, ly)
                    if cell.weed or cell.cover or cell.terrain in (
                            TERRAIN_ROCK, TERRAIN_BREAK):
                        event = "structure"
            if event is None and not self._was_in_range:
                # 魚がルアーに追いついた瞬間 (リアクションバイト)
                event = "reach"

            # ── bite_check (イベント時に1回だけ確率判定) ──
            if event is not None and self._bite_event_cd <= 0:
                w = TU.BITE_EVENT_WEIGHTS.get(event, 1.0)
                prob = min(0.95, TU.BITE_EVENT_BASE_P * w * modifier)
                self._bite_event_cd = TU.BITE_EVENT_COOLDOWN
                if random.random() < prob:
                    self._trigger_bite()
                    self._prev_lure_cell = (lx, ly)
                    self._was_in_range = True
                    return

            # 弱い近接ゲージ (保険): 何もイベントが無くてもごく稀に食う
            base_rate = _CHARGE_RATE.get(self.lure.action, 0.005)
            self._bite_charge = min(
                1.0,
                self._bite_charge
                + base_rate * modifier * TU.BITE_PASSIVE_SCALE,
            )
            if self._bite_charge >= BITE_TRIGGER:
                self._trigger_bite()
        else:
            self._bite_charge = max(0.0, self._bite_charge - TU.BITE_CHARGE_DECAY)

        self._prev_lure_cell = (lx, ly)
        self._was_in_range = any_in_range

    def _determine_action(self, mouse) -> Tuple[str, float]:
        """Beta v0.9: (action, retrieve_mult) を返す。

        リール (マウス):
          長押し       → 通常巻き (×1.0)
          短押しタップ → チョイ巻き (×0.45)
          連打         → 早巻き (×1.8)
        ロッド (十字キー):
          ↓短押し=トゥイッチ  ↓長押し=リフト  ↑=フォール
          中立 (操作直後) = ストップ
        """
        # リール長押し (タップ猶予より長く押している)
        reel_hold = (
            mouse[0]
            and self._reel_press_frame >= 0
            and self._frame_count - self._reel_press_frame > REEL_TAP_FRAMES
        )
        if reel_hold:
            self.rod.notify_reel()
            mult = TU.REEL_FAST_MULT if self._fast_frames > 0 else 1.0
            return ACTION_RETRIEVE, mult
        if self._creep_frames > 0:
            return ACTION_RETRIEVE, TU.REEL_CREEP_MULT
        return self.rod.lure_action(), 1.0

    # ── Beta v0.9: Cast release ───────────────────────────────────────

    def _judge_cast(self) -> str:
        # ピンポン式: 値のみで判定 (LATE はゲージ上限廃止に伴い発生しない)
        c = self._cast_charge
        if CAST_PERFECT_LO <= c <= CAST_PERFECT_HI:
            return CAST_PERFECT
        if c >= CAST_GOOD_LO:
            return CAST_GOOD
        return CAST_EARLY

    def _release_cast(self) -> None:
        """LMBリリース: ゲージ判定 → 着水点決定 → キャスト。"""
        if self._cast_aim is None:
            self.state = FS_IDLE
            return
        quality = self._judge_cast()
        iux, iuy = self._cast_aim

        # 着水点 = 狙い点 + 品質補正
        ax, ay = float(iux), float(iuy)
        if quality == CAST_EARLY:
            # ショートキャスト: ゲージ不足分だけプレイヤー側 (y+) へずれる
            shortfall = (CAST_GOOD_LO - self._cast_charge) / CAST_GOOD_LO
            ay += (float(UW_H - 1) - ay) * min(
                TU.CAST_EARLY_SHORTFALL_CAP,
                shortfall * TU.CAST_EARLY_SHORTFALL_FACTOR,
            )
        elif quality == CAST_LATE:
            # オーバーキャスト: 対岸側 (y-) へずれる
            ay -= random.uniform(*TU.CAST_LATE_OVERSHOOT)

        sigma, clamp = _CAST_DEVIATION[quality]
        dx = min(clamp, max(-clamp, random.gauss(0, sigma)))
        dy = min(clamp, max(-clamp, random.gauss(0, sigma)))
        fx = max(0, min(UW_W - 1, int(round(ax + dx))))
        fy = max(0, min(UW_H - 1, int(round(ay + dy))))

        self._intended_pos    = (iux, iuy)
        self._intended_timer  = INTENDED_FRAMES
        self._cast_quality    = quality
        self._cast_quality_timer = 90
        self._cast_aim        = None
        self.rod.reset()
        self._bite_charge   = 0.0

        # ── キャスト飛行演出を開始 (FS_CASTING) ──────────────────────
        # 着水点へ即出現させず、手元(ロッドティップ付近)から放物線で飛ばす。
        # ルアーはまだ in_water=False。飛行完了時に lure.cast(fx,fy) を呼ぶ。
        tip = self.rod.tip_pos(self.rod_anchor, length=TU.ROD_VISUAL_LENGTH)
        tgt = self._uw_to_screen(fx, fy)
        self._cast_flight_start  = (float(tip[0]), float(tip[1]))
        self._cast_flight_target = (float(tgt[0]), float(tgt[1]))
        self._cast_flight_cell   = (int(fx), int(fy))
        dist_px = math.hypot(tgt[0] - tip[0], tgt[1] - tip[1])
        # 飛行時間: 距離に応じて 20〜45 frame
        self._cast_flight_duration = int(max(20, min(45, 20 + dist_px * 0.045)))
        self._cast_flight_timer = 0
        # 放物線の高さ: 遠投ほど高く弧を描く
        self._cast_arc_height = min(170.0, 60.0 + dist_px * 0.30)
        self._cast_flight_trail = []
        self.state = FS_CASTING

    # ── v0.95: Cast flight (ルアーが飛んでいく演出) ──────────────────

    def _cast_flight_pos(self, t: float) -> Tuple[float, float]:
        """飛行進捗 t(0..1) における画面座標 (放物線)。"""
        sx, sy = self._cast_flight_start
        tx, ty = self._cast_flight_target
        x = sx + (tx - sx) * t
        y = sy + (ty - sy) * t
        # 上方向の弧 (sin で離陸→着水)
        y -= self._cast_arc_height * math.sin(math.pi * t)
        return (x, y)

    def _update_casting(self) -> None:
        """ルアー飛行中: 着水点へ放物線で飛び、完了で FS_RETRIEVE へ。"""
        self._cast_flight_timer += 1
        t = min(1.0, self._cast_flight_timer / max(1, self._cast_flight_duration))
        # 軌跡 (薄いライン用)。直近のみ保持
        self._cast_flight_trail.append(self._cast_flight_pos(t))
        if len(self._cast_flight_trail) > 12:
            self._cast_flight_trail.pop(0)

        # 飛行中も魚はパトロール (まだルアーは水中にない)
        for fish in self.fishes:
            if fish.state not in (FISH_CAUGHT, REACT_BITE):
                fish.update(None)

        if t >= 1.0:
            # 着水: ここで初めてルアーを水中へ
            fx, fy = self._cast_flight_cell
            self.lure.cast(fx, fy)
            self._splash_timer = 24
            csx, csy = self._uw_to_screen(fx, fy)
            self._spawn_ripple(csx, csy, rings=2)
            # イベント駆動バイトのトラッキングをリセット
            self._prev_lure_cell = (int(fx), int(fy))
            self._was_in_range   = False
            self._bite_event_cd  = 0
            self._cast_flight_trail = []
            self.state = FS_RETRIEVE

    # ── Bite / hookset / miss ─────────────────────────────────────────

    def _update_bite(self) -> None:
        """巻物/その他: BITE 中の経過とタイムアウト判定。"""
        self._bite_elapsed += 1
        for fish in self.fishes:
            if fish.state not in (FISH_CAUGHT, REACT_BITE):
                fish.update(self.lure)
        # モード別タイムアウト
        if self._bite_mode == HOOKSET_VISUAL_DELAY:
            if self._bite_elapsed > self._weight_on_frame + TU.TOPWATER_TIMEOUT_AFTER:
                self._miss_bite()
        elif self._bite_elapsed > _BITE_TIMEOUT.get(self._bite_mode, BITE_FRAMES):
            self._miss_bite()

    def _update_worm_bite(self) -> None:
        """Hooking v1: ワーム系 WEIGHT → LINE_RUN 工程の進行。

        WEIGHT  : 重みが乗る (ティップが少し入る / ラインが張る)。
        LINE_RUN: 魚が走り出し、魚+ルアーが沖へ動く (ライン角度が変化)。
        どちらの状態でも↓入力で HOOK でき、品質は _bite_elapsed で判定する。
        """
        self._bite_elapsed += 1
        for fish in self.fishes:
            if fish.state not in (FISH_CAUGHT, REACT_BITE):
                fish.update(self.lure)

        if self.state == FS_WEIGHT:
            # ラインが張る: スラックが抜けていき、ティップに重みが乗る
            self.lure.slack = max(0.0, self.lure.slack - 0.05)
            # 重みが乗りきると魚が走り出す → LINE_RUN へ
            if self._bite_elapsed >= TU.WORM_WEIGHT_TO_RUN:
                self.state = FS_LINE_RUN
                self.lure.slack = 0.0
        else:  # FS_LINE_RUN: 魚+ルアーを走らせてライン角度を変える
            self._advance_line_run()

        # ワーム系は DELAY のタイムアウトで見切られる
        if self._bite_elapsed > _BITE_TIMEOUT.get(self._bite_mode, BITE_FRAMES):
            self._miss_bite()

    def _advance_line_run(self) -> None:
        """LINE_RUN中: バイト魚とルアーを走行方向へ動かす (ライン角度が変化する)。"""
        dx, dy = self._line_run_dir
        spd = TU.WORM_LINE_RUN_SPEED
        if self._bite_fish is not None:
            self._bite_fish.x = max(0.0, min(float(UW_W - 1),
                                             self._bite_fish.x + dx * spd))
            self._bite_fish.y = max(0.0, min(float(UW_H - 1),
                                             self._bite_fish.y + dy * spd))
            # ルアーは魚に咥えられたまま追従 → ティップ→ルアーのラインが魚方向へ走る
            self.lure.x = self._bite_fish.x
            self.lure.y = self._bite_fish.y

    def _trigger_bite(self) -> None:
        """バイト発生: ルアー別フッキング方式に応じて分岐。"""
        biting = min(
            (f for f in self.fishes if f.state == REACT_CHASE),
            key=lambda f: (f.x - self.lure.x)**2 + (f.y - self.lure.y)**2,
            default=None,
        )
        if not biting:
            return

        biting.trigger_bite()
        self._bite_fish = biting
        self._bite_charge = 0.0
        # Beta v0.96: バイト成立時のスラックを記録 → フッキング品質(hook_hold)に反映。
        # 適正スラックで掛ければテンション伝達が良く、保持率が高い。
        self._bite_slack = self.lure.slack_m
        self._bite_slack_mod = self._slack_modifier()
        # ルアーは水中に残す: ラインが張られたままティップが引き込まれる
        # (リトリーブ→バイトをシームレスに見せる)
        self._intended_pos = None

        spec = get_spec_by_idx(self._lure_idx)
        self._bite_mode = _HOOKSET_MODE.get(spec.name, HOOKSET_DELAY)
        self._bite_type = _BITE_TYPE.get(spec.name, BITE_MEDIUM_TICK)
        self._bite_elapsed = 0

        # 自動フッキングは廃止: どのルアーも↓入力で合わせなければ釣れない
        bsx, bsy = self._uw_to_screen(biting.x, biting.y)
        if self._bite_mode == HOOKSET_VISUAL_DELAY:
            # バシャ! → 重みが乗るまで待つ。トップは派手なスプラッシュ
            self._weight_on_frame = random.randint(*TU.TOPWATER_WEIGHT_ON_RANGE)
            self._spawn_splash(bsx, bsy, n=12, power=1.3)
        else:
            # 水中バイト: 控えめな波紋
            self._spawn_ripple(bsx, bsy, rings=1)

        # Hooking v1: ワーム系 (DELAYフッキング) は BITE→WEIGHT→LINE_RUN→HOOK。
        # 巻物/その他は従来通り BITE→HOOK。
        if self._bite_mode == HOOKSET_DELAY:
            # 走る方向: アンカー(立ち位置)から沖へ + 開けた側へ少し横走り
            ax = self.player_stance_x * (UW_W - 1)
            side = -1.0 if biting.x < ax else 1.0
            self._line_run_dir = (side * 0.55, -0.83)   # 沖向き(手前→奥) 主体
            self.state = FS_WEIGHT
        else:
            self.state = FS_BITE

    def _hookset_quality(self) -> Optional[str]:
        """↓入力タイミングからフック品質を返す (None = すっぽ抜け)。

        タイミング窓は tuning.py の DELAY_* / TOPWATER_* / HYBRID_* で調整。
        """
        t = self._bite_elapsed
        if self._bite_mode == HOOKSET_DELAY:
            # 一呼吸置くのが正解
            if t < TU.DELAY_POOR_END:
                return "POOR"
            if t < TU.DELAY_GOOD1_END:
                return "GOOD"
            if t < TU.DELAY_JUST_END:
                return "JUST"
            if t < TU.DELAY_GOOD2_END:
                return "GOOD"
            return "NORMAL"
        if self._bite_mode == HOOKSET_VISUAL_DELAY:
            # 重みが乗る前に合わせるとすっぽ抜けやすい
            if t < self._weight_on_frame:
                return (None if random.random() < TU.TOPWATER_EARLY_MISS_P
                        else "POOR")
            dt = t - self._weight_on_frame
            if dt < TU.TOPWATER_JUST_END:
                return "JUST"
            if dt < TU.TOPWATER_GOOD_END:
                return "GOOD"
            return "NORMAL"
        if self._bite_mode == HOOKSET_AUTO:
            # クランク/スピナベ: ゴン!と来たら即合わせが正解 (窓は広め)
            if t < TU.AUTO_JUST_END:
                return "JUST"
            if t < TU.AUTO_GOOD_END:
                return "GOOD"
            return "NORMAL"
        # HYBRID (手動分岐)
        if t < TU.HYBRID_GOOD_END:
            return "GOOD"
        if t < TU.HYBRID_JUST_END:
            return "JUST"
        return "NORMAL"

    def _attempt_hookset(self) -> None:
        quality = self._hookset_quality()
        if quality is None:
            # すっぽ抜け
            self._fight_events.append(("MISSED!", 60))
            self._miss_bite()
            return
        self._do_hookset(quality)

    def _do_hookset(self, quality: str) -> None:
        """フッキング成立。50cm以上はファイトへ、それ未満は即キャッチ。"""
        # フッキング地点 (=ルアー位置) をリセット前に記録 → ファイト描画の基準
        hook_sx, hook_sy = self._uw_to_screen(self.lure.x, self.lure.y)
        # V5: フッキング成功の水しぶき
        self._spawn_splash(hook_sx, hook_sy, n=10, power=1.1)
        self.lure.reset()   # ここでルアー回収 (バイト中は水中に残している)
        self._bite_fish = None
        caught = next((f for f in self.fishes if f.state == REACT_BITE), None)
        if not caught:
            self.state         = FS_RESULT
            self._result_timer = RESULT_FRAMES
            return

        caught.size = round(caught.size + random.uniform(-1.5, 1.5), 1)
        self._result_fish    = caught
        self._result_size    = caught.size
        self._result_fish_id = caught.fish_id or ""

        if caught.size >= FIGHT_MIN_SIZE:
            # ── ファイト開始 ─────────────────────────────────────────
            fi = self._get_individual(caught)
            legend = bool(fi and fi.legend_candidate)
            # 2D ファイト: アンカー = プレイヤー立ち位置 (足場) のグリッド基準点。
            # 初期 fish 位置 = フッキング地点 (ルアー位置)。line_length_m は
            # この2点間の斜距離から FightState が自動算出する。
            anchor_cell = self._player_anchor_cell()
            start_cell  = (caught.x, caught.y)
            self._fight_hook_sx   = hook_sx
            self._fight_hook_sy   = hook_sy
            self.fight = FightState(
                fish_size=caught.size,
                hook_quality=quality,
                anchor_cell=anchor_cell,
                start_cell=start_cell,
                meters_per_cell=TU.FIGHT_METERS_PER_CELL,
                legend=legend,
            )
            # Beta v0.96: スラック適合度を初期 hook_hold に乗せる。適正スラックで
            # 掛ければ満点、外れて掛けると保持率が落ち、魚を止めにくくなる。
            hold_mult = (TU.FIGHT_SLACK_HOOKHOLD_FLOOR
                         + (1.0 - TU.FIGHT_SLACK_HOOKHOLD_FLOOR) * self._bite_slack_mod)
            self.fight.hook_hold *= hold_mult
            self.fight._hook_hold_max = self.fight.hook_hold
            # Hooking v1: RUN_START — フック直後の最初の突っ走り。サイズ別に
            # line_out_m を一気に増やしてからファイトへ入る。
            run_m = self.fight.apply_run_start()
            caught.x, caught.y = self.fight.fish_x, self.fight.fish_y
            self._fight_start_dist = self.fight.line_length_m
            self._fight_fish = caught
            self._fight_events.append((f"HOOKED! [{quality}]", 80))
            if run_m >= 4.0:
                self._fight_events.append(("LINE OUT!", 70))
            self.rod.reset()
            self.state = FS_FIGHT
            return

        # ── 50cm未満: 従来通り即キャッチ ──────────────────────────────
        caught.hook()
        self._after_catch_settled(caught)
        self.rod.reset()   # 釣果後: ロッド角度・しなりを中立へ戻す
        self.state = FS_KEEP_RELEASE

    def _after_catch_settled(self, caught: Fish) -> None:
        """キャッチ確定時の学習・再捕獲チェック (即キャッチ/ランディング共通)。"""
        # Phase 9: キャッチ学習 (KEEP/RELEASE どちらでも起こる)
        if caught.fish_id:
            fi = self._get_individual(caught)
            if fi:
                fi.learn(
                    "catch",
                    self._current_lure_category(),
                    self._current_game_day(),
                )
        # Phase 10: 再捕獲チェック
        self._result_is_recapture = False
        self._recapture_prev      = None
        if caught.fish_id and self._population:
            prev_hist = self._population.get_history(caught.fish_id)
            if prev_hist is not None:
                self._result_is_recapture = True
                self._recapture_prev      = copy.copy(prev_hist)

    # ── Beta v0.9: Fight update ───────────────────────────────────────

    def _update_fight(self) -> None:
        if not self.fight or not self._fight_fish:
            self.state = FS_IDLE
            return

        keys  = pygame.key.get_pressed()
        mouse = pygame.mouse.get_pressed()
        self.rod.update(keys)

        rod_y = 1.0 if keys[pygame.K_DOWN] else (-1.0 if keys[pygame.K_UP] else 0.0)
        rod_x = (1.0 if keys[pygame.K_RIGHT] else 0.0) - (1.0 if keys[pygame.K_LEFT] else 0.0)
        reel  = bool(mouse[0])

        self.fight.update(reel, rod_y, rod_x)

        for msg in self.fight.pop_events():
            self._fight_events.append((msg, 80))

        # 他の魚はパトロール継続
        for fish in self.fishes:
            if fish is not self._fight_fish and fish.state not in (FISH_CAUGHT, REACT_BITE):
                fish.update(None)

        if not self.fight.done:
            return

        # ── 決着 ─────────────────────────────────────────────────────
        if self.fight.outcome == OUTCOME_LANDED:
            caught = self._fight_fish
            caught.hook()
            self._after_catch_settled(caught)
            self.fight = None
            self._fight_fish = None
            self.rod.reset()   # 釣果後: ロッド角度・しなりを中立へ戻す
            self.state = FS_KEEP_RELEASE
        else:
            self._lose_fight(self.fight.outcome)

    def _lose_fight(self, reason: str, give_up: bool = False) -> None:
        """フックアウト / ラインブレイク / ギブアップ処理。"""
        caught = self._fight_fish
        if caught:
            # Phase 9: バラシ学習
            if caught.fish_id:
                fi = self._get_individual(caught)
                if fi:
                    fi.learn(
                        "miss",
                        self._current_lure_category(),
                        self._current_game_day(),
                    )
            caught.miss()

        self.fight = None
        self._fight_fish = None
        self._result_fish = None
        self.rod.reset()   # バラシ/ギブアップ後: ロッドを中立へ戻す
        self._result_action = "LOST"
        self._result_lost_reason = "GIVE UP" if give_up else reason
        self.state         = FS_RESULT
        self._result_timer = RESULT_FRAMES // 2

    def _miss_bite(self) -> None:
        for fish in self.fishes:
            if fish.state == REACT_BITE:
                # Phase 9: バラシ学習 (フッキング後に逃げた)
                if fish.fish_id:
                    fi = self._get_individual(fish)
                    if fi:
                        fi.learn(
                            "miss",
                            self._current_lure_category(),
                            self._current_game_day(),
                        )
                fish.miss()
        self.lure.reset()   # バイト中は水中に残していたルアーを回収
        self.rod.reset()    # すっぽ抜け後: ロッドを中立へ戻す
        self.state        = FS_IDLE
        self._bite_charge = 0.0
        self._bite_fish   = None

    # ── Phase 10: Keep / Release ──────────────────────────────────────

    def _keep_fish(self) -> None:
        """K キー: 魚を持ち帰る。個体削除・報酬付与・釣果保存。"""
        caught = self._result_fish
        if not caught:
            return

        lure_name = LURE_CATALOG[self._lure_idx].name
        current_day = self._current_game_day()

        # 釣果履歴を記録 (population に委譲)
        if caught.fish_id and self._population:
            self._population.record_catch_history(
                caught.fish_id, current_day, caught.size
            )
            # 湖から個体を削除 (再スポーンなし)
            self._population.remove_caught(caught.fish_id)

        # シーンからも除去
        self.fishes = [f for f in self.fishes if f is not caught]

        # 釣果ログ (FishingView ローカル)
        entry: dict = {
            "length":     caught.size,
            "lure":       lure_name,
            "ticks":      pygame.time.get_ticks(),
            "point_name": self.spot_name,
            "action":     "KEEP",
        }
        if caught.fish_id and caught.size >= 50.0:
            entry["fish_id"] = caught.fish_id
        self.catch_log.append(entry)

        # 報酬 = length_cm × 10
        reward = int(caught.size * 10)
        if self._save_manager:
            self._save_manager.money += reward

        # セーブ
        is_pb = False
        if self._save_manager:
            is_pb = self._save_manager.record_catch(
                caught.size, self.spot_name, lure_name,
                fish_id=caught.fish_id or "",
                action="KEEP",
            )
            self._save_manager.save()

        self._result_action  = "KEEP"
        self._result_reward  = reward
        self._result_is_pb   = is_pb
        # _result_fish はまだ表示用に保持 (FS_RESULT タイマー終了で None に)
        self.state            = FS_RESULT
        self._result_timer    = RESULT_FRAMES

    def _release_fish(self) -> None:
        """R キー: 魚を湖に返す。個体維持・ペナルティ・釣果保存。"""
        caught = self._result_fish
        if not caught:
            return

        lure_name   = LURE_CATALOG[self._lure_idx].name
        current_day = self._current_game_day()

        # 釣果・リリース履歴を記録
        if caught.fish_id and self._population:
            self._population.record_catch_history(
                caught.fish_id, current_day, caught.size
            )
            self._population.record_release_history(caught.fish_id)

            # FishIndividual に release ペナルティ適用
            fi = self._population.managed_fish.get(caught.fish_id)
            if fi:
                fi.release_count    += 1
                fi.last_release_day  = current_day
                fi.health            = max(0.1, fi.health - 0.05)
                fi.caution           = min(1.0, fi.caution + 0.05)

        # 魚を湖に戻す (シーンでリスポーン)
        caught.respawn(self.uw_map.best_positions(10))

        # 釣果ログ
        entry: dict = {
            "length":     self._result_size,
            "lure":       lure_name,
            "ticks":      pygame.time.get_ticks(),
            "point_name": self.spot_name,
            "action":     "RELEASE",
        }
        if caught.fish_id and self._result_size >= 50.0:
            entry["fish_id"] = caught.fish_id
        self.catch_log.append(entry)

        if self._save_manager:
            self._save_manager.record_catch(
                self._result_size, self.spot_name, lure_name,
                fish_id=caught.fish_id or "",
                action="RELEASE",
            )
            self._save_manager.save()

        self._result_action  = "RELEASE"
        self._result_reward  = 0
        self._result_is_pb   = False
        self._result_fish    = None   # 魚はシーンに戻ったので参照を切る
        self.state            = FS_RESULT
        self._result_timer    = RESULT_FRAMES // 2  # 短めの表示

    # ── Helpers ────────────────────────────────────────────────────────

    # ── Phase 9: Learning helpers ──────────────────────────────────────

    def _get_individual(self, fish: Fish) -> Optional[FishIndividual]:
        """Fish オブジェクトに紐付く FishIndividual を返す (なければ None)。"""
        if fish.fish_id and self._population:
            return self._population.managed_fish.get(fish.fish_id)
        return None

    def _current_lure_category(self) -> str:
        """現在のルアーのカテゴリ名を返す。"""
        spec = get_spec_by_idx(self._lure_idx)
        return getattr(spec, "lure_category", "hard_bait")

    def _slack_modifier(self) -> float:
        """Beta v0.96: 現在の slack_m がルアー適正レンジにどれだけ合うか。

        適正=1.0 / やや外れ=0.7 / 大きく外れ=0.3。バイト確率に乗る。
        hard_bait は張って(低スラック)、soft/bottom はフォール(高スラック)で 1.0。
        """
        spec = get_spec_by_idx(self._lure_idx)
        return slack_modifier(self.lure.slack_m, optimal_slack_range(spec))

    def _current_game_day(self) -> int:
        """現在のゲーム内日数を返す (SaveManager から)。"""
        if self._save_manager:
            return self._save_manager.game_minutes // 1440
        return 0

    def _memory_modifier_for(self, fish: Fish) -> float:
        """記憶・警戒心による bite_charge レート補正係数 [0.2, 1.0] を返す。
        個体管理外の魚 (小型魚) は補正なし (1.0)。
        """
        fi = self._get_individual(fish)
        if fi is None:
            return 1.0
        cat = self._current_lure_category()
        mem = fi.memory_for_category(cat)
        cau = fi.caution
        modifier = (1.0 - mem) * (1.0 - cau * 0.5)
        return max(0.2, min(1.0, modifier))

    # ── End Phase 9 helpers ────────────────────────────────────────────

    def _lure_spot_score(self) -> float:
        if not self.lure.in_water:
            return 0.0
        lx, ly = int(self.lure.x), int(self.lure.y)
        if 0 <= lx < UW_W and 0 <= ly < UW_H:
            return self.uw_map.full_score(lx, ly)
        return 0.0

    def _visible_lure_for(self, fish: Fish, spot_score: float):
        if fish.state in (REACT_APPROACH, REACT_CHASE):
            return self.lure  # already committed
        if fish.size >= PIN_SMALL_LIMIT and spot_score < PIN_LOW_SCORE:
            return None
        return self.lure

    # ── Exploration v2: 横スクロールカメラ ────────────────────────────
    def _camera_target(self) -> float:
        """player_stance_x(0..1, 世界全幅) を画面中央に置くカメラ目標 (px, クランプ済)。"""
        player_world_x = self.player_stance_x * WORLD_W
        return max(0.0, min(float(CAM_X_MAX), player_world_x - MAIN_W * 0.5))

    def _update_camera(self) -> None:
        """カメラを目標位置へ滑らかに追従させる。歩行(A/D)で立ち位置が動くと
        ビューが左右にスクロールし、探索感が出る。キャスト/ファイト中は立ち位置が
        固定なのでカメラも止まる。"""
        target = self._camera_target()
        self.cam_x += (target - self.cam_x) * CAM_FOLLOW
        if abs(target - self.cam_x) < 0.5:
            self.cam_x = target

    def _world_x(self, ux: float) -> float:
        """水中グリッドx(0..UW_W-1) → 世界座標x(px, カメラ適用前)。"""
        return (ux / (UW_W - 1)) * WORLD_W

    def _uw_to_world(self, ux: float, uy: float) -> Tuple[int, int]:
        """水中グリッド → 世界座標(px, カメラ適用前)。事前生成サーフェス構築用。"""
        wx = int(self._world_x(ux))
        t  = uy / (UW_H - 1)
        wy = int(WATER_Y0 + t * (WATER_NEAR_Y - WATER_Y0))
        return wx, wy

    def _screen_to_uw(self, sx: int, sy: int) -> Tuple[Optional[int], Optional[int]]:
        if not (0 <= sx < MAIN_W and WATER_Y0 <= sy <= WATER_NEAR_Y):
            return None, None
        world_x = sx + self.cam_x                       # 画面→世界 (カメラ逆適用)
        ux = int((world_x / WORLD_W) * (UW_W - 1))
        t  = (sy - WATER_Y0) / (WATER_NEAR_Y - WATER_Y0)
        uy = int(t * (UW_H - 1))
        return max(0, min(UW_W-1, ux)), max(0, min(UW_H-1, uy))

    def _uw_to_screen(self, ux: float, uy: float) -> Tuple[int, int]:
        sx = int(self._world_x(ux) - self.cam_x)        # 世界→画面 (カメラ適用)
        t  = uy / (UW_H - 1)
        sy = int(WATER_Y0 + t * (WATER_NEAR_Y - WATER_Y0))
        return sx, sy

    def _get_hovered_grid_cell(self) -> Tuple[Optional[int], Optional[int]]:
        mx, my = pygame.mouse.get_pos()
        gx, gy = mx - UW_GRID_X, my - UW_GRID_Y
        if 0 <= gx < UW_W * CELL_PX and 0 <= gy < UW_H * CELL_PX:
            return gx // CELL_PX, gy // CELL_PX
        return None, None

    # ══════════════════════════════════════════════════════════════════
    # Drawing
    # ══════════════════════════════════════════════════════════════════

    def draw(self, surface: pygame.Surface) -> None:
        # Stage 1: full_off — draw scene at full viewport resolution
        self._full_off.fill(C_BLACK)
        self._draw_scene(self._full_off)

        # Stage 2: pix_off — downscale entire full_off by PIX_DIV
        pix_w = MAIN_W // PIX_DIV    # 330
        pix_h = SCREEN_H // PIX_DIV  # 240
        pygame.transform.scale(self._full_off, (pix_w, pix_h), self._pix_off)

        # Stage 3: crop ZOOM_W worth from pix_off (camera-aware), scale to screen
        # Use explicit surface + blit instead of subsurface to avoid SRCALPHA alpha=0 bug
        src_x = max(0, min(int(self.cam_x) // PIX_DIV, pix_w - ZOOM_W // PIX_DIV))
        src_rect = pygame.Rect(src_x, 0, ZOOM_W // PIX_DIV, pix_h)
        self._pix_crop.blit(self._pix_off, (0, 0), src_rect)
        pygame.transform.scale(self._pix_crop, (MAIN_W, SCREEN_H), self._zoomed)
        surface.blit(self._zoomed, (0, 0))

        # Stage 4: UI overlays drawn directly to surface (stays sharp)
        self._draw_sidebar(surface)
        self._draw_hud(surface)
        if self.state == FS_FIGHT:
            self._draw_fight_panel(surface)
        else:
            self._draw_status_panel(surface)

        # TODO(D-2.5 diag): 切り分け完了後はこのブロックごと削除 or debug_mode に戻す。
        self._draw_diag_overlay(surface)

    def _draw_diag_overlay(self, surface: pygame.Surface) -> None:
        """D-2.5 切り分け用: 最終surfaceへ常時直接描画するランタイム診断ブロック。

        world pipeline を通さず debug_mode にも依存しない。
        「最新payloadが動いているか / debug_modeがONか / 見ているspotに構造物が
        あるか」を端末画面だけで判定できるようにする。
        """
        if self.font_sm is None:
            return
        tr = getattr(self, "terrain", None)
        structs = list(getattr(tr, "structures", []) or [])
        # 構造物の world 範囲 (bbox) を概算
        if structs:
            xs = [float(getattr(s, "x", 0.0)) for s in structs]
            ys = [float(getattr(s, "y", 0.0)) for s in structs]
            bbox = f"{min(xs):.0f},{min(ys):.0f}-{max(xs):.0f},{max(ys):.0f}m"
        else:
            bbox = "-"
        layer = getattr(self, "_structure_layer", None)
        lines = [
            (f"BUILD: {BUILD_ID}", (255, 230, 120)),
            (f"DBG: {'ON' if self.debug_mode else 'OFF'}",
             (120, 255, 140) if self.debug_mode else (255, 140, 140)),
            (f"SPOT: {self.spot_id} / {self.spot_name}", (200, 210, 255)),
            (f"STRUCT: {'yes' if layer is not None else 'no'}  count={len(structs)}",
             (200, 210, 255)),
            (f"STRUCT bbox: {bbox}", (170, 180, 210)),
        ]
        # 右下に下から積む
        pad = 6
        y = SCREEN_H - pad
        for txt, col in reversed(lines):
            surf_t = self.font_sm.render(txt, True, col)
            surf_s = self.font_sm.render(txt, True, (0, 0, 0))
            y -= surf_t.get_height()
            x = SCREEN_W - surf_t.get_width() - 8
            surface.blit(surf_s, (x + 1, y + 1))
            surface.blit(surf_t, (x, y))

    # ── Scene ──────────────────────────────────────────────────────────

    def _draw_scene(self, surface: pygame.Surface) -> None:
        # Sky
        for y in range(SKY_Y0, SKY_Y1):
            t = y / SKY_Y1
            pygame.draw.line(surface,
                             (int(50+t*80), int(100+t*80), int(180+t*50)),
                             (0, y), (MAIN_W-1, y))
        # Treeline (遠景: カメラに対し弱いパララックスでスクロール = 奥行き感)
        pygame.draw.rect(surface, (35,75,25), (0, SHORE_Y0, MAIN_W, SHORE_Y1-SHORE_Y0))
        tree_off = self.cam_x * 0.5     # 遠景は半速 (TREELINE_PARALLAX)
        for tx in range(0, WORLD_W, 38):
            sx = int(tx - tree_off)
            if sx < -20 or sx > MAIN_W:
                continue
            h = 20 + (tx*13 % 30)       # 高さは世界座標基準 → スクロールしてもチラつかない
            pygame.draw.rect(surface, (25,55,15), (sx, SHORE_Y1-h, 18, h))
        # Horizon
        pygame.draw.rect(surface, (90,150,210), (0, SHORE_Y1, MAIN_W, 18))
        # Water gradient (手前端 WATER_NEAR_Y まで)
        for y in range(WATER_Y0, WATER_NEAR_Y):
            t = (y - WATER_Y0) / (WATER_NEAR_Y - WATER_Y0)
            wr,wg,wb = int(18+t*35), int(65+t*45), int(155+t*25)
            pygame.draw.line(surface, (wr,wg,wb), (0,y), (MAIN_W-1,y))
            if (y - WATER_Y0) % 20 == 0:
                pygame.draw.line(surface, (wr+18,wg+18,wb+18), (0,y+1),(MAIN_W-1,y+1), 1)
        # Foreground water
        pygame.draw.rect(surface, (12,45,110), (0, WATER_NEAR_Y, MAIN_W, SCREEN_H-WATER_NEAR_Y))

        # ── F2デバッグ時のみ水深グラデーション表示 ──────────────────────
        # 通常プレイ時は水深を色で見せない (ポイント探索のゲーム性を守る)。
        if self.debug_mode and self._depth_debug_surf is not None:
            surface.blit(self._depth_debug_surf, (int(-self.cam_x), 0))

        # ── 旧 _struct_surf (underwater map セル単位のマス目状ストラクチャー) ──
        # D-3.2: 通常時は非表示。StructureObject baked layer を主表示にするため、
        # このセルグリッド描画が「マス目状の岩/ウィード」の正体。フラグで復活可。
        if SHOW_LEGACY_STRUCT_SURF and self._struct_surf is not None:
            surface.blit(self._struct_surf, (int(-self.cam_x), 0))

        # ── Phase D-1: StructureObject レイヤー (spot.structures を焼いたもの) ──
        # 毎フレーム blit のみ。生成は init_fonts / spot単位キャッシュ済み。
        if SHOW_STRUCTURE_LAYER and self._structure_layer is not None:
            surface.blit(self._structure_layer, (int(-self.cam_x), 0))

        # F2デバッグ時のみ StructureObject 中心にマーカー/ラベルを出す
        if self.debug_mode:
            self._draw_structure_debug(surface)

        # Depth guide lines on water surface (faint horizontals per 0.5m)
        if self.lure.in_water:
            for depth_mark in [0.5, 1.0, 1.5, 2.0]:
                _, my = self._uw_to_screen(self.lure.x, depth_mark * 1.5)
                if WATER_Y0 <= my <= WATER_NEAR_Y:
                    pygame.draw.line(surface, (30,80,130,60), (0,my), (MAIN_W-1,my), 1)

        # ── V4: 魚影 (CHASE以上のみ; 追尾を感じさせる半透明シルエット) ──
        if not self.debug_mode:
            self._draw_fish_shadows(surface)

        # ── Debug: 水中地形 + 魚をフィールドへ投影表示 ────────────────
        if self.debug_mode:
            self._draw_field_debug(surface)

        # Cast cursor (idle): 十字キーで動かす黄色の小さな十字
        if self.state == FS_IDLE:
            mx, my = self._uw_to_screen(self.cast_cursor_x, self.cast_cursor_y)
            pygame.draw.circle(surface, C_YELLOW, (mx, my), 10, 2)
            for p0, p1 in [((mx-16,my),(mx-6,my)), ((mx+6,my),(mx+16,my)),
                           ((mx,my-16),(mx,my-6)), ((mx,my+6),(mx,my+16))]:
                pygame.draw.line(surface, C_YELLOW, p0, p1, 2)

        # Intended cast marker (fading)
        if self._intended_timer > 0 and self._intended_pos is not None:
            iux,iuy = self._intended_pos
            ix,iy = self._uw_to_screen(iux, iuy)
            col = (200, 200, 100)
            pygame.draw.circle(surface, col, (ix,iy), 12, 1)
            pygame.draw.line(surface, col, (ix-15,iy),(ix+15,iy), 1)
            pygame.draw.line(surface, col, (ix,iy-15),(ix,iy+15), 1)
            if self.lure.in_water:
                lx,ly = self._uw_to_screen(self.lure.x, self.lure.y)
                pygame.draw.line(surface, col, (ix,iy), (lx,ly), 1)

        # Lure
        if self.lure.in_water:
            lx,ly = self._uw_to_screen(self.lure.x, self.lure.y)
            if 0 <= lx < MAIN_W and WATER_Y0 <= ly <= WATER_NEAR_Y:
                action_col = _ACTION_COLOR.get(self.lure.action, C_LURE)
                for i in range(1,5):
                    pygame.draw.line(surface,(80,140,200),(lx-i*7,ly+1),(lx-i*5+2,ly+1),2)
                pygame.draw.circle(surface, action_col, (lx,ly), 7)
                pygame.draw.circle(surface, C_WHITE, (lx,ly), 7, 2)

        # Splash
        if self._splash_timer > 0 and self.lure.in_water:
            lx,ly = self._uw_to_screen(self.lure.x, self.lure.y)
            r = int((24-self._splash_timer)*2.5)+2
            pygame.draw.circle(surface, C_WHITE, (lx,ly), r, 2)

        # V5: 水面パーティクル (波紋/しぶき)
        self._draw_particles(surface)

        # ── Beta v0.9: Cast charge gauge ─────────────────────────────
        if self.state == FS_CAST_CHARGE:
            self._draw_cast_gauge(surface)

        # ── Beta v0.9: Cast quality flash ────────────────────────────
        if self._cast_quality_timer > 0 and self._cast_quality and self.font:
            qcol = {
                CAST_PERFECT: (80, 255, 120),
                CAST_GOOD:    C_YELLOW,
                CAST_EARLY:   (160, 160, 160),
                CAST_LATE:    (255, 110, 60),
            }.get(self._cast_quality, C_WHITE)
            qs = self.font.render(self._cast_quality, True, qcol)
            surface.blit(qs, (MAIN_W // 2 - qs.get_width() // 2, 200))

        # ── Beta v0.9: Bite cue (ルアー別アタリ演出) ──────────────────
        if self.state == FS_BITE and self.font_lg and self.font:
            self._draw_bite_cue(surface)

        # ── Hooking v1: ワーム系 WEIGHT / LINE_RUN キュー ─────────────
        if self.state in (FS_WEIGHT, FS_LINE_RUN) and self.font_lg and self.font:
            self._draw_worm_bite_cue(surface)

        # ── Beta v0.9: Fight scene (魚マーカー・ライン) ────────────────
        if self.state == FS_FIGHT and self.fight:
            self._draw_fight_scene(surface)

        # ── Beta v0.9: Rod (動的描画) ─────────────────────────────────
        self._draw_rod(surface)

        # ── v0.95: Cast flight (飛んでいくルアー + 薄い軌跡) ───────────
        if self.state == FS_CASTING:
            self._draw_cast_flight(surface)

        # ── Beta v0.9: Fight event flashes ────────────────────────────
        if self._fight_events and self.font:
            fy = 240
            for msg, t in self._fight_events[-3:]:
                alpha = min(1.0, t / 30.0)
                col = (255, int(220 * alpha), int(60 * alpha))
                es = self.font.render(msg, True, col)
                surface.blit(es, (MAIN_W // 2 - es.get_width() // 2, fy))
                fy += 30

        # ── Phase 10: Keep / Release 選択オーバーレイ ────────────────
        if self.state == FS_KEEP_RELEASE and self.font_lg:
            dim = pygame.Surface((MAIN_W, SCREEN_H), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 160))
            surface.blit(dim, (0, 0))

            y = 150

            # RECAPTURE 演出
            if self._result_is_recapture and self._recapture_prev:
                pulse = abs(math.sin(self._frame_count * 0.15))
                rc = (int(255 * pulse + 200 * (1 - pulse)),
                      int(200 * pulse + 150 * (1 - pulse)), 30)
                rec_surf = self.font_lg.render("★ RECAPTURE ★", True, rc)
                surface.blit(rec_surf, (MAIN_W // 2 - rec_surf.get_width() // 2, y))
                y += rec_surf.get_height() + 6

                prev = self._recapture_prev
                info_lines = [
                    (f"Last caught: Day {prev.last_caught_day + 1}", C_GRAY),
                    (f"Was: {prev.best_length:.1f} cm  →  Now: {self._result_size:.1f} cm",
                     C_YELLOW),
                ]
                for txt, col in info_lines:
                    ts = self.font.render(txt, True, col)
                    surface.blit(ts, (MAIN_W // 2 - ts.get_width() // 2, y))
                    y += 26
                y += 8
            else:
                # 通常キャッチ
                cs = self.font_lg.render("CATCH!", True, C_GREEN)
                surface.blit(cs, (MAIN_W // 2 - cs.get_width() // 2, y))
                y += cs.get_height() + 6

            # 個体情報
            if self.font:
                fish_lines = []
                if self._result_fish_id and self._result_size >= 40.0:
                    fish_lines.append((f"[{self._result_fish_id}]", (255, 200, 60)))
                fish_lines.append((f"{self._result_size:.1f} cm", C_WHITE))
                if self._result_fish:
                    fi = (self._population.managed_fish.get(self._result_fish_id)
                          if self._population and self._result_fish_id else None)
                    if fi:
                        fish_lines.append((f"Age {fi.age}", C_GRAY))
                        if fi.release_count > 0:
                            fish_lines.append((f"Released {fi.release_count}x", (100, 200, 255)))
                for txt, col in fish_lines:
                    ts = self.font.render(txt, True, col)
                    surface.blit(ts, (MAIN_W // 2 - ts.get_width() // 2, y))
                    y += 28

                y += 16
                # 区切り線
                pygame.draw.line(surface, C_GRAY,
                                 (MAIN_W // 2 - 140, y), (MAIN_W // 2 + 140, y), 1)
                y += 12

                reward_pts = int(self._result_size * 10)
                keep_surf = self.font.render(
                    f"[K]  KEEP   +{reward_pts} pt", True, (80, 220, 80))
                rel_surf = self.font.render(
                    "[R]  RELEASE", True, (80, 180, 255))
                surface.blit(keep_surf, (MAIN_W // 2 - keep_surf.get_width() // 2, y))
                y += 32
                surface.blit(rel_surf,  (MAIN_W // 2 - rel_surf.get_width() // 2, y))

        # ── Result overlay (KEEP / RELEASE 後) ───────────────────────
        if self.state == FS_RESULT and self.font_lg:
            dim = pygame.Surface((MAIN_W, SCREEN_H), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 140))
            surface.blit(dim, (0, 0))

            y = 190
            if self._result_action == "KEEP":
                cs = self.font_lg.render("KEEP!", True, (80, 220, 80))
                surface.blit(cs, (MAIN_W // 2 - cs.get_width() // 2, y))
                y += cs.get_height() + 10
                if self.font:
                    lines = []
                    if self._result_fish_id and self._result_size >= 50.0:
                        lines.append((f"[{self._result_fish_id}]", (255, 200, 60)))
                    lines.append((f"{self._result_size:.1f} cm", C_WHITE))
                    lines.append((f"+ {self._result_reward} pt", (80, 220, 80)))
                    if self._result_is_pb:
                        lines.append(("★  NEW PERSONAL BEST!", C_YELLOW))
                    for txt, col in lines:
                        ts = self.font.render(txt, True, col)
                        surface.blit(ts, (MAIN_W // 2 - ts.get_width() // 2, y))
                        y += 34
            elif self._result_action == "RELEASE":
                cs = self.font_lg.render("RELEASE!", True, (80, 180, 255))
                surface.blit(cs, (MAIN_W // 2 - cs.get_width() // 2, y))
                y += cs.get_height() + 10
                if self.font:
                    lines = []
                    if self._result_fish_id and self._result_size >= 50.0:
                        lines.append((f"[{self._result_fish_id}]", (255, 200, 60)))
                    lines.append((f"{self._result_size:.1f} cm", C_WHITE))
                    lines.append(("→ back to the lake", C_GRAY))
                    for txt, col in lines:
                        ts = self.font.render(txt, True, col)
                        surface.blit(ts, (MAIN_W // 2 - ts.get_width() // 2, y))
                        y += 34
            elif self._result_action == "LOST":
                # Beta v0.9: ファイト敗北 (フックアウト / ラインブレイク)
                reason = self._result_lost_reason
                if reason == OUTCOME_LINE_BREAK:
                    title, tcol = "LINE BREAK!", (255, 80, 60)
                elif reason == "GIVE UP":
                    title, tcol = "GAVE UP...", C_GRAY
                else:
                    title, tcol = "HOOK OUT...", (200, 160, 255)
                cs = self.font_lg.render(title, True, tcol)
                surface.blit(cs, (MAIN_W // 2 - cs.get_width() // 2, y))
                y += cs.get_height() + 10
                if self.font:
                    ts = self.font.render("The fish got away.", True, C_GRAY)
                    surface.blit(ts, (MAIN_W // 2 - ts.get_width() // 2, y))
            else:
                # フォールバック (旧フロー)
                if self._result_fish:
                    cs = self.font_lg.render("CATCH!", True, C_GREEN)
                    surface.blit(cs, (MAIN_W // 2 - cs.get_width() // 2, y))
                    y += cs.get_height() + 10
                    if self.font:
                        ts = self.font.render(
                            f"{self._result_fish.size:.1f} cm", True, C_WHITE)
                        surface.blit(ts, (MAIN_W // 2 - ts.get_width() // 2, y))

    def _draw_fish_shadows(self, surface: pygame.Surface) -> None:
        """CHASE以上の魚を半透明黒シルエットで水面に投影する (追尾中のみ)。

        魚本体は描かない。「魚がいる/追っている」を感じさせるのが目的。
        ルアーを追っている向きへシルエットを傾け、進行方向を伝える。
        魚スプライトの描き込みは意図的にしない (Visual Pass の優先順位)。
        """
        if not self.lure.in_water:
            return
        lx, ly = self._uw_to_screen(self.lure.x, self.lure.y)
        for fish in self.fishes:
            if fish.state not in (REACT_CHASE, REACT_BITE):
                continue
            fx, fy = self._uw_to_screen(fish.x, fish.y)
            if not (0 <= fx < MAIN_W and WATER_Y0 <= fy <= WATER_NEAR_Y):
                continue
            # 奥ほど小さく + サイズ反映。BITEは少し濃く
            depth_scale = 0.5 + 0.5 * (fish.y / (UW_H - 1))
            body_len = int((14 + fish.size * 0.55) * depth_scale)
            body_h   = max(4, int(body_len * 0.42))
            alpha    = 70 if fish.state == REACT_CHASE else 105
            # シルエット (小サーフェスに描いてルアー方向へ回転)
            pad = 4
            sw, sh = body_len + pad * 2, body_h + pad * 2
            shp = pygame.Surface((sw, sh), pygame.SRCALPHA)
            pygame.draw.ellipse(shp, (5, 12, 20, alpha),
                                (pad, pad, body_len, body_h))
            # 尾びれ
            tail = body_h
            pygame.draw.polygon(
                shp, (5, 12, 20, alpha),
                [(pad + 2, sh // 2),
                 (pad - 3, sh // 2 - tail // 2),
                 (pad - 3, sh // 2 + tail // 2)])
            ang = math.degrees(math.atan2(-(ly - fy), lx - fx))  # ルアー方向
            rot = pygame.transform.rotate(shp, ang)
            surface.blit(rot, (fx - rot.get_width() // 2,
                               fy - rot.get_height() // 2))

    def _draw_field_debug(self, surface: pygame.Surface) -> None:
        """デバッグ: 水中地形セルと魚をメインビューの水面へ投影描画する。"""
        overlay = pygame.Surface((MAIN_W, SCREEN_H), pygame.SRCALPHA)

        # 地形セル (flat 以外のみ; 半透明)
        for cy in range(UW_H):
            for cx in range(UW_W):
                cell = self.uw_map.cell(cx, cy)
                if cell.terrain == TERRAIN_ROCK:
                    color = C_ROCK_CELL
                elif cell.cover:
                    color = C_COVER_CELL
                elif cell.weed:
                    color = C_WEED_CELL
                elif cell.terrain == TERRAIN_BREAK:
                    color = C_BREAK_CELL
                else:
                    continue
                x0, y0 = self._uw_to_screen(cx - 0.5, cy - 0.5)
                x1, y1 = self._uw_to_screen(cx + 0.5, cy + 0.5)
                pygame.draw.rect(
                    overlay, (*color, 90),
                    (x0, y0, max(1, x1 - x0 - 1), max(1, y1 - y0 - 1)),
                )

        # 魚マーカー (リアクション色 + サイズ表示)
        for fish in self.fishes:
            if fish.state == FISH_CAUGHT:
                continue
            fx, fy = self._uw_to_screen(fish.x, fish.y)
            col = _REACT_COLOR.get(fish.state, C_FISH_IDLE)
            r = 5 + int(fish.size / 15)
            pygame.draw.circle(overlay, (*col, 220), (fx, fy), r)
            pygame.draw.circle(overlay, (255, 255, 255, 200), (fx, fy), r, 1)
            if self.font_sm:
                ts = self.font_sm.render(f"{fish.size:.0f}", True, C_WHITE)
                overlay.blit(ts, (fx + r + 2, fy - 8))

        surface.blit(overlay, (0, 0))

    # ── Beta v0.9: New drawing helpers ─────────────────────────────────

    def _draw_cast_gauge(self, surface: pygame.Surface) -> None:
        """キャスト溜めゲージ (PERFECT/GOODゾーン表示付き)。"""
        GW, GH = 320, 26
        GX, GY = MAIN_W // 2 - GW // 2, 560

        pygame.draw.rect(surface, (25, 25, 35), (GX, GY, GW, GH))
        # ゾーン帯: EARLY(灰) / GOOD(黄) / PERFECT(緑) / LATE(赤)
        def zone_x(v: float) -> int:
            return GX + int(GW * min(1.0, v / CAST_CHARGE_MAX))
        pygame.draw.rect(surface, (70, 70, 70),
                         (GX, GY, zone_x(CAST_GOOD_LO) - GX, GH))
        pygame.draw.rect(surface, (130, 120, 40),
                         (zone_x(CAST_GOOD_LO), GY,
                          zone_x(CAST_PERFECT_LO) - zone_x(CAST_GOOD_LO), GH))
        pygame.draw.rect(surface, (40, 140, 60),
                         (zone_x(CAST_PERFECT_LO), GY,
                          zone_x(CAST_PERFECT_HI) - zone_x(CAST_PERFECT_LO), GH))
        pygame.draw.rect(surface, (130, 110, 40),
                         (zone_x(CAST_PERFECT_HI), GY,
                          zone_x(100.0) - zone_x(CAST_PERFECT_HI), GH))
        pygame.draw.rect(surface, (150, 50, 40),
                         (zone_x(100.0), GY, GX + GW - zone_x(100.0), GH))

        # 現在値マーカー
        mx = zone_x(self._cast_charge)
        pygame.draw.line(surface, C_WHITE, (mx, GY - 4), (mx, GY + GH + 4), 3)
        pygame.draw.rect(surface, C_WHITE, (GX, GY, GW, GH), 2)

        if self.font_sm:
            lbl = self.font_sm.render(
                "Release in the GREEN zone!", True, C_WHITE)
            surface.blit(lbl, (GX + GW // 2 - lbl.get_width() // 2, GY + GH + 8))

    def _draw_bite_cue(self, surface: pygame.Surface) -> None:
        """アタリは竿先の引き込み (_rod_tension_visual) で伝える。
        画面表示はロッド付近の「!」と水面演出のみに抑える。
        操作ヒントは画面下部HUD ("Press DOWN to hookset!") に常設。
        """
        # トップ: 重みが乗る前は水面の演出のみ (まだ合わせない)
        if (self._bite_mode == HOOKSET_VISUAL_DELAY
                and self._bite_elapsed < self._weight_on_frame):
            if (self._bite_elapsed // 10) % 2 == 0 and self.font:
                ts = self.font.render("splash!", True, (150, 200, 255))
                surface.blit(ts, (MAIN_W // 2 - ts.get_width() // 2, WATER_Y0 + 30))
            return

        # ロッドの手元に「!」 — 強いアタリほど大きく速く点滅
        strong = self._bite_type == BITE_HEAVY_STRIKE
        if (self._bite_elapsed // (6 if strong else 12)) % 2 == 0:
            f = self.font_lg if (strong and self.font_lg) else self.font
            if f:
                col = (255, 80, 60) if strong else (255, 220, 120)
                cs = f.render("!", True, col)
                surface.blit(cs, (self.rod_anchor[0] - 50, SCREEN_H - 170))

    def _draw_worm_bite_cue(self, surface: pygame.Surface) -> None:
        """Hooking v1: ワーム系のバイト工程キュー。

        WEIGHT  : "weight..." (重みが乗る = まだ送り込む)
        LINE_RUN: "LINE RUN!" + 走行点の点滅 (合わせの好機)
        """
        if self.state == FS_WEIGHT:
            if (self._bite_elapsed // 14) % 2 == 0:
                ts = self.font.render("weight...", True, (255, 220, 120))
                surface.blit(ts, (self.rod_anchor[0] - 60, SCREEN_H - 170))
        else:  # FS_LINE_RUN
            if (self._bite_elapsed // 6) % 2 == 0 and self.font_lg:
                ts = self.font_lg.render("LINE RUN!", True, (255, 120, 60))
                surface.blit(ts, (self.rod_anchor[0] - 70, SCREEN_H - 185))
            # 走っているルアー位置に赤マーカー (ライン角度の変化を強調)
            if self.lure.in_water:
                lx, ly = self._uw_to_screen(self.lure.x, self.lure.y)
                if 0 <= lx < MAIN_W:
                    pygame.draw.circle(surface, (255, 80, 60), (lx, ly), 6, 2)

    def _rod_tension_visual(self) -> float:
        """描画用テンション値 (状態に応じて算出)。"""
        if self.state == FS_FIGHT and self.fight:
            return self.fight.tension
        if self.state == FS_CAST_CHARGE:
            # 振りかぶり: 溜めに応じて後方へしなる表現の代用
            return min(1.0, self._cast_charge / 100.0) * 0.5
        if self.state == FS_WEIGHT:
            # Hooking v1: 重みが乗る → ティップが少し入り、ラインが張っていく
            t = self._bite_elapsed
            ramp = min(1.0, t / max(1, TU.WORM_WEIGHT_TO_RUN))
            pulse = max(0.0, math.sin(t * 0.30)) ** 3
            return 0.10 + 0.18 * ramp + 0.10 * pulse
        if self.state == FS_LINE_RUN:
            # Hooking v1: 魚が走る → ラインが強く張り、竿先が魚方向へ入り続ける
            t = self._bite_elapsed
            return 0.40 + 0.12 * abs(math.sin(t * 0.18))
        if self.state == FS_BITE:
            # アタリ: 竿先が引き込まれる。ルアー別に引っ張りの強さ・リズムが違う
            t = self._bite_elapsed
            if (self._bite_mode == HOOKSET_VISUAL_DELAY
                    and t < self._weight_on_frame):
                return 0.08   # トップ: バシャ! 後、まだ重みは乗っていない
            if self._bite_type == BITE_LIGHT_TICK:
                # ワーム系: コツ…コツ…と小さく引き込まれる
                pulse = max(0.0, math.sin(t * 0.30)) ** 3
                return 0.10 + 0.25 * pulse
            if self._bite_type == BITE_MEDIUM_TICK:
                # ミノー/ジグ: 明確にティップが入る
                pulse = max(0.0, math.sin(t * 0.24)) ** 2
                return 0.15 + 0.35 * pulse
            # クランク/スピナベ/トップ重みあり: ゴン! 強く引き込まれ続ける
            return 0.50 + 0.20 * abs(math.sin(t * 0.12))
        if self.state == FS_RETRIEVE and self.lure.in_water:
            # 糸ふけがある間はテンションが乗らない (竿はほぼ真っ直ぐ)
            if self.lure.slack >= 0.1:
                return 0.03
            base = 0.12
            if self.lure.action == ACTION_RETRIEVE:
                base += 0.10 * self.lure.retrieve_mult
            elif self.lure.action == ACTION_LIFT:
                base += 0.14
            return base
        return 0.05

    @property
    def rod_anchor(self) -> Tuple[int, int]:
        """ロッドのバット位置 (画面座標)。プレイヤーの立ち位置 x(世界座標) に連動し、
        カメラ(cam_x)を適用した画面x、画面下端の下 (手元) から伸びる。
        追従カメラにより通常は画面中央付近に来る。"""
        screen_x = self.player_stance_x * WORLD_W - self.cam_x
        return (int(screen_x), ROD_BASE_Y)

    def _player_anchor_cell(self) -> Tuple[float, float]:
        """プレイヤー立ち位置の水中グリッド基準点 (足場)。

        x = 立ち位置 (player_stance_x, 幅 UW_W 基準)、y = 手前端 (= 岸)。
        ファイトのライン長・寄せ方向はこの点を基準に2Dで計算する。
        """
        ax = self.player_stance_x * (UW_W - 1)
        ay = float(UW_H - 1)
        return (ax, ay)

    def _retrieve_target_cell_x(self) -> float:
        """リトリーブの自然な寄せ先 = プレイヤーの立ち位置の列 (幅 UW_W 基準)。"""
        return max(0.0, min(float(UW_W - 1),
                            self.player_stance_x * (UW_W - 1)))

    def _draw_rod(self, surface: pygame.Surface) -> None:
        """ロッド本体 + ラインを描画。"""
        tension = self._rod_tension_visual()
        # ロッドのしなりはルアー/魚の方向へ引き込まれる
        target: Optional[Tuple[int, int]] = None
        shake = 0.0
        rod_flex = 1.0
        bend_floor = 0.0
        if self.state == FS_FIGHT and self.fight:
            target = self._fight_fish_screen_pos()
            f = self.fight
            # 大物ほど深く胴に入る (40cm:1.0 → 65cm:1.45)。ロッドを見れば大きさが分かる
            rod_flex = 1.0 + max(0.0, (f.fish_size - 40.0)) * 0.018
            # v0.96: ファイト中は常に魚に引かれている → テンションが抜けても竿先が
            # 魚方向へ入ったままになるよう曲げの下限を与える。大物ほど深く入る。
            bend_floor = TU.ROD_FIGHT_BEND_FLOOR + max(0.0, (f.fish_size - 40.0)) * 0.006
            # 高テンション警告: REDに入るほど・ライン負荷が溜まるほど激しく震える
            if f.tension > T_YELLOW:
                over = (f.tension - T_YELLOW) / (1.0 - T_YELLOW)
                shake = 2.0 + 5.0 * over + 8.0 * f.line_stress_ratio
        elif self.lure.in_water:
            target = self._uw_to_screen(self.lure.x, self.lure.y)
        tip = self.rod.draw(surface, self.rod_anchor, tension, rod_flex=rod_flex,
                            length=TU.ROD_VISUAL_LENGTH, target=target, shake=shake,
                            bend_floor=bend_floor)

        # ライン: ティップ → ルアー (リトリーブ中) / 魚 (ファイト中)
        line_col = (210, 220, 235)
        if self.state == FS_FIGHT and self.fight:
            fx, fy = self._fight_fish_screen_pos()
            self._draw_fight_line(surface, tip, (fx, fy))
        elif self.lure.in_water:
            lx, ly = self._uw_to_screen(self.lure.x, self.lure.y)
            if 0 <= lx < MAIN_W:
                sag = min(1.0, self.lure.slack / 1.5)
                if sag > 0.03:
                    # 糸ふけ: ラインが弛んで垂れ下がる (2次ベジェ近似)
                    cx = (tip[0] + lx) * 0.5
                    cyt = (tip[1] + ly) * 0.5 + 18 + 70 * sag
                    pts = []
                    for i in range(13):
                        t = i / 12.0
                        bx = (1-t)**2 * tip[0] + 2*(1-t)*t * cx + t*t * lx
                        by = (1-t)**2 * tip[1] + 2*(1-t)*t * cyt + t*t * ly
                        pts.append((int(bx), int(by)))
                    pygame.draw.lines(surface, (170, 180, 200), False, pts, 1)
                    if self.lure.slack >= 0.4 and self.font_sm:
                        sl = self.font_sm.render("slack", True, (150, 160, 180))
                        surface.blit(sl, (int(cx) - sl.get_width() // 2,
                                          int(cyt) + 4))
                else:
                    pygame.draw.line(surface, line_col, tip, (lx, ly), 1)

    def _draw_cast_flight(self, surface: pygame.Surface) -> None:
        """飛行中のルアー: 薄いライン軌跡 + 小さなルアー点 + ティップ→ルアーのライン。"""
        t = min(1.0, self._cast_flight_timer / max(1, self._cast_flight_duration))
        lx, ly = self._cast_flight_pos(t)
        lx, ly = int(lx), int(ly)

        # ロッドティップ → 飛行中ルアーのライン (放出されていく糸)
        tip = self.rod.tip_pos(self.rod_anchor, length=TU.ROD_VISUAL_LENGTH)
        pygame.draw.line(surface, (200, 210, 230), tip, (lx, ly), 1)

        # 薄い軌跡
        if len(self._cast_flight_trail) >= 2:
            pts = [(int(px), int(py)) for px, py in self._cast_flight_trail]
            ov = pygame.Surface((MAIN_W, SCREEN_H), pygame.SRCALPHA)
            pygame.draw.lines(ov, (255, 255, 255, 70), False, pts, 1)
            surface.blit(ov, (0, 0))

        # ルアー点 (小さく)
        pygame.draw.circle(surface, C_LURE, (lx, ly), 4)
        pygame.draw.circle(surface, C_WHITE, (lx, ly), 4, 1)

    def _draw_fight_line(self, surface: pygame.Surface,
                         tip: Tuple[int, int], fish: Tuple[int, int]) -> None:
        """ファイト中のライン: ゾーンで見え方が変わる。
          BLUE(SLACK) : たるんで垂れ下がる (危険=フックアウト)
          GREEN(SAFE) : 細い綺麗な直線
          YELLOW(HIGH): 太く張り詰める
          RED(DANGER) : 赤く点滅し、極限まで張る
        ラインの角度がそのまま魚の進行方向を示す (fish 座標が lateral 反映)。
        """
        f = self.fight
        z = f.zone
        tx, ty = tip
        fxp, fyp = fish

        if z == "BLUE":
            # v0.96: たるみは「軽い垂れ」に留める。竿先→魚は基本まっすぐで、
            # テンションが抜けてもラインが不自然に大きく垂れない (やり取り感重視)。
            slack = (T_GREEN - f.tension) / T_GREEN   # 0..1
            mx = (tx + fxp) * 0.5
            my = (ty + fyp) * 0.5 + 8 + 24 * max(0.0, slack)
            pts = []
            for i in range(13):
                t = i / 12.0
                bx = (1-t)**2 * tx + 2*(1-t)*t * mx + t*t * fxp
                by = (1-t)**2 * ty + 2*(1-t)*t * my + t*t * fyp
                pts.append((int(bx), int(by)))
            pygame.draw.lines(surface, (150, 170, 195), False, pts, 1)
            return

        if z == "GREEN":
            col, w = (220, 235, 250), 1
        elif z == "YELLOW":
            col, w = (255, 240, 180), 2          # 張り詰め: 太く明るく
        else:  # RED
            blink = (self._frame_count % 8) < 4
            col = (255, 70, 50) if blink else (255, 150, 120)
            w = 3
        pygame.draw.line(surface, col, tip, (fxp, fyp), w)
        if z == "RED":
            # 張り極限: ラインに沿って白いハイライトを重ねる
            pygame.draw.line(surface, (255, 220, 210), tip, (fxp, fyp), 1)

    def _fight_fish_screen_pos(self) -> Tuple[int, int]:
        """ファイト中の魚の画面位置。

        魚のグリッド座標 (fish_x, fish_y) をそのまま画面座標へ変換する。
        立ち位置 (アンカー) 方向へ寄せれば、画面上でも魚が立ち位置側へ引かれる。
        ライン角度 = ティップ→魚 がそのまま 2D の引き方向を表す。
        """
        f = self.fight
        fx, fy = self._uw_to_screen(f.fish_x, f.fish_y)
        return max(20, min(MAIN_W - 20, fx)), max(WATER_Y0 + 20, min(WATER_NEAR_Y, fy))

    def _draw_fight_scene(self, surface: pygame.Surface) -> None:
        """水面の魚マーカー (波紋・向き矢印)。"""
        f = self.fight
        fx, fy = self._fight_fish_screen_pos()

        # 波紋
        r = 10 + int(abs(math.sin(f.frame * 0.1)) * 8)
        pygame.draw.circle(surface, (220, 235, 255), (fx, fy), r, 2)
        pygame.draw.circle(surface, (160, 200, 240), (fx, fy), r + 8, 1)

        # 頭の向き矢印 (進行方向)
        adx = 26 if f.head_dir > 0 else -26
        pygame.draw.line(surface, C_YELLOW, (fx, fy), (fx + adx, fy), 3)
        pygame.draw.line(surface, C_YELLOW, (fx + adx, fy),
                         (fx + adx - (6 if f.head_dir > 0 else -6), fy - 5), 3)
        pygame.draw.line(surface, C_YELLOW, (fx + adx, fy),
                         (fx + adx - (6 if f.head_dir > 0 else -6), fy + 5), 3)

        # 行動表示 (RUN中など)
        if self.font_sm and f.behavior in ("RUN", "DIVE", "SHAKE"):
            bs = self.font_sm.render(f.behavior + "!", True, (255, 160, 80))
            surface.blit(bs, (fx - bs.get_width() // 2, fy - 30))

        # 障害物警告
        if f.obstacle_lock and self.font and (self._frame_count % 30) < 20:
            ob = self.font.render("IN COVER! Pull the opposite way!", True, (255, 120, 50))
            surface.blit(ob, (MAIN_W // 2 - ob.get_width() // 2, 300))

        # ── 高テンション危険演出: 赤ビネット + 警告テキスト ──────────
        # 「ヤバい、切れる!」と感じさせ、気づいて入力を離せば助かる
        if f.zone == "RED":
            reeling = bool(pygame.mouse.get_pressed()[0])
            danger = max((f.tension - T_YELLOW) / (1.0 - T_YELLOW),
                         f.line_stress_ratio)
            pulse = abs(math.sin(self._frame_count * (0.35 if reeling else 0.18)))
            a = int((50 + 110 * danger) * (0.45 + 0.55 * pulse))
            vign = pygame.Surface((MAIN_W, SCREEN_H), pygame.SRCALPHA)
            bw = 14 + int(18 * danger)
            for rect in ((0, 0, MAIN_W, bw), (0, SCREEN_H - bw, MAIN_W, bw),
                         (0, 0, bw, SCREEN_H), (MAIN_W - bw, 0, bw, SCREEN_H)):
                pygame.draw.rect(vign, (255, 40, 25, a), rect)
            surface.blit(vign, (0, 0))

            if self.font_lg and self.font:
                if reeling:
                    msg, sub = "STOP REELING!!", "Release LMB / rod UP to save the line!"
                elif f.line_stress_ratio > 0.25:
                    msg, sub = "LINE BREAKING!", "Rod UP to release tension!"
                else:
                    msg, sub = "", ""
                if msg and (self._frame_count % 14) < 9:
                    ws = self.font_lg.render(msg, True, (255, 60, 40))
                    surface.blit(ws, (MAIN_W // 2 - ws.get_width() // 2, 230))
                    ss = self.font.render(sub, True, (255, 170, 150))
                    surface.blit(ss, (MAIN_W // 2 - ss.get_width() // 2, 296))

        # ランディング圏内表示
        if f.distance <= LANDING_DIST_M and self.font:
            pulse = (self._frame_count % 40) < 25
            col = (80, 255, 120) if pulse else (50, 180, 90)
            ls = self.font.render("LANDING RANGE!  Hold DOWN!", True, col)
            surface.blit(ls, (MAIN_W // 2 - ls.get_width() // 2, 340))
            if f.landing_progress > 0:
                pw = int(180 * f.landing_progress / 50)
                pygame.draw.rect(surface, (40, 40, 40),
                                 (MAIN_W // 2 - 90, 372, 180, 10))
                pygame.draw.rect(surface, (80, 255, 120),
                                 (MAIN_W // 2 - 90, 372, pw, 10))

    def _draw_tension_gauge_v(self, surface: pygame.Surface, f) -> None:
        """画面右側の縦型テンションゲージ (色 + 白マーカーのみ)。

        下=青(SLACK), 中=緑(SAFE), 上=黄〜赤(DANGER)。ラベルや大きな文字は
        付けず、現在テンション位置に小さな白マーカーだけを置く。ロッド (中央)
        とは被らない右端に配置する。
        """
        VW, VH = self._VGAUGE_W, self._VGAUGE_H
        VX, VY = self._VGAUGE_X, self._VGAUGE_Y
        if self._vgauge_surf is not None:
            surface.blit(self._vgauge_surf, (VX, VY))
        pygame.draw.rect(surface, (40, 40, 48), (VX, VY, VW, VH), 2)
        # 現在テンション位置の白マーカー (横線 + 左側の小三角)
        t = max(0.0, min(1.0, f.tension))
        my = VY + int(VH * (1.0 - t))
        pygame.draw.line(surface, C_WHITE, (VX - 3, my), (VX + VW + 3, my), 3)
        pygame.draw.polygon(surface, C_WHITE,
                            [(VX - 5, my), (VX - 13, my - 6), (VX - 13, my + 6)])

    def _draw_fight_panel(self, surface: pygame.Surface) -> None:
        """ファイト表示: 右側に縦型テンションゲージ + 上部の細い情報ストリップ。

        旧・下部横長ゲージはロッドと被るため廃止。テンションは右側の縦ゲージで
        示し、テキストはロッドを隠さない上部に薄く置く。
        """
        if not self.font or not self.font_sm:
            return
        f = self.fight
        if not f:
            return

        # ── 右側: 縦型テンションゲージ ──────────────────────────────
        self._draw_tension_gauge_v(surface, f)

        # ── 上部: 細い情報ストリップ (ロッドを隠さない位置) ──────────
        SX, SY, SW, SH = 6, 150, 560, 48
        bg = pygame.Surface((SW, SH), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        surface.blit(bg, (SX, SY))
        pygame.draw.rect(surface, (60, 60, 60), (SX, SY, SW, SH), 1)

        surface.blit(self.font.render("FIGHT!", True, (255, 120, 60)), (SX + 8, SY + 4))
        surface.blit(
            self.font.render(f"Line out: {f.line_length_m:.1f} m", True, C_WHITE),
            (SX + 110, SY + 4))
        surface.blit(self.font_sm.render(f"Hook: {f.hook_quality}", True, C_GRAY),
                     (SX + 330, SY + 8))

        # 状況ヒント (1行)
        zone = f.zone
        if zone == "BLUE":
            hint = "Too slack! reel or rod DOWN"
        elif zone == "RED":
            hint = "DANGER! stop reeling / rod UP!"
        elif f.pumping:
            hint = "PUMP! reeling in fast"
        elif f.control_success:
            hint = "Good! rod against the fish"
        elif f.behavior == "RUN":
            hint = "Fish running - steer opposite"
        elif f.pump_charge > 0.0:
            hint = "Now rod UP + REEL to pump in!"
        elif f.distance <= LANDING_DIST_M:
            hint = "Hold DOWN to land the fish!"
        elif f.fish_size >= 45.0:
            hint = "Rod DOWN to load, then UP + REEL (pump)"
        else:
            hint = "Reel to gain line / arrows to steer"
        surface.blit(self.font_sm.render(hint, True, (210, 210, 210)), (SX + 8, SY + 26))

        # ── ポンピング charge バー (溜まっている時のみ) ─────────────────
        if f.pump_charge > 0.01 or f.pumping:
            pcw = int(120 * min(1.0, f.pump_charge))
            bx, by = SX + 430, SY + 30
            pygame.draw.rect(surface, (40, 40, 40), (bx, by, 120, 8))
            col = (120, 220, 255) if f.pumping else (90, 160, 210)
            pygame.draw.rect(surface, col, (bx, by, pcw, 8))
            surface.blit(self.font_sm.render("PUMP", True, col), (bx, by - 14))

        # 巻き時インジケータ: 縦ゲージの上に点滅表示
        if (zone in ("GREEN", "YELLOW") and f.behavior != "RUN"
                and f.distance > LANDING_DIST_M):
            on = (self._frame_count % 40) < 26
            rc = (90, 255, 130) if on else (50, 150, 80)
            rs = self.font_sm.render("REEL NOW!", True, rc)
            surface.blit(rs, (self._VGAUGE_X + self._VGAUGE_W // 2 - rs.get_width() // 2,
                              self._VGAUGE_Y - 22))

        # デバッグ: フックホールド / 魚の体力 / ライン負荷の内部値
        if self.debug_mode:
            ctrl = "CTRL+" if f.control_success else ("wrong" if f.wrong_dir else "-")
            dbg = self.font_sm.render(
                f"hold {f.hook_hold:.0f}/{f._hook_hold_max:.0f}   "
                f"stam {f.stamina_ratio * 100:.0f}%   "
                f"stress {f._line_stress:.0f}/{TU.FIGHT_LINE_BREAK_STRESS:.0f}   "
                f"{ctrl}",
                True, (255, 200, 80))
            surface.blit(dbg, (SX + 8, SY + SH + 4))

    # ── Sidebar ────────────────────────────────────────────────────────

    def _draw_sidebar(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(surface, C_DARK, (SIDEBAR_X, 0, SIDEBAR_W, SCREEN_H))
        pygame.draw.line(surface, C_GRAY, (SIDEBAR_X,0),(SIDEBAR_X,SCREEN_H),2)
        if not self.font: return

        title      = "DEBUG – Score" if self.debug_mode else "Underwater Map"
        title_col  = (255,200,80) if self.debug_mode else C_WHITE
        surface.blit(self.font.render(title, True, title_col), (SIDEBAR_X+10,10))

        grid_surf = self._score_surf if self.debug_mode else self._terrain_surf
        if grid_surf:
            surface.blit(grid_surf, (UW_GRID_X, UW_GRID_Y))

        # Pin-spot outlines in debug
        if self.debug_mode:
            for cy in range(UW_H):
                for cx in range(UW_W):
                    if self.uw_map.full_score(cx,cy) >= PIN_HIGH_SCORE:
                        pygame.draw.rect(surface, C_WHITE,
                            (UW_GRID_X+cx*CELL_PX, UW_GRID_Y+cy*CELL_PX, CELL_PX-1,CELL_PX-1),1)

        pygame.draw.rect(surface, C_GRAY,
            (UW_GRID_X-1,UW_GRID_Y-1,UW_W*CELL_PX+2,UW_H*CELL_PX+2),1)

        # Fish dots (reaction-stage colour)
        for fish in self.fishes:
            if fish.state == FISH_CAUGHT: continue
            fx = int(UW_GRID_X + fish.x * CELL_PX)
            fy = int(UW_GRID_Y + fish.y * CELL_PX)
            col = _REACT_COLOR.get(fish.state, C_FISH_IDLE)
            r   = 5 if fish.state == REACT_BITE else 4
            pygame.draw.circle(surface, col, (fx,fy), r)
            if fish.state == REACT_BITE:
                pygame.draw.circle(surface, C_WHITE, (fx,fy), r, 1)

        # Lure dot
        if self.lure.in_water:
            lx = int(UW_GRID_X + self.lure.x * CELL_PX)
            ly = int(UW_GRID_Y + self.lure.y * CELL_PX)
            pygame.draw.circle(surface, C_LURE, (lx,ly), 5)
            pygame.draw.circle(surface, C_WHITE, (lx,ly), 5, 1)

        # Intended dot
        if self._intended_timer > 0 and self._intended_pos:
            iux,iuy = self._intended_pos
            ix = int(UW_GRID_X + iux * CELL_PX)
            iy = int(UW_GRID_Y + iuy * CELL_PX)
            pygame.draw.circle(surface, (200,200,100), (ix,iy), 5, 1)

        info_y = UW_GRID_Y + UW_H*CELL_PX + 8
        if self.debug_mode:
            self._draw_debug_info(surface, info_y)
        else:
            self._draw_legend(surface, info_y)
            self._draw_catch_log(surface, info_y + 96)

    def _draw_legend(self, surface, base_y):
        if not self.font_sm: return
        items = [
            (C_FLAT,"Flat"),(C_WEED_CELL,"Weed"),(C_COVER_CELL,"Cover"),
            (C_BREAK_CELL,"Break"),(C_ROCK_CELL,"Rock"),
            (C_FISH_IDLE,"Ignore"),(C_FISH_NOTICE,"Notice"),
            (C_FISH_APPROACH,"Approach"),(C_FISH_ACTIVE,"Chase"),
            (C_FISH_BITE_COL,"Bite"),(C_FISH_SPOOK,"Spook"),(C_LURE,"Lure"),
        ]
        for i,(col,lbl) in enumerate(items):
            lx = SIDEBAR_X+10 + (i%2)*130
            ly = base_y + (i//2)*22
            pygame.draw.rect(surface, col, (lx,ly,12,12))
            surface.blit(self.font_sm.render(lbl,True,C_WHITE),(lx+16,ly))

    def _draw_debug_info(self, surface, base_y):
        if not self.font_sm: return
        y = base_y
        # Scale bar
        for v,lbl in [(0,"Low"),(6,"Mid"),(12,"High")]:
            col = _score_to_heat(v)
            sx  = SIDEBAR_X+10 + int(v/12*200)
            pygame.draw.rect(surface,col,(sx,y,12,12))
            surface.blit(self.font_sm.render(lbl,True,C_WHITE),(sx+14,y))
        y += 18
        hcx,hcy = self._get_hovered_grid_cell()
        if hcx is not None:
            cell  = self.uw_map.cell(hcx,hcy)
            score = self.uw_map.full_score(hcx,hcy)
            for j,(line,col) in enumerate([
                (f"Cell ({hcx},{hcy})", C_YELLOW),
                (f"  depth {cell.depth:.1f}m", C_WHITE),
                (f"  weed  {'yes' if cell.weed else 'no'}", C_WHITE),
                (f"  cover {'yes' if cell.cover else 'no'}", C_WHITE),
                (f"  bait  {cell.bait}", C_WHITE),
                (f"  score {score:.1f}", C_WHITE),
            ]):
                surface.blit(self.font_sm.render(line,True,col),(SIDEBAR_X+10,y+j*18))
        y += 6*18+6
        if self.lure.in_water:
            score = self._lure_spot_score()
            q = ("★★★ Excellent" if score >= PIN_HIGH_SCORE else
                 "★★  Good"     if score >= PIN_LOW_SCORE  else "★   Poor")
            qcol = C_GREEN if score >= PIN_HIGH_SCORE else (C_YELLOW if score >= PIN_LOW_SCORE else C_RED)
            surface.blit(self.font_sm.render("Lure spot:", True, C_WHITE),(SIDEBAR_X+10,y))
            surface.blit(self.font_sm.render(f"  {q} ({score:.1f})",True,qcol),(SIDEBAR_X+10,y+18))
        y += 44
        surface.blit(self.font_sm.render("Top 5 spots:",True,C_WHITE),(SIDEBAR_X+10,y))
        for i,(bx,by) in enumerate(self.uw_map.best_positions(5)):
            s = self.uw_map.full_score(bx,by)
            pygame.draw.rect(surface,_score_to_heat(s),(SIDEBAR_X+10,y+18+i*18,10,10))
            surface.blit(self.font_sm.render(f"  ({bx:2d},{by:2d}) {s:.1f}",True,C_WHITE),
                         (SIDEBAR_X+18,y+18+i*18))
        y += 18+5*18+8
        self._draw_terrain_debug(surface, y)
        y += 7*18+8
        self._draw_catch_log(surface, y)

    def _nearest_hotspot(self, col: int, row: int, max_cells: float = 3.0):
        """(col,row) セルに最も近い hotspot dict を返す。範囲外なら None。"""
        tr = self.terrain
        if not tr.hotspots:
            return None
        best = None
        best_d = max_cells
        for hs in tr.hotspots:
            hc = hs["x"] / tr.view_width_m * tr.grid_cols
            hr = hs["y"] / tr.view_depth_m * tr.grid_rows
            d = ((hc - col) ** 2 + (hr - row) ** 2) ** 0.5
            if d <= best_d:
                best_d = d
                best = hs
        return best

    def _draw_terrain_debug(self, surface, base_y):
        """デバッグ: terrain grid 情報 + カーソルセルの水深データ (サイドバー内)。"""
        if not self.font_sm:
            return
        from fishing_spots import get_fishing_spot
        tr = self.terrain
        spot = get_fishing_spot(self.spot_id)
        lines: list = [
            (f"Terrain: {tr.spot_id}", C_YELLOW),
            (f"  profile {spot.depth_profile}", (180, 180, 100)),
            (f"  depth   {spot.base_depth_m:.1f}–{spot.max_depth_m:.1f}m", C_WHITE),
        ]
        hcx, hcy = self._get_hovered_grid_cell()
        if hcx is not None:
            c = min(tr.grid_cols - 1, max(0, hcx))
            r = min(tr.grid_rows - 1, max(0, hcy))
            tc = tr.cell(c, r)
            slope_col = (255, 190, 40) if tc.slope > 0.35 else C_WHITE
            lines += [
                (f"  cell ({c},{r})", C_YELLOW),
                (f"  depth  {tc.depth_m:.2f}m", C_WHITE),
                (f"  slope  {tc.slope:.2f}", slope_col),
                (f"  cover  {tc.cover:.2f}", C_WHITE),
                (f"  shade  {tc.shade:.2f}", C_WHITE),
                (f"  snag   {tc.snag:.2f}", C_WHITE),
                (f"  veg    {tc.vegetation:.2f}", C_WHITE),
                (f"  hard   {tc.hardness:.2f}", C_WHITE),
                (f"  ambush {tc.ambush:.2f}", C_WHITE),
                (f"  bottom {tc.bottom_type}", (170, 170, 170)),
            ]
            hs = self._nearest_hotspot(c, r)
            if hs is not None:
                lines.append((f"  hot: {hs['kind']} {hs['score']:.2f}", (120, 220, 255)))
        else:
            lines += [("  (hover grid cell)", (100, 100, 100))]
        for j, (txt, col) in enumerate(lines):
            surface.blit(self.font_sm.render(txt, True, col), (SIDEBAR_X + 10, base_y + j * 18))

    def _draw_catch_log(self, surface, base_y):
        if not self.font or not self.font_sm: return
        surface.blit(self.font.render("Catch Log",True,C_WHITE),(SIDEBAR_X+10,base_y))
        y = base_y + 26
        # Personal best (from save_manager if available)
        if self._save_manager and self._save_manager.personal_best:
            pb_str = f"PB: {self._save_manager.personal_best_str}"
            surface.blit(self.font_sm.render(pb_str, True, C_YELLOW), (SIDEBAR_X+10, y))
            y += 20
        for i, entry in enumerate(self.catch_log[-5:]):
            s  = entry["ticks"] // 1000
            mm, ss = s // 60, s % 60
            length = entry.get("length", entry.get("size", 0.0))
            fid    = entry.get("fish_id", "")
            action = entry.get("action", "KEEP")
            prefix = f"[{fid}] " if fid else ""
            act_tag = "REL" if action == "RELEASE" else "KEP"
            line   = f"{prefix}{length:.1f}cm  {act_tag}  {entry['lure']}  {mm:02d}:{ss:02d}"
            if action == "RELEASE":
                col = (100, 180, 255)
            elif fid:
                col = (255, 200, 60)
            else:
                col = C_GREEN
            surface.blit(self.font_sm.render(line, True, col), (SIDEBAR_X+10, y+i*20))

    # ── Status panel (bottom of scene) ────────────────────────────────

    def _draw_status_panel(self, surface: pygame.Surface) -> None:
        """Lure Type / Action / Depth / Match / Fish Reaction / Bite Window."""
        if not self.font or not self.font_sm:
            return
        if self.is_mobile:
            self._draw_status_panel_mobile(surface)
            return

        # 左上に配置 (中央のロッドと重ならないように)
        PX, PY, PW, PH = 6, 36, 572, 192

        # Background
        bg = pygame.Surface((PW, PH), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 172))
        surface.blit(bg, (PX, PY))
        pygame.draw.rect(surface, (60,60,60), (PX, PY, PW, PH), 1)

        y = PY + 6

        # ── Section 1: Lure ──────────────────────────────────────────
        spec       = get_spec_by_idx(self._lure_idx)
        lure_col   = spec.color
        lure_label = f"[{self._lure_idx+1}] {spec.name}"

        surface.blit(self.font_sm.render("LURE", True, (180,180,180)), (PX+6, y))
        ls = self.font.render(lure_label, True, lure_col)
        surface.blit(ls, (PX+PW - ls.get_width() - 8, y - 2))
        y += 18

        # Action + depth
        a_col = _ACTION_COLOR.get(self.lure.action, C_GRAY)
        a_lbl = _ACTION_LABEL.get(self.lure.action, self.lure.action.upper())
        lbl_surf = self.font.render(a_lbl, True, a_col)
        surface.blit(lbl_surf, (PX+6, y))

        depth_str = f"Depth {self.lure.depth:.1f}m"
        surface.blit(self.font_sm.render(depth_str, True, C_WHITE), (PX+160, y+4))

        y += 26
        # Naturalness bar
        surface.blit(self.font_sm.render("Natural", True, C_GRAY), (PX+6, y))
        _draw_bar(surface, PX+70, y+2, 110, 10, self.lure.naturalness, (80,200,80))
        # Appeal bar
        surface.blit(self.font_sm.render("Appeal", True, C_GRAY), (PX+200, y))
        _draw_bar(surface, PX+260, y+2, 110, 10, self.lure.appeal, (220,160,40))

        y += 20
        # Lure Match row
        match     = self._lure_match()
        if match >= 0.80:
            mc = C_GREEN
        elif match >= 0.55:
            mc = C_YELLOW
        else:
            mc = C_RED
        surface.blit(self.font_sm.render("Match", True, C_GRAY), (PX+6, y))
        _draw_bar(surface, PX+60, y+2, 200, 10, match, mc)
        surface.blit(self.font_sm.render(f"{match:.0%}", True, mc), (PX+268, y))

        y += 22

        # ── Section 2: Fish Reaction ─────────────────────────────────
        pygame.draw.line(surface, (60,60,60), (PX+4,y), (PX+PW-4,y), 1)
        y += 4
        surface.blit(self.font_sm.render("FISH REACTION", True, (180,180,180)), (PX+6, y))
        y += 18

        # Sort fish by reaction priority (descending), skip caught
        visible_fish = sorted(
            [f for f in self.fishes if f.state != FISH_CAUGHT],
            key=lambda f: REACTION_PRIORITY.get(f.state, 0),
            reverse=True,
        )
        slot_w = PW // 5
        for i, fish in enumerate(visible_fish[:5]):
            sx = PX + i * slot_w + 4
            col = _REACT_COLOR.get(fish.state, C_GRAY)
            # Dot
            pygame.draw.circle(surface, col, (sx+8, y+8), 5)
            if fish.state == REACT_BITE:
                flash = (self._frame_count % 20) < 10
                if flash:
                    pygame.draw.circle(surface, C_WHITE, (sx+8, y+8), 7, 1)
            # Size
            surface.blit(
                self.font_sm.render(f"{fish.size:.0f}cm", True, C_WHITE),
                (sx+16, y),
            )
            # Stage label
            rlbl = _REACT_LABEL.get(fish.state, "?")
            surface.blit(
                self.font_sm.render(rlbl, True, col),
                (sx+4, y+16),
            )

        y += 38

        # ── Section 3: Bite Window ────────────────────────────────────
        pygame.draw.line(surface, (60,60,60), (PX+4,y), (PX+PW-4,y), 1)
        y += 4
        surface.blit(self.font_sm.render("BITE WINDOW", True, (180,180,180)), (PX+6, y))
        y += 18

        # Charge bar colour
        bc = self._bite_charge
        if bc < 0.50:
            bar_col = (50, 200, 80)
        elif bc < 0.75:
            bar_col = (230, 180, 30)
        else:
            pulse = (self._frame_count % 16) < 8
            bar_col = (255, 80, 40) if pulse else (200, 50, 20)

        _draw_bar(surface, PX+6, y, 300, 14, bc, bar_col)
        pct_str = f"{bc*100:.0f}%"
        surface.blit(self.font_sm.render(pct_str, True, C_WHITE), (PX+316, y))

        # Hint
        if bc < 0.01:
            hint = "Fish not in range"
        elif bc < 0.50:
            hint = "Pause (stop) or tap DOWN (twitch) to trigger bite"
        elif bc < BITE_TRIGGER:
            hint = "Bite incoming! Hold action!"
        else:
            hint = ""
        if hint:
            surface.blit(self.font_sm.render(hint, True, (200,200,200)), (PX+6, y+18))

    def _draw_status_panel_mobile(self, surface: pygame.Surface) -> None:
        """スマホ用簡易HUD: Lure / Match / Bite Window / Fish Reaction (最大3件)。

        左上パネルを PH≈88px に抑え、釣り場の視野を最大化する。
        Natural/Appeal バー・操作説明・5匹横並び Fish Reaction は省略。
        """
        if not self.font_sm:
            return

        PX, PY, PW, PH = 6, 36, 332, 88

        bg = pygame.Surface((PW, PH), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        surface.blit(bg, (PX, PY))
        pygame.draw.rect(surface, (60, 60, 60), (PX, PY, PW, PH), 1)

        y = PY + 5
        spec = get_spec_by_idx(self._lure_idx)

        # Row 1: ルアー名 + 深度
        lure_label = f"[{self._lure_idx + 1}] {spec.name}"
        surface.blit(self.font_sm.render(lure_label, True, spec.color), (PX + 6, y))
        if self.lure.in_water:
            ds = self.font_sm.render(f"{self.lure.depth:.1f}m", True, C_WHITE)
            surface.blit(ds, (PX + PW - ds.get_width() - 6, y))
        y += 20

        # Row 2: Match
        match = self._lure_match()
        mc = C_GREEN if match >= 0.80 else (C_YELLOW if match >= 0.55 else C_RED)
        surface.blit(self.font_sm.render("Match", True, C_GRAY), (PX + 6, y))
        _draw_bar(surface, PX + 58, y + 2, 200, 10, match, mc)
        surface.blit(self.font_sm.render(f"{match:.0%}", True, mc), (PX + 264, y))
        y += 18

        # Row 3: Bite Window
        bc = self._bite_charge
        if bc < 0.50:
            bar_col = (50, 200, 80)
        elif bc < 0.75:
            bar_col = (230, 180, 30)
        else:
            pulse = (self._frame_count % 16) < 8
            bar_col = (255, 80, 40) if pulse else (200, 50, 20)
        surface.blit(self.font_sm.render("BW", True, C_GRAY), (PX + 6, y))
        _draw_bar(surface, PX + 30, y + 2, 228, 10, bc, bar_col)
        surface.blit(self.font_sm.render(f"{bc * 100:.0f}%", True, C_WHITE), (PX + 264, y))
        y += 18

        # Row 4: Fish Reaction ドット (最大3件)
        visible_fish = sorted(
            [f for f in self.fishes if f.state != FISH_CAUGHT],
            key=lambda f: REACTION_PRIORITY.get(f.state, 0),
            reverse=True,
        )
        slot_w = 108
        for i, fish in enumerate(visible_fish[:3]):
            sx = PX + 6 + i * slot_w
            col = _REACT_COLOR.get(fish.state, C_GRAY)
            pygame.draw.circle(surface, col, (sx + 5, y + 7), 4)
            if fish.state == REACT_BITE:
                if (self._frame_count % 20) < 10:
                    pygame.draw.circle(surface, C_WHITE, (sx + 5, y + 7), 6, 1)
            rlbl = _REACT_LABEL.get(fish.state, "?")
            surface.blit(
                self.font_sm.render(f"{fish.size:.0f}cm {rlbl}", True, col),
                (sx + 13, y),
            )

    # ── HUD (top overlay + bottom hints) ─────────────────────────────

    def _draw_hud(self, surface: pygame.Surface) -> None:
        if not self.font or not self.font_sm: return

        # Spot info (top-left)
        surface.blit(self.font.render(f"[ {self.spot_name} ]", True, C_WHITE), (10,10))
        if self.spot_label and not self.is_mobile:
            surface.blit(self.font_sm.render(self.spot_label, True, C_GRAY), (10,36))

        # F4 テストモード表示
        if self._test_big_fish:
            tm = self.font_sm.render(
                "[F4 TEST] big fish spawned (52/58/64cm)", True, (255, 120, 220))
            surface.blit(tm, (10, 108))

        if not self.is_mobile:
            # State hint (PC向け操作説明)
            hints = {
                FS_IDLE:         "Arrows:Aim cast  A/D:Move footing  Hold LMB:charge, release:throw  |  1-6:lure",
                FS_CAST_CHARGE:  "Release LMB in the GREEN zone!",
                FS_RETRIEVE:     "LMB:Reel (tap=creep, mash=fast)  Arrows:Rod (v=twitch/lift ^=fall <>=steer)",
                FS_BITE:         "> Press DOWN to hookset!",
                FS_WEIGHT:       "> Weight loading... feel the tip, then set!",
                FS_LINE_RUN:     "> LINE RUNNING — Press DOWN to hookset!",
                FS_FIGHT:        "Arrows: rod control  LMB: reel  |  manage tension!",
                FS_KEEP_RELEASE: "[K] KEEP  /  [R] RELEASE",
                FS_RESULT:       "",
            }
            hint = hints.get(self.state, "")
            if hint:
                surface.blit(self.font_sm.render(hint, True, C_YELLOW), (10, 55))

            # Cast deviation
            if self._intended_timer > 0 and self._intended_pos and self.lure.in_water:
                dev = math.sqrt((self.lure.x - self._intended_pos[0])**2 +
                                (self.lure.y - self._intended_pos[1])**2)
                surface.blit(
                    self.font_sm.render(f"Cast deviation: {dev:.1f} cells", True, (200,200,100)),
                    (10, 72),
                )

        # Pin-spot quality (only when lure is in water)
        if self.lure.in_water:
            score = self._lure_spot_score()
            if score >= PIN_HIGH_SCORE:
                qlbl,qcol = "*** Excellent - large fish active", C_GREEN
            elif score >= PIN_LOW_SCORE:
                qlbl,qcol = "**  Good spot", C_YELLOW
            else:
                qlbl,qcol = "*   Poor - small fish only", C_RED
            surface.blit(self.font_sm.render(qlbl, True, qcol), (10,90))

        # ── Environment info block (top-right) ───────────────────────
        if self._env:
            act      = self._env.activity_modifier
            act_col  = (
                C_GREEN  if act >= 0.90 else
                C_YELLOW if act >= 0.60 else
                C_RED
            )
            env_rows = [
                (f"{self._env.month_day_str}  {self._env.season_label}", C_YELLOW),
                (
                    f"{self._env.weather}  "
                    f"Air:{self._env.air_temp:.0f}C  "
                    f"W:{self._env.water_temp:.0f}C",
                    self._env.weather_color,
                ),
                (f"Wind: {self._env.wind_display}  Activity:{act:.0%}", act_col),
            ]
            for i, (line, col) in enumerate(env_rows):
                ts = self.font_sm.render(line, True, col)
                surface.blit(ts, (MAIN_W - ts.get_width() - 10, 10 + i * 18))
        else:
            # Catches count (top-right, fallback)
            surface.blit(
                self.font.render(f"Catches: {len(self.catch_log)}", True, C_WHITE),
                (MAIN_W-160, 10),
            )

        # Bottom hints
        if not self.is_mobile:
            surface.blit(
                self.font_sm.render("D: debug" + (" ON" if self.debug_mode else ""), True, (170,170,170)),
                (10, SCREEN_H-42),
            )
        surface.blit(
            self.font_sm.render("ESC: back to map", True, C_GRAY),
            (10, SCREEN_H-24),
        )

        if not self.is_mobile:
            # ── Lure key strip (bottom-right area, PC only) ───────────────────────
            strip_x = 600
            strip_y = SCREEN_H - 42
            for i, spec in enumerate(LURE_CATALOG):
                is_cur = (i == self._lure_idx)
                lbl   = f"{i+1}:{spec.name[:4]}"
                col   = spec.color if is_cur else (100, 100, 100)
                ts    = self.font_sm.render(lbl, True, col)
                bx    = strip_x + i * 62
                if is_cur:
                    pygame.draw.rect(surface, (40, 40, 60), (bx - 2, strip_y - 2, ts.get_width()+4, ts.get_height()+4))
                    pygame.draw.rect(surface, spec.color,   (bx - 2, strip_y - 2, ts.get_width()+4, ts.get_height()+4), 1)
                surface.blit(ts, (bx, strip_y))

            # Second strip line: Match % for current lure
            match  = self._lure_match()
            mcol   = C_GREEN if match >= 0.80 else (C_YELLOW if match >= 0.55 else C_RED)
            cur_spec = get_spec_by_idx(self._lure_idx)
            mline  = (
                f"{cur_spec.name}  Depth {self.lure.depth:.1f}m  Match {match:.0%}"
            )
            msurf  = self.font_sm.render(mline, True, mcol)
            surface.blit(msurf, (strip_x, strip_y + 18))
