"""Lure – Minnow physics and action system.

Actions
-------
IDLE     : just cast, sitting still – sinks slowly
RETRIEVE : LMB hold – moves toward player at fixed depth
STOP     : S key – pauses and slowly sinks (best feeding window)
TWITCH   : A key – sharp darting impulse then still
LIFT     : W key – rises in the water column
FALL     : Q key – free-falls toward bottom

Each action has its own depth delta, base appeal, and naturalness baseline.
Naturalness decays the longer the same action is held; appeal = f(naturalness).
"""

from __future__ import annotations

from typing import Optional

from constants import (
    UW_SIZE, UW_W, UW_H,
    ACTION_IDLE, ACTION_RETRIEVE, ACTION_STOP,
    ACTION_TWITCH, ACTION_LIFT, ACTION_FALL,
)
import tuning as TU

# Per-action physics & attractiveness config
# depth_d  : metres per frame (positive = sinks, negative = rises)
# depth_cap: natural depth ceiling (IDLE/STOP stop sinking here)
# base_apl : base appeal  0-1
# base_nat : base naturalness 0-1 (resets here on action change)
# nat_decay: naturalness lost per frame (× action_timer)
_CFG: dict = {
    ACTION_IDLE:     dict(depth_d=+0.005, depth_cap=1.5,  base_apl=0.20, base_nat=0.55, nat_decay=0.00060),
    ACTION_RETRIEVE: dict(depth_d= 0.000, depth_cap=0.9,  base_apl=0.45, base_nat=0.72, nat_decay=0.00055),
    ACTION_STOP:     dict(depth_d=+0.007, depth_cap=2.8,  base_apl=0.68, base_nat=0.88, nat_decay=0.00040),
    ACTION_TWITCH:   dict(depth_d= 0.000, depth_cap=1.2,  base_apl=0.85, base_nat=0.75, nat_decay=0.00280),
    ACTION_LIFT:     dict(depth_d=-0.014, depth_cap=0.15, base_apl=0.52, base_nat=0.68, nat_decay=0.00160),
    ACTION_FALL:     dict(depth_d=+0.016, depth_cap=4.0,  base_apl=0.74, base_nat=0.80, nat_decay=0.00090),
}

RETRIEVE_SPEED = TU.REEL_RETRIEVE_SPEED   # cells per frame (y advance toward player)


