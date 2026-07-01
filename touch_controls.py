"""On-screen touch controls for mobile (pygbag) play.

The game is keyboard/mouse driven. Rather than rewrite every input site, this
overlay maps touches on virtual buttons to keyboard/mouse input:

* A directional pad drives the arrow keys. ``pygame.key.get_pressed()`` is
  wrapped so continuous-input code (player movement, cast cursor / AIM, rod
  control) sees the virtual keys held. KEYDOWN/KEYUP are also posted so discrete
  handlers fire (e.g. hook-set on ↓ during a bite).
* During FS_IDLE two top **MOVE** buttons hold A / D so the player can shift
  their footing (player_stance_x) before casting. They are hidden once a cast is
  in flight / retrieving / fighting.
* The bottom-right **context button** changes per fishing state:
  * FS_IDLE / FS_CAST_CHARGE → **CAST** (press-and-hold to charge, release to
    throw — a held left mouse button on the water).
  * FS_RETRIEVE / FS_FIGHT   → **REEL** (held left mouse button).
  * FS_BITE                  → **HOOK** (a single ↓ tap to set the hook).
* Tapping open water does **nothing** — casting only happens through the CAST
  button, so a stray screen tap can never fire a cast.

**Multi-touch:** real SDL ``FINGER*`` events are handled so several buttons can
be held at once (e.g. REEL while steering the rod with the d-pad during a
fight). Each finger is tracked independently. Desktop falls back to single
mouse-pointer handling so the overlay is still usable/testable with a mouse.
"""

from __future__ import annotations
from typing import Optional, Tuple

import pygame

from constants import (
    FS_IDLE, FS_CAST_CHARGE, FS_RETRIEVE, FS_BITE, FS_WEIGHT, FS_LINE_RUN,
    FS_FIGHT, FS_KEEP_RELEASE,
)

# Hooking v1: バイト中に HOOK タップを受け付ける状態 (巻物=BITE / ワーム系=WEIGHT,LINE_RUN)
_HOOK_STATES = {FS_BITE, FS_WEIGHT, FS_LINE_RUN}

# Synthetic pointer position for water taps driven by the CAST/REEL button: open
# water, clear of every on-screen button so the re-dispatched event reaches the
# cast/reel code rather than bouncing off the overlay again.
_REEL_POS = (640, 300)

# 右下コンテキストボタンを「押し続け＝マウス左長押し」として扱う釣り状態。
# (FS_IDLE/CAST_CHARGE=キャスト溜め, FS_RETRIEVE/FIGHT=リール)
_PRIMARY_HOLD_STATES = {FS_IDLE, FS_CAST_CHARGE, FS_RETRIEVE, FS_FIGHT}
# 右下ボタンを表示する釣り状態 (上記 + バイト時の HOOK タップ)
_PRIMARY_STATES = _PRIMARY_HOLD_STATES | _HOOK_STATES

# ルアー切替UIを表示する釣り状態 (キーボードの 1〜6 と同条件:
# アイドル/リトリーブ中のみ。溜め/バイト/ファイト中は不可)。
_LURE_STATES = {FS_IDLE, FS_RETRIEVE}


class _Button:
    def __init__(self, rect, label, key, modes=None, fish_states=None):
        self.rect = pygame.Rect(rect)
        self.label = label        # str, or dict keyed by mode
        self.key = key            # int keycode, dict keyed by mode, or None
        self.modes = modes        # None = every mode, else a set of mode names
        self.fish_states = fish_states  # None = any, else a set of FS_* states

    def visible(self, mode: str, fish_state: str) -> bool:
        if self.modes is not None and mode not in self.modes:
            return False
        if self.fish_states is not None and fish_state not in self.fish_states:
            return False
        return True

    def key_for(self, mode: str) -> int:
        return self.key[mode] if isinstance(self.key, dict) else self.key

    def label_for(self, mode: str) -> str:
        return self.label[mode] if isinstance(self.label, dict) else self.label


