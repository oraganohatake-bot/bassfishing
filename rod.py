"""RodController – Beta v0.9: arrow-key rod input + dynamic rod rendering.

設計 (rod_control_and_reeling_input_design_v001.md):
  ↑ : ロッドを下げる (テンションを抜く / フォール)
  ↓ : ロッドを立てる (しゃくる / フッキング / リフト / テンション増)
  ←→: ロッドを左右へ倒す (ライン角度調整)
  キーを離すと中立位置へ自動復帰

入力値と描画値を分離する:
  rod_input_x / rod_input_y   : -1.0〜1.0 (押している間のみ非ゼロ)
  rod_visual_x / rod_visual_y : 描画用 (入力へ滑らかに追従し、離すと戻る)

ロッドアクション判定は「位置」ではなく「押下時間」で行う:
  ↓ 短押し (≤TWITCH_FRAMES) → トゥイッチ
  ↓ 長押し (>TWITCH_FRAMES) → リフト / テンション維持
  ↑ 押下                    → フォール

描画 (rod_visual_and_tension_design_v001.md):
  5〜7制御点の折れ線。bend_amount = line_tension * rod_flex。
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import pygame

from constants import (
    ACTION_IDLE, ACTION_STOP, ACTION_TWITCH, ACTION_LIFT, ACTION_FALL,
)
import tuning as TU

# 注: ロッドスタンス (Z/X/C 切替) は廃止。ライン角度はプレイヤーの立ち位置
# (FishingView.player_stance_x → rod_anchor) で作る方式へ移行。

# 調整パラメータは tuning.py に集約 (Beta v0.9 tuning notes 参照)
TWITCH_FRAMES       = TU.ROD_TWITCH_FRAMES
TWITCH_PULSE_FRAMES = TU.ROD_TWITCH_PULSE_FRAMES
STOP_WINDOW_FRAMES  = TU.ROD_STOP_WINDOW_FRAMES
RETURN_SPEED        = TU.ROD_RETURN_SPEED


class RodController:
    """十字キー入力を読み、ルアーアクションとロッド描画状態を生成する。"""

    def __init__(self) -> None:
        self.rod_input_x: float = 0.0   # -1=左 +1=右
        self.rod_input_y: float = 0.0   # -1=↑(下げる) +1=↓(立てる)
        self.rod_visual_x: float = 0.0
        self.rod_visual_y: float = 0.0

        self._down_frames: int = 0       # ↓押下継続フレーム
        self._twitch_pulse: int = 0      # トゥイッチ発火残フレーム
        self._since_last_action: int = 9999

    # ── 入力更新 ──────────────────────────────────────────────────────

    def update(self, keys) -> None:
        """毎フレーム呼び出す。keys = pygame.key.get_pressed()"""
        up    = keys[pygame.K_UP]
        down  = keys[pygame.K_DOWN]
        left  = keys[pygame.K_LEFT]
        right = keys[pygame.K_RIGHT]

        # ── ↓ 押下時間トラッキング (短押し=トゥイッチ) ──────────────
        if down:
            self._down_frames += 1
        else:
            if 0 < self._down_frames <= TWITCH_FRAMES:
                self._twitch_pulse = TWITCH_PULSE_FRAMES
            self._down_frames = 0

        if self._twitch_pulse > 0:
            self._twitch_pulse -= 1

        # ── 入力値 ──────────────────────────────────────────────────
        self.rod_input_y = 1.0 if down else (-1.0 if up else 0.0)
        self.rod_input_x = (1.0 if right else 0.0) - (1.0 if left else 0.0)

        # ── 描画値: 滑らかに追従し、離すと中立へ戻る ─────────────────
        self.rod_visual_x += (self.rod_input_x - self.rod_visual_x) * RETURN_SPEED
        self.rod_visual_y += (self.rod_input_y - self.rod_visual_y) * RETURN_SPEED

        # ── アクション猶予タイマー ────────────────────────────────────
        if up or down or left or right:
            self._since_last_action = 0
        else:
            self._since_last_action += 1

    def notify_reel(self) -> None:
        """リール操作があったことを通知 (STOP 猶予リセット)。"""
        self._since_last_action = 0

    # ── ルアーアクション決定 ──────────────────────────────────────────

    def lure_action(self) -> str:
        """現在の入力状態からルアーアクションを返す (リール操作を除く)。

        優先順位: トゥイッチパルス > ↓長押し(リフト) > ↑(フォール)
                  > 操作直後の中立(ストップ) > アイドル
        """
        if self._twitch_pulse > 0:
            return ACTION_TWITCH
        if self._down_frames > TWITCH_FRAMES:
            return ACTION_LIFT
        if self.rod_input_y < 0:
            return ACTION_FALL
        if self._since_last_action < STOP_WINDOW_FRAMES:
            return ACTION_STOP
        return ACTION_IDLE

    @property
    def steer_x(self) -> float:
        """ライン角度調整 (-1.0〜1.0)。"""
        return self.rod_input_x

    @property
    def hookset_held(self) -> bool:
        """↓が押されている (フッキング / ランディング入力)。"""
        return self.rod_input_y > 0

    def reset(self) -> None:
        """入力・描画・内部状態を完全に中立へ戻す。

        釣果後 (ランディング/KEEP/RELEASE/バラシ) や次キャスト開始時に呼ぶ。
        rod_visual_x/y も 0 に戻すことで、前回ファイトのしなり角が残らない。
        """
        self.rod_input_x = self.rod_input_y = 0.0
        self.rod_visual_x = self.rod_visual_y = 0.0
        self._down_frames = 0
        self._twitch_pulse = 0
        self._since_last_action = 9999

    # ── 描画 ──────────────────────────────────────────────────────────

    def _points(
        self,
        anchor: Tuple[int, int],
        tension: float,
        rod_flex: float,
        length: float,
        segments: int,
        target: Optional[Tuple[int, int]],
        shake: float,
    ) -> list:
        """ロッドの折れ線制御点を計算して返す (描画と座標取得で共有)。"""
        # 基本角度: まっすぐ立っている状態 (-90°=真上)。
        # ↑↓ (rod_visual_y) ←→ (rod_visual_x) を合成。バット位置(anchor)が
        # プレイヤーの立ち位置に連動するため、構え角オフセットは不要。
        base_deg = -90.0 - self.rod_visual_y * 22.0 + self.rod_visual_x * 14.0
        angle = math.radians(base_deg)

        bend_total = min(1.0, tension) * rod_flex
        # 先端ほど曲がる: ティップがターゲット (ルアー/魚) 方向へ引き込まれる
        if target is not None:
            target_a = math.atan2(target[1] - anchor[1], target[0] - anchor[0])
            diff = (target_a - angle + math.pi) % (2.0 * math.pi) - math.pi
            max_bend = math.radians(70.0)
            bend_angle = max(-max_bend, min(max_bend, diff)) * bend_total
        else:
            bend_angle = math.radians(bend_total * 60.0)
        per_seg_bend = bend_angle / segments

        seg_len = length / segments
        pts = [anchor]
        x, y = float(anchor[0]), float(anchor[1])
        a = angle
        ticks = pygame.time.get_ticks()
        for i in range(segments):
            # 先端側のセグメントほど大きく曲がる (i+1 で重み付け)
            a += per_seg_bend * (i + 1) * 0.5
            x += math.cos(a) * seg_len
            y += math.sin(a) * seg_len
            px, py = x, y
            if shake > 0.0:
                # 先端ほど大きく震える (危険シグナル)。高周波の擬似振動
                amp = shake * (i + 1) / segments
                px += math.sin(ticks * 0.09 + i * 1.7) * amp
                py += math.cos(ticks * 0.11 + i * 2.3) * amp
            pts.append((int(px), int(py)))
        return pts

    def tip_pos(
        self,
        anchor: Tuple[int, int],
        tension: float = 0.05,
        rod_flex: float = 1.0,
        length: float = 290.0,
        segments: int = 6,
        target: Optional[Tuple[int, int]] = None,
    ) -> Tuple[int, int]:
        """描画せずにロッドティップの画面座標を返す (リトリーブ先計算用)。"""
        return self._points(anchor, tension, rod_flex, length,
                            segments, target, 0.0)[-1]

    def draw(
        self,
        surface: pygame.Surface,
        anchor: Tuple[int, int],
        tension: float,
        rod_flex: float = 1.0,
        length: float = 290.0,
        segments: int = 6,
        target: Optional[Tuple[int, int]] = None,
        shake: float = 0.0,
    ) -> Tuple[int, int]:
        """ロッドを折れ線で動的描画し、ティップ座標を返す。

        anchor  : グリップ位置 (画面座標)
        tension : 0.0〜1.0 ラインテンション → 曲がり量
        target  : 引っ張られる先 (ルアー/魚の画面座標)。None なら従来の固定方向
        shake   : 振動振幅 (px)。高テンション警告でロッドが震える
        """
        pts = self._points(anchor, tension, rod_flex, length,
                           segments, target, shake)

        # ロッド本体 (グリップ側を太く)
        for i in range(len(pts) - 1):
            w = 5 if i == 0 else (4 if i <= 2 else 2)
            color = (60, 40, 25) if i == 0 else (120, 90, 55)
            pygame.draw.line(surface, color, pts[i], pts[i + 1], w)

        # 高テンション警告: ティップ震え表現 (赤マーク)
        if tension > 0.9:
            tip = pts[-1]
            pygame.draw.circle(surface, (255, 60, 40), tip, 4, 1)

        return pts[-1]