class Lure:
    """Lure physics.  x/y in UnderwaterMap cell units.  y=0 far shore, y=31 player.

    lure_type controls depth behaviour:
      "Topwater"  → depth clamped to surface (≤ 0.08 m)
      all others  → standard per-action depth physics
    """

    PLAYER_Y = float(UW_H - 1)

    def __init__(self, lure_type: str = "Minnow") -> None:
        self.lure_type: str = lure_type

        self.x: float = 0.0
        self.y: float = 0.0
        self.depth: float = 0.3        # metres below surface
        self.speed: float = 0.0        # horizontal movement (cells/frame)
        self.in_water: bool = False

        self.action: str = ACTION_IDLE
        self.action_timer: int = 0     # frames spent in current action
        self.action_changed: bool = False

        self.naturalness: float = 0.55
        self.appeal: float = 0.20

        # Beta v0.9: リール速度倍率 (1.0=通常巻き, <1=チョイ巻き, >1=早巻き)
        self.retrieve_mult: float = 1.0
        # Beta v0.9: ライン角度ステア (-1.0〜1.0; ←→入力)
        # 横移動は竿先の可動分のみ: base_x からのオフセットを ±ROD_STEER_MAX に制限。
        # ↓入力 (LIFT/TWITCH) の手前移動は y 側の既存物理で表現される。
        self.steer_x: float = 0.0
        self._base_x: float = 0.0      # ステア基準位置
        self._steer_off: float = 0.0   # 現在の横オフセット
        # リトリーブ時にルアーが寄っていく目標 x (立ち位置アンカーの列)。
        # None ならキャスト地点の列を維持 (従来挙動)。
        self.retrieve_target_x: Optional[float] = None
        # キャスト着水点 (リトリーブ直線の始点)。cast() で確定。
        self.retrieve_start_x: float = 0.0
        self.retrieve_start_y: float = 0.0
        # ステアで蓄積したコース横ずれ (直線アンカーを横へ平行移動させる)。
        self._course_off: float = 0.0

        # ラインスラック (糸ふけ, m)。ロッドで引いた分はロッドが戻ると弛む。
        # 弛みがある間: リール=回収のみ / トゥイッチ・リフト=効かない
        self.slack: float = 0.0
        self._lift_rise: float = 0.0   # 現在のリフトで引き上げた深度 (m)
        self._lift_pull: float = 0.0   # 現在のリフトで寄せた距離 (セル≒m)

    # ── Beta v0.96: ライン長 / スラック / エフェクティブテンション ──────

    @property
    def slack_m(self) -> float:
        """ラインスラック量 (m)。self.slack の正式名 (後方互換のため別名)。"""
        return self.slack

    @property
    def line_out_m(self) -> float:
        """実際に出ているライン長 (m) = プレイヤー(y=31)からルアーまでの y距離。

        リールだけがこれを縮められる (まずスラックを取り、その後 y を寄せる)。
        ロッド操作 (トゥイッチ/リフト/フォール) では変化しない。
        """
        return max(0.0, self.PLAYER_Y - self.y) * TU.LINE_METERS_PER_CELL

    @property
    def effective_tension(self) -> float:
        """張っているライン量 (m) = max(0, line_out_m - slack_m)。

        スラックが大きいほどテンション伝達が落ちる。バイト/フッキング品質に影響。
        """
        return max(0.0, self.line_out_m - self.slack_m)

    # ── Public ─────────────────────────────────────────────────────────

    def cast(self, uw_x: float, uw_y: float) -> None:
        self.x = float(uw_x)
        self.y = float(uw_y)
        self._base_x = float(uw_x)
        self._steer_off = 0.0
        self._course_off = 0.0
        # 着水点を直線リトリーブの始点として確定
        self.retrieve_start_x = float(uw_x)
        self.retrieve_start_y = float(uw_y)
        self.retrieve_target_x = None
        self.slack = 0.0
        self._lift_rise = 0.0
        self._lift_pull = 0.0
        self.depth = 0.30
        self.speed = 0.0
        self.in_water = True
        self._reset_action(ACTION_IDLE)

    def set_action(self, action: str) -> None:
        """Call once per frame from FishingView before update()."""
        if action != self.action:
            # ロッドが戻る → 引いていた分のラインが弛む
            if self.action == ACTION_LIFT:
                pulled = self._lift_rise + self._lift_pull
                if pulled > 0:
                    self.slack = min(TU.LINE_SLACK_MAX, self.slack + pulled)
                self._lift_rise = 0.0
                self._lift_pull = 0.0
            elif self.action == ACTION_TWITCH:
                self.slack = min(TU.LINE_SLACK_MAX,
                                 self.slack + TU.LINE_SLACK_TWITCH)
            self.action_changed = True
            self._reset_action(action)
        else:
            self.action_changed = False

    def update(self) -> bool:
        """Apply per-frame physics.  Returns True when lure reaches player side."""
        if not self.in_water:
            return False

        cfg = _CFG[self.action]
        self.action_timer += 1

        # ── Depth ──
        raw = self.depth + cfg["depth_d"]
        cap = cfg["depth_cap"]
        if cfg["depth_d"] > 0:                     # sinking
            # cap より既に深い場合は維持 (上方向へスナップしない)
            if self.depth < cap:
                old = self.depth
                self.depth = min(raw, min(cap, 4.0))
                # 沈下中は糸を送る = 糸ふけが出る
                self.slack = min(
                    TU.LINE_SLACK_MAX,
                    self.slack + (self.depth - old) * TU.LINE_SLACK_SINK_FACTOR,
                )
        elif cfg["depth_d"] < 0:                   # rising (LIFT)
            if self.slack >= 0.1:
                # 弛んでいる間は竿を立てても糸ふけが取れるだけ
                self.slack = max(0.0, self.slack - TU.LINE_SLACK_ROD_TAKEUP)
            elif self._lift_rise < TU.ROD_LIFT_MAX_RISE_M:
                # 竿先の移動分だけ引き上げられる (押しっぱなしでは続かない)
                old = self.depth
                self.depth = max(raw, max(cap, 0.10))
                self._lift_rise += old - self.depth
        else:
            # RETRIEVE/TWITCH: 現在レンジを維持 (レンジコントロール)。
            # cap より深い場合のみゆっくり浮上 (即スナップしない)
            if self.depth > cap:
                self.depth = max(cap, self.depth - TU.REEL_RISE_RATE)

        # ── Horizontal movement ──
        if self.action == ACTION_RETRIEVE:
            if self.slack > 0.0:
                # まず糸ふけを回収する。回収し終えるまでルアーは動かない
                self.slack = max(
                    0.0,
                    self.slack - TU.LINE_SLACK_REEL_TAKEUP * self.retrieve_mult,
                )
                self.speed = 0.0
            else:
                spd = RETRIEVE_SPEED * self.retrieve_mult
                self.y += spd
                self.speed = spd
                if self.y >= self.PLAYER_Y:
                    self.in_water = False
                    return True
        elif self.action == ACTION_TWITCH:
            # Beta v0.96: ロッド操作は回収ではない。トゥイッチはその場で跳ねる
            # アクションのみ (line_out_m は動かさない)。弛みは set_action で出る。
            self.speed = 0.0
        elif self.action == ACTION_LIFT:
            # Beta v0.96: リフトもルアーを手前へは寄せない。竿先で水中のルアーを
            # 持ち上げる (深度 rise) だけ。寄せはリール専任。
            self.speed = 0.0
        else:
            self.speed = 0.0

        # Beta v0.9: ←→ ライン角度調整。横移動は竿先の可動分 (±ROD_STEER_MAX) のみ。
        if self.steer_x != 0.0:
            self._steer_off = max(
                -TU.ROD_STEER_MAX,
                min(TU.ROD_STEER_MAX,
                    self._steer_off + self.steer_x * TU.ROD_STEER_SPEED),
            )
        # 前進中はステアがコースへ吸収される (= 巻きながらコースを曲げられる)。
        # 吸収分はアンカー側の横ずれ (_course_off) に積み、直線を平行移動させる。
        if self.speed > 0 and self._steer_off != 0.0:
            shift = self._steer_off * min(1.0, self.speed * 6.0) * 0.05
            self._course_off += shift
            self._steer_off  -= shift

        # v0.95: 直線リトリーブ。
        # 着水点 (retrieve_start) → 立ち位置アンカー (retrieve_target) を結ぶ直線上を、
        # y方向の進捗 progress で線形補間する。横だけ後から収束させない。
        if self.retrieve_target_x is not None:
            anchor_x = self.retrieve_target_x + self._course_off
            start_x  = self.retrieve_start_x
            span_y   = self.PLAYER_Y - self.retrieve_start_y
            if span_y > 1e-6:
                progress = max(0.0, min(1.0,
                                        (self.y - self.retrieve_start_y) / span_y))
            else:
                progress = 1.0
            self._base_x = start_x + (anchor_x - start_x) * progress

        self.x = max(0.0, min(float(UW_W - 1), self._base_x + self._steer_off))

        # ── Topwater: keep lure at surface ──
        if self.lure_type == "Topwater":
            self.depth = min(self.depth, 0.08)

        # ── Naturalness decay ──
        base = cfg["base_nat"]
        self.naturalness = max(0.10, base - self.action_timer * cfg["nat_decay"])

        # ── Appeal ──
        # TWITCH gets a freshness spike in the first 10 frames
        if self.action == ACTION_TWITCH and self.action_timer <= 10:
            fresh = 1.40
        elif self.action_changed:
            fresh = 1.10
        else:
            fresh = 1.00
        self.appeal = min(1.0, cfg["base_apl"] * self.naturalness * fresh)

        return False

    def reset(self) -> None:
        self.in_water = False
        self.x = 0.0
        self.y = 0.0
        self._base_x = 0.0
        self._steer_off = 0.0
        self._course_off = 0.0
        self.retrieve_start_x = 0.0
        self.retrieve_start_y = 0.0
        self.retrieve_target_x = None
        self.slack = 0.0
        self._lift_rise = 0.0
        self._lift_pull = 0.0
        self.depth = 0.08 if self.lure_type == "Topwater" else 0.30
        self.speed = 0.0
        self._reset_action(ACTION_IDLE)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _reset_action(self, action: str) -> None:
        self.action = action
        self.action_timer = 0
        self.naturalness = _CFG[action]["base_nat"]
        self.appeal = _CFG[action]["base_apl"]