class TouchControls:
    def __init__(self, screen_w: int, screen_h: int):
        self.screen_w, self.screen_h = screen_w, screen_h
        self.mode = "explore"            # set by the game each frame
        self.fish_state = ""             # FishingView.state ("" when not fishing)
        self.reel_enabled = False        # 後方互換: 旧フラグ (未使用)
        self.lure_idx = 0                # 現在のルアー番号 (game が毎フレーム更新)
        self.lure_name = ""              # 現在のルアー名 (表示用)
        self.lure_count = 6              # ルアー総数

        self._held: set = set()          # arrow / A / D keycodes held via buttons
        self._action_keys: set = set()   # action keycodes currently held
        self._reel_holders: set = set()  # finger ids (or "mouse") holding CAST/REEL
        self._pressed_btns: set = set()  # action buttons pressed (for drawing)
        self._fingers: dict = {}         # finger_id -> target tuple
        self._mouse_target = None        # target tuple for the desktop mouse
        self._touch_active = False       # latched once any finger is seen

        self.font = pygame.font.Font(None, 28)

        s = 82
        # D-pad (plus layout) bottom-left.  FS_IDLE = AIM (cast cursor),
        # FS_RETRIEVE/FIGHT = rod control — same arrow keys, the game decides.
        self.dpad = [
            _Button((87, 421, s, s), "up",    pygame.K_UP),
            _Button((87, 587, s, s), "down",  pygame.K_DOWN),
            _Button((4, 504, s, s),  "left",  pygame.K_LEFT),
            _Button((170, 504, s, s), "right", pygame.K_RIGHT),
        ]
        # 足場移動 (画面上部の左右端, FS_IDLE のみ): 押下中 A / D を保持して
        # 立ち位置を動かす。左端=左へ, 右端=右へ。既存の上部HUD (左:ステータス
        # パネル / 右:環境情報) と被らない高さに置く。
        _MV = dict(modes={"fishing"}, fish_states={FS_IDLE})
        self.move_btns = [
            _Button((10, 246, 120, 54), "MOVE", pygame.K_a, **_MV),
            _Button((860, 246, 120, 54), "MOVE", pygame.K_d, **_MV),
        ]
        # Key-mapped action buttons.
        self.actions = [
            _Button((1018, 566, 96, 96), "ACT", pygame.K_e, modes={"explore"}),
            _Button((1158, 24, 84, 84), "BACK", pygame.K_ESCAPE),
            _Button((1042, 360, 84, 84), "KEEP", pygame.K_k,
                    modes={"fishing"}, fish_states={FS_KEEP_RELEASE}),
            _Button((1148, 360, 84, 84), "REL",  pygame.K_r,
                    modes={"fishing"}, fish_states={FS_KEEP_RELEASE}),
        ]
        # 右下コンテキストボタン: CAST / REEL / HOOK (状態でラベル・挙動が変わる)。
        self.primary = _Button((1146, 560, 110, 110), "CAST", None,
                               modes={"fishing"}, fish_states=_PRIMARY_STATES)
        # ルアー切替UI (画面下部中央): ◀ で前, ▶ で次のルアーへ。中央に現在名を表示。
        # key は持たず、押下時に 1〜6 キー相当のイベントを post して既存処理を再利用。
        _LU = dict(modes={"fishing"}, fish_states=_LURE_STATES)
        self.lure_prev = _Button((470, 658, 70, 60), "◀", None, **_LU)
        self.lure_next = _Button((740, 658, 70, 60), "▶", None, **_LU)
        # 名前プレートの矩形 (当たり判定なし, 描画専用) — ボタンより少し小さく中央寄せ
        self.lure_plate = pygame.Rect(548, 661, 164, 52)
        # デバッグトグル: 左上隅の小ボタン。タップで K_F2 を発火 → debug_mode をトグル。
        # modes=None / fish_states=None で常時表示。
        self.debug_btn = _Button((4, 4, 60, 36), "DBG", pygame.K_F2)
        self.debug_active: bool = False   # 毎フレーム game が FishingView.debug_mode を転写

    @property
    def _reel_held(self) -> bool:
        return bool(self._reel_holders)

    def _primary_label(self) -> str:
        s = self.fish_state
        if s in (FS_IDLE, FS_CAST_CHARGE):
            return "CAST"
        if s in _HOOK_STATES:
            return "HOOK"
        return "REEL"

    # ── input-state patches ───────────────────────────────────────────────
    def install_key_patch(self) -> None:
        """Wrap ``pygame.key.get_pressed()`` and ``pygame.mouse.get_pressed()``
        so the d-pad / MOVE buttons report held keys and CAST/REEL reports a held
        left mouse button (used by the cast-charge and fight-reel logic)."""
        real_keys = pygame.key.get_pressed
        held = self._held

        class _MergedKeys:
            def __init__(self, base):
                self._base = base

            def __getitem__(self, k):
                return bool(self._base[k]) or (k in held)

            def __len__(self):
                return len(self._base)

        pygame.key.get_pressed = lambda: _MergedKeys(real_keys())

        real_mouse = pygame.mouse.get_pressed
        tc = self

        def merged_mouse(*args, **kwargs):
            base = list(real_mouse(*args, **kwargs))
            if tc._reel_held and base:
                base[0] = True
            return tuple(base)

        pygame.mouse.get_pressed = merged_mouse

    # ── hit testing ────────────────────────────────────────────────────────
    def _resolve(self, pos) -> Tuple[str, Optional[_Button]]:
        if self.debug_btn.rect.collidepoint(pos):
            return "debug", self.debug_btn
        if (self.mode == "fishing"
                and self.primary.visible(self.mode, self.fish_state)
                and self.primary.rect.collidepoint(pos)):
            return "primary", self.primary
        for b in (self.lure_prev, self.lure_next):
            if b.visible(self.mode, self.fish_state) and b.rect.collidepoint(pos):
                return "lure", b
        for b in self.move_btns:
            if b.visible(self.mode, self.fish_state) and b.rect.collidepoint(pos):
                return "move", b
        for b in self.dpad:
            if b.rect.collidepoint(pos):
                return "dpad", b
        for b in self.actions:
            if b.visible(self.mode, self.fish_state) and b.rect.collidepoint(pos):
                return "action", b
        return "water", None

    @staticmethod
    def _post(kind, **kw):
        pygame.event.post(pygame.event.Event(kind, **kw))

    def _press(self, target, fid) -> None:
        kind = target[0]
        if kind == "dpad":
            self._held.add(target[1])
            self._post(pygame.KEYDOWN, key=target[1], mod=0, unicode="")
        elif kind == "action":
            self._action_keys.add(target[1])
            self._pressed_btns.add(target[2])
            self._post(pygame.KEYDOWN, key=target[1], mod=0, unicode="")
        elif kind == "reel":
            first = not self._reel_holders
            self._reel_holders.add(fid)
            if first:
                self._post(pygame.MOUSEBUTTONDOWN, button=1, pos=_REEL_POS,
                           synthetic=True)
        elif kind == "lure":
            # 離散操作: 押した瞬間に 1〜6 キー相当を1回分発行して切替。
            self._pressed_btns.add(target[2])
            self._post(pygame.KEYDOWN, key=target[1], mod=0, unicode="")
            self._post(pygame.KEYUP, key=target[1], mod=0)
        # "water" → 何もしない (水面タップでキャスト暴発しない)

    def _release(self, target, fid) -> None:
        kind = target[0]
        if kind == "dpad":
            self._held.discard(target[1])
            self._post(pygame.KEYUP, key=target[1], mod=0)
        elif kind == "action":
            self._action_keys.discard(target[1])
            self._pressed_btns.discard(target[2])
            self._post(pygame.KEYUP, key=target[1], mod=0)
        elif kind == "reel":
            self._reel_holders.discard(fid)
            if not self._reel_holders:
                self._post(pygame.MOUSEBUTTONUP, button=1, pos=_REEL_POS,
                           synthetic=True)
        elif kind == "lure":
            # 切替は press 時に完了済み。指/マウスを離したら押下表示を解除。
            self._pressed_btns.discard(target[2])
        # "water" → 何もしない

    def _make_target(self, pos):
        kind, b = self._resolve(pos)
        if kind == "debug":
            return ("action", b.key, b)
        if kind == "dpad":
            return ("dpad", b.key)
        if kind == "move":
            # A / D を押下保持 (d-pad と同じ機構)
            return ("dpad", b.key)
        if kind == "primary":
            if self.fish_state in _HOOK_STATES:
                # HOOK = ↓ タップ (アクションキー機構)
                return ("action", pygame.K_DOWN, b)
            # CAST / REEL = マウス左長押し
            return ("reel",)
        if kind == "lure":
            # ◀/▶ で前後のルアーへ循環。押下時の現在番号から次番号を算出し、
            # 1〜6 キー (K_1 + idx) として post → 既存の _switch_lure を再利用。
            step = -1 if b is self.lure_prev else 1
            n = max(self.lure_count, 1)
            new_idx = (self.lure_idx + step) % n
            return ("lure", pygame.K_1 + new_idx, b)
        if kind == "action":
            return ("action", b.key_for(self.mode), b)
        return ("water", pos)

    # ── event entry point ────────────────────────────────────────────────
    def handle_event(self, event: pygame.event.Event) -> bool:
        """Return True if the event was consumed."""
        t = event.type

        # Multi-touch path (phones).
        if t in (pygame.FINGERDOWN, pygame.FINGERUP, pygame.FINGERMOTION):
            self._touch_active = True
            if t == pygame.FINGERDOWN:
                pos = (event.x * self.screen_w, event.y * self.screen_h)
                target = self._make_target(pos)
                self._fingers[event.finger_id] = target
                self._press(target, event.finger_id)
            elif t == pygame.FINGERUP:
                target = self._fingers.pop(event.finger_id, None)
                if target is not None:
                    self._release(target, event.finger_id)
            return True

        # Emulated mouse from a touch is a duplicate of a FINGER event we have
        # already handled — drop it (but never drop our own synthetic events).
        if t in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            if getattr(event, "synthetic", False):
                return False
            if self._touch_active:
                return True
            return self._handle_mouse(event)

        return False

    def _handle_mouse(self, event) -> bool:
        """Single-pointer fallback for desktop (mouse)."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            target = self._make_target(event.pos)
            if target[0] == "water":
                # 水面タップではキャスト/リールしない。fishing は消費して
                # ゲーム側のキャストへ届かせない (誤爆防止); explore は素通し。
                return self.mode == "fishing"
            self._mouse_target = target
            self._press(target, "mouse")
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._mouse_target is None:
                return False
            self._release(self._mouse_target, "mouse")
            self._mouse_target = None
            return True
        return False

    # ── drawing ──────────────────────────────────────────────────────────
    def _draw_btn(self, surf, rect, pressed, enabled=True):
        if not enabled:
            fill, border = (255, 255, 255, 18), (255, 255, 255, 60)
        elif pressed:
            fill, border = (255, 255, 255, 95), (255, 255, 255, 150)
        else:
            fill, border = (255, 255, 255, 40), (255, 255, 255, 150)
        pygame.draw.rect(surf, fill, rect, border_radius=14)
        pygame.draw.rect(surf, border, rect, width=2, border_radius=14)

    def _draw_dir_icon(self, surf, b: _Button):
        r = b.rect
        cx, cy = r.centerx, r.centery
        d = 16
        tri = {
            "up":    [(cx, cy - d), (cx - d, cy + d), (cx + d, cy + d)],
            "down":  [(cx, cy + d), (cx - d, cy - d), (cx + d, cy - d)],
            "left":  [(cx - d, cy), (cx + d, cy - d), (cx + d, cy + d)],
            "right": [(cx + d, cy), (cx - d, cy - d), (cx - d, cy + d)],
        }[b.label]
        pygame.draw.polygon(surf, (255, 255, 255, 210), tri)

    def _draw_move_icon(self, surf, b: _Button):
        """足場移動ボタン: 外側端に三角矢印 + 中央に "MOVE"。"""
        r = b.rect
        cy = r.centery
        d = 11
        if b.key == pygame.K_a:   # ◀ 左
            ax = r.left + 20
            tri = [(ax - d, cy), (ax + d, cy - d), (ax + d, cy + d)]
        else:                     # ▶ 右
            ax = r.right - 20
            tri = [(ax + d, cy), (ax - d, cy - d), (ax - d, cy + d)]
        pygame.draw.polygon(surf, (255, 255, 255, 210), tri)
        self._draw_text(surf, r, "MOVE")

    def _draw_text(self, surf, rect, text):
        img = self.font.render(text, True, (255, 255, 255))
        img.set_alpha(220)
        surf.blit(img, img.get_rect(center=rect.center))

    def draw(self, screen) -> None:
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        for b in self.dpad:
            self._draw_btn(overlay, b.rect, b.key in self._held)
            self._draw_dir_icon(overlay, b)
        for b in self.move_btns:
            if not b.visible(self.mode, self.fish_state):
                continue
            self._draw_btn(overlay, b.rect, b.key in self._held)
            self._draw_move_icon(overlay, b)
        for b in self.actions:
            if not b.visible(self.mode, self.fish_state):
                continue
            self._draw_btn(overlay, b.rect, b in self._pressed_btns)
            self._draw_text(overlay, b.rect, b.label_for(self.mode))
        if self.primary.visible(self.mode, self.fish_state):
            pressed = self._reel_held or (self.primary in self._pressed_btns)
            self._draw_btn(overlay, self.primary.rect, pressed)
            self._draw_text(overlay, self.primary.rect, self._primary_label())
        self._draw_lure_switch(overlay)
        # DBG ボタン: アクティブ時はオレンジ枠で強調
        dbg_pressed = self.debug_btn in self._pressed_btns
        if self.debug_active:
            pygame.draw.rect(overlay, (255, 160, 40, 180),
                             self.debug_btn.rect, border_radius=8)
            pygame.draw.rect(overlay, (255, 200, 80, 230),
                             self.debug_btn.rect, width=2, border_radius=8)
        else:
            self._draw_btn(overlay, self.debug_btn.rect, dbg_pressed)
        self._draw_text(overlay, self.debug_btn.rect, "DBG")
        screen.blit(overlay, (0, 0))

    def _draw_lure_switch(self, surf) -> None:
        """画面下部中央のルアー切替UI: ◀ [ルアー名] ▶。"""
        if not self.lure_prev.visible(self.mode, self.fish_state):
            return
        for b in (self.lure_prev, self.lure_next):
            self._draw_btn(surf, b.rect, b in self._pressed_btns)
            r = b.rect
            cx, cy = r.centerx, r.centery
            d = 13
            if b is self.lure_prev:   # ◀
                tri = [(cx - d, cy), (cx + d, cy - d), (cx + d, cy + d)]
            else:                     # ▶
                tri = [(cx + d, cy), (cx - d, cy - d), (cx - d, cy + d)]
            pygame.draw.polygon(surf, (255, 255, 255, 210), tri)
        # 名前プレート (枠 + "LURE" 見出し + 現在名)
        self._draw_btn(surf, self.lure_plate, False)
        head = self.font.render("LURE", True, (255, 255, 255))
        head.set_alpha(150)
        surf.blit(head, head.get_rect(
            centerx=self.lure_plate.centerx, top=self.lure_plate.top + 6))
        name = self.font.render(self.lure_name or "-", True, (255, 255, 255))
        name.set_alpha(230)
        surf.blit(name, name.get_rect(
            centerx=self.lure_plate.centerx, bottom=self.lure_plate.bottom - 6))
