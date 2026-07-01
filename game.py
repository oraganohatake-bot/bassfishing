"""Game – top-level state machine and main loop.

Phase 4 additions
-----------------
* SaveManager for JSON persistence (saves/save_data.json)
* F5: manual save   F9: load
* Auto-save on every catch (handled inside FishingView._hook)
* Spot discovery: first time the player stands near a spot it is saved
* In-game clock (1 game-minute = 60 real frames)
* "Saved!" / "Loaded!" flash messages on screen
* Personal best displayed on explore HUD

Phase 5 additions
-----------------
* Environment simulation (season, weather, temperature, wind)
* Fishing hours 04:00–21:00; at 21:00 clock wraps to next day 04:00
* Environment state saved/loaded via SaveManager
* Explore HUD shows date / season / weather / temps / wind
"""

from __future__ import annotations
import asyncio
from typing import Optional, Tuple

import pygame

from constants import (
    SCREEN_W, SCREEN_H, TILE_SIZE, FPS,
    ST_EXPLORE, ST_FISHING,
    FS_RETRIEVE, FS_FIGHT,
    C_LAND, C_BLACK, C_WHITE, C_YELLOW, C_GRAY, C_GREEN, C_RED,
)
from player import Player
from lake_map import LakeMap
from fishing_view import FishingView
from save_manager import SaveManager
from environment import Environment
from fish_population import FishPopulationManager
from npc_manager import NPCManager
from touch_controls import TouchControls
from lure_catalog import LURE_NAMES

# ── In-game clock rate ───────────────────────────────────────────────
_FRAMES_PER_GAME_MINUTE = 60   # 1 real second = 1 game minute

# ── Flash message duration (frames) ─────────────────────────────────
_FLASH_DURATION = 150


class Game:
    """Owns the window, clock, and global state transitions."""

    PLAYER_START = (25, 38)

    def __init__(self):
        pygame.init()
        # IME (日本語変換) を無効化: キー入力で変換候補ウィンドウが出ないように
        # WASM (pygbag) では未実装で例外になりうるため防御的に呼ぶ
        try:
            pygame.key.stop_text_input()
        except Exception:
            pass
        pygame.display.set_caption("Bass RPG  –  Beta v0.9")
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        self.clock  = pygame.time.Clock()
        self.font       = pygame.font.Font(None, 28)
        self.font_sm    = pygame.font.Font(None, 22)
        self.font_title = pygame.font.Font(None, 52)

        self.state = ST_EXPLORE
        self.lake_map = LakeMap()
        self.player   = Player(*self.PLAYER_START)
        self.fishing_view: Optional[FishingView] = None
        self._near_spot = None
        self.running    = True

        # ── Save / load ─────────────────────────────────────────────
        self.save_manager = SaveManager()

        # ── Environment ──────────────────────────────────────────────
        self.env = Environment(rng_seed=7)

        # ── Phase 7: Fish Population ──────────────────────────────────
        self.population = FishPopulationManager(rng_seed=99)

        # ── Phase 11: NPC Manager ────────────────────────────────────
        self.npc_manager = NPCManager()

        # ── Touch controls (mobile / pygbag) ─────────────────────────
        self.touch = TouchControls(SCREEN_W, SCREEN_H)
        self.touch.install_key_patch()

        # ── Debug overlays ────────────────────────────────────────────
        self._show_pop_debug: bool = False
        self._show_npc_debug: bool = False

        # ── Beta v0.9: F4 大型魚テストモード ──────────────────────────
        self._test_big_fish: bool = False

        # ── NPC dialog state ──────────────────────────────────────────
        self._npc_dialog_active: bool = False
        self._npc_dialog_npc = None       # NPCIndividual | None
        self._npc_dialog_lines: list = []
        self._near_npc = None             # NPCIndividual | None

        self._try_load_on_start()

        # ── In-game clock accumulator ────────────────────────────────
        self._clock_accum: int = 0

        # ── Flash message ─────────────────────────────────────────────
        self._flash_msg:   str = ""
        self._flash_timer: int = 0
        self._flash_color: tuple = C_GREEN

        # ── Catch-sync: detect new catches from FishingView ───────────
        self._last_catch_count: int = 0

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main loop. async so it works under pygbag (WebAssembly) too.

        Each frame yields control with `await asyncio.sleep(0)`, which is a
        no-op on desktop but is required for the browser event loop.
        """
        while self.running:
            self._handle_events()
            self._update()
            self._draw()
            self.clock.tick(FPS)
            await asyncio.sleep(0)
        pygame.quit()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            # On-screen touch buttons get first crack; consumed events
            # (taps on a virtual button) must not also reach cast/reel logic.
            if self.touch.handle_event(event):
                continue

            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self._npc_dialog_active:
                        self._close_npc_dialog()
                    elif self.state == ST_FISHING:
                        self._exit_fishing()
                    else:
                        self.running = False

                elif event.key == pygame.K_e and self.state == ST_EXPLORE:
                    if self._npc_dialog_active:
                        self._close_npc_dialog()
                    elif self._near_npc:
                        self._open_npc_dialog(self._near_npc)
                    elif self._near_spot:
                        self._enter_fishing(self._near_spot)

                elif event.key == pygame.K_F2:
                    self._show_pop_debug = not self._show_pop_debug

                elif event.key == pygame.K_F3:
                    self._show_npc_debug = not self._show_npc_debug

                elif event.key == pygame.K_F4:
                    self._test_big_fish = not self._test_big_fish
                    if self._test_big_fish:
                        self._flash("BIG FISH TEST MODE ON  (next fishing spawns 52/58/64cm)",
                                    (255, 120, 220))
                    else:
                        self._flash("Big fish test mode OFF", C_GRAY)

                elif event.key == pygame.K_F5:
                    self._manual_save()

                elif event.key == pygame.K_F9:
                    self._manual_load()

            if self.state == ST_FISHING and self.fishing_view:
                result = self.fishing_view.handle_event(event)
                if result == "exit_fishing":
                    self._exit_fishing()

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def _update(self) -> None:
        # ── In-game clock ────────────────────────────────────────────
        self._clock_accum += 1
        if self._clock_accum >= _FRAMES_PER_GAME_MINUTE:
            self._clock_accum = 0
            self.save_manager.advance_minutes(1)
            # Update environment each game-minute
            self.env.update(self.save_manager.game_minutes)
            # Wrap 21:00 → next day 04:00
            within_day = self.save_manager.game_minutes % 1440
            if within_day >= 21 * 60:  # 1260 minutes
                day_num = self.save_manager.game_minutes // 1440
                self.save_manager.game_minutes = (day_num + 1) * 1440 + 4 * 60
                self.env.advance_day()
                # Phase 7: 翌日の自然補充
                new_fish = self.population.daily_replenish(
                    self.lake_map.all_spot_names()
                )
                # Phase 9.5: 日次成長
                self.population.update_growth()
                # Phase 9: 日次記憶更新 (忘却 + 警戒心減衰)
                self.population.update_memory()
                # Phase 11: NPC日次観測
                self.npc_manager.daily_observe(
                    self.population, self.env, day_num + 2
                )
                msg = f"Day {day_num + 2}  04:00 — New day!"
                if new_fish:
                    msg += f"  ({len(new_fish)} fish spawned)"
                self._flash(msg, C_YELLOW)

        # ── Flash timer ──────────────────────────────────────────────
        if self._flash_timer > 0:
            self._flash_timer -= 1

        if self.state == ST_EXPLORE:
            if not self._npc_dialog_active:
                keys = pygame.key.get_pressed()
                self.player.handle_input(keys, self.lake_map)
            self.player.update()
            self._near_npc = self.npc_manager.get_nearby_npc(
                self.player.tile_x, self.player.tile_y
            )
            # NPCが近くにいる場合は釣りポイントチェックをスキップ
            if self._near_npc:
                self._near_spot = None
            else:
                self._near_spot = self.lake_map.get_nearby_spot(
                    self.player.tile_x, self.player.tile_y
                )
            # Spot discovery
            if self._near_spot:
                _, _, name = self._near_spot
                if self.save_manager.discover_spot(name):
                    self._flash(f"Discovered: {name}", C_YELLOW)
            pygame.mouse.set_visible(True)

        elif self.state == ST_FISHING and self.fishing_view:
            self.fishing_view.update()
            # Sync new catches (auto-saved inside _hook; we just track count)
            new_count = len(self.fishing_view.catch_log)
            if new_count > self._last_catch_count:
                self._last_catch_count = new_count
            pygame.mouse.set_visible(True)

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        if self.state == ST_EXPLORE:
            self.screen.fill(C_LAND)
            cam_x, cam_y = self._camera()
            self.lake_map.draw(self.screen, cam_x, cam_y)
            self._draw_npcs(cam_x, cam_y)
            self.player.draw(self.screen, cam_x, cam_y)
            self._draw_explore_hud(cam_x, cam_y)
            if self._npc_dialog_active and self._npc_dialog_npc:
                self._draw_npc_dialog()

        elif self.state == ST_FISHING and self.fishing_view:
            self.screen.fill(C_BLACK)
            self.fishing_view.is_mobile = self.touch._touch_active
            self.fishing_view.draw(self.screen)

        # F2: 大型魚一覧デバッグオーバーレイ
        if self._show_pop_debug:
            self._draw_population_debug()

        # F3: NPC デバッグオーバーレイ
        if self._show_npc_debug:
            self._draw_npc_debug()

        # Touch controls overlay (on top of the world, under flash text)
        self.touch.mode = "fishing" if self.state == ST_FISHING else "explore"
        self.touch.fish_state = (
            self.fishing_view.state
            if (self.state == ST_FISHING and self.fishing_view) else ""
        )
        self.touch.reel_enabled = bool(
            self.state == ST_FISHING and self.fishing_view
            and self.fishing_view.state in (FS_RETRIEVE, FS_FIGHT)
        )
        if self.state == ST_FISHING and self.fishing_view:
            self.touch.lure_idx = self.fishing_view._lure_idx
            self.touch.lure_name = LURE_NAMES[self.fishing_view._lure_idx]
            self.touch.lure_count = len(LURE_NAMES)
        self.touch.draw(self.screen)

        # Flash message (on top of any screen)
        if self._flash_timer > 0 and self._flash_msg:
            alpha = min(255, self._flash_timer * 4)
            surf  = self.font.render(self._flash_msg, True, self._flash_color)
            bg    = pygame.Surface((surf.get_width() + 20, surf.get_height() + 10),
                                   pygame.SRCALPHA)
            bg.fill((0, 0, 0, min(200, alpha)))
            bx = SCREEN_W // 2 - bg.get_width() // 2
            by = SCREEN_H - 80
            self.screen.blit(bg,  (bx, by))
            self.screen.blit(surf, (bx + 10, by + 5))

        pygame.display.flip()

    def _draw_explore_hud(self, cam_x: int, cam_y: int) -> None:
        # ── Left column: time, env, stats ──────────────────────────────
        # In-game time + date
        time_str  = f"{self.save_manager.time_display}   {self.env.month_day_str}"
        time_surf = self.font.render(time_str, True, C_WHITE)
        _draw_box(self.screen, time_surf, 10, 10, pad=6)

        # Season + weather row
        season_str  = f"{self.env.season_label}  |  {self.env.weather}"
        season_surf = self.font_sm.render(season_str, True, self.env.weather_color)
        _draw_box(self.screen, season_surf, 10, 46, pad=5)

        # Temperature row
        temp_str  = (
            f"Air: {self.env.air_temp:.0f}C   "
            f"Water: {self.env.water_temp:.0f}C   "
            f"Wind: {self.env.wind_display}"
        )
        temp_surf = self.font_sm.render(temp_str, True, (180, 220, 255))
        _draw_box(self.screen, temp_surf, 10, 65, pad=5)

        # Discovered spots count
        disc_str  = f"Spots: {len(self.save_manager.discovered_spots)}/10"
        disc_surf = self.font_sm.render(disc_str, True, C_GRAY)
        _draw_box(self.screen, disc_surf, 10, 84, pad=5)

        # Total catches
        catch_str  = f"Catches: {self.save_manager.total_catches}"
        catch_surf = self.font_sm.render(catch_str, True, C_GRAY)
        _draw_box(self.screen, catch_surf, 10, 103, pad=5)

        # ── Right column: personal best + activity ──────────────────
        pb_str  = f"PB: {self.save_manager.personal_best_str}"
        pb_surf = self.font_sm.render(pb_str, True, C_YELLOW)
        bx = SCREEN_W - pb_surf.get_width() - 20
        _draw_box(self.screen, pb_surf, bx, 10, pad=5)

        # Activity modifier display
        act      = self.env.activity_modifier
        act_col  = (
            C_GREEN  if act >= 0.90 else
            C_YELLOW if act >= 0.60 else
            C_RED
        )
        act_str  = f"Fish Activity: {act:.0%}"
        act_surf = self.font_sm.render(act_str, True, act_col)
        bx2 = SCREEN_W - act_surf.get_width() - 20
        _draw_box(self.screen, act_surf, bx2, 30, pad=5)

        # F4 テストモード常時表示
        if self._test_big_fish:
            tm_surf = self.font_sm.render("[F4 TEST MODE]", True, (255, 120, 220))
            bx3 = SCREEN_W - tm_surf.get_width() - 20
            _draw_box(self.screen, tm_surf, bx3, 50, pad=5)

        # ── Controls reminder ─────────────────────────────────────────
        ctrl = self.font_sm.render(
            "WASD: Move   E: Talk/Fish   F2: Pop   F3: NPC   F4: BigFishTest   F5: Save   F9: Load   ESC: Quit",
            True, (210, 210, 210),
        )
        self.screen.blit(ctrl, (10, SCREEN_H - 24))

        # ── NPC proximity hint ────────────────────────────────────────
        if self._near_npc and not self._npc_dialog_active:
            npc = self._near_npc
            color = npc.color
            today = self.save_manager.game_day
            can_t = npc.can_talk_today(today)
            label = f"Talk [E]  →  {npc.name} ({npc.type_label})"
            if not can_t:
                label += "  ※ 今日は話した"
            txt = self.font.render(label, True, color)
            tw = txt.get_width()
            bx = SCREEN_W // 2 - tw // 2 - 10
            by = SCREEN_H - 66
            pygame.draw.rect(self.screen, C_BLACK, (bx, by, tw + 20, 34))
            pygame.draw.rect(self.screen, color, (bx, by, tw + 20, 34), 2)
            self.screen.blit(txt, (bx + 10, by + 6))

        # ── Fishing spot hint ─────────────────────────────────────────
        elif self._near_spot:
            _, _, name = self._near_spot
            discovered = name in self.save_manager.discovered_spots
            badge = "* " if discovered else ""
            txt = self.font.render(f"Press  E  ->  {badge}{name}", True, C_YELLOW)
            tw = txt.get_width()
            bx = SCREEN_W // 2 - tw // 2 - 10
            by = SCREEN_H - 66
            pygame.draw.rect(self.screen, C_BLACK, (bx, by, tw + 20, 34))
            pygame.draw.rect(self.screen, C_YELLOW, (bx, by, tw + 20, 34), 2)
            self.screen.blit(txt, (bx + 10, by + 6))

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _camera(self) -> Tuple[int, int]:
        cx = int(self.player.px - SCREEN_W // 2 + TILE_SIZE // 2)
        cy = int(self.player.py - SCREEN_H // 2 + TILE_SIZE // 2)
        max_cx = self.lake_map.width  * TILE_SIZE - SCREEN_W
        max_cy = self.lake_map.height * TILE_SIZE - SCREEN_H
        cx = max(0, min(cx, max_cx))
        cy = max(0, min(cy, max_cy))
        return cx, cy

    def _enter_fishing(self, spot: tuple) -> None:
        sx, sy, name = spot
        seed = sx * 97 + sy * 31 + 1
        fv = FishingView(
            name, seed=seed,
            save_manager=self.save_manager,
            environment=self.env,
            fish_population=self.population,
            test_big_fish=self._test_big_fish,
        )
        fv.init_fonts()
        self.fishing_view = fv
        self._last_catch_count = 0
        self.state = ST_FISHING

    def _exit_fishing(self) -> None:
        self.fishing_view = None
        self.state = ST_EXPLORE

    # ------------------------------------------------------------------
    # Save / load
    # ------------------------------------------------------------------

    def _try_load_on_start(self) -> None:
        """Silently load save data at startup (no flash)."""
        if self.save_manager.load():
            tx, ty = self.save_manager.player_tile
            self.player.teleport(tx, ty)
            if self.save_manager.env_state:
                self.env.from_dict(self.save_manager.env_state)
            if self.save_manager.population_state:
                self.population.from_dict(self.save_manager.population_state)
            if self.save_manager.npc_state:
                self.npc_manager.from_dict(self.save_manager.npc_state)

    def _manual_save(self) -> None:
        ok = self.save_manager.save(
            player_tile=[self.player.tile_x, self.player.tile_y],
            env_state=self.env.to_dict(),
            population_state=self.population.to_dict(),
            npc_state=self.npc_manager.to_dict(),
        )
        if ok:
            self._flash("Saved!", C_GREEN)
        else:
            self._flash("Save failed!", C_RED)

    def _manual_load(self) -> None:
        # Exit fishing first if needed
        if self.state == ST_FISHING:
            self._exit_fishing()
        ok = self.save_manager.load()
        if ok:
            tx, ty = self.save_manager.player_tile
            self.player.teleport(tx, ty)
            if self.save_manager.env_state:
                self.env.from_dict(self.save_manager.env_state)
            if self.save_manager.population_state:
                self.population.from_dict(self.save_manager.population_state)
            if self.save_manager.npc_state:
                self.npc_manager.from_dict(self.save_manager.npc_state)
            self._flash("Loaded!", C_YELLOW)
        else:
            self._flash("No save data found.", C_GRAY)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _draw_population_debug(self) -> None:
        """F2 デバッグ: 大型魚個体一覧オーバーレイ (Phase 9: 記憶・レジェンド表示)。"""
        individuals = self.population.all_individuals_sorted()

        PW, PH = 680, min(56 + len(individuals) * 20 + 20, SCREEN_H - 60)
        PX, PY = SCREEN_W // 2 - PW // 2, 60

        bg = pygame.Surface((PW, PH), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 210))
        self.screen.blit(bg, (PX, PY))
        pygame.draw.rect(self.screen, C_YELLOW, (PX, PY, PW, PH), 2)

        title = self.font.render(
            f"[F2] Large Fish Population  ({self.population.total_managed} total)",
            True, C_YELLOW,
        )
        self.screen.blit(title, (PX + 10, PY + 8))

        header = self.font_sm.render(
            "  ID         Size(cur/max)   Age  Cau  Rel  Caught  Legend",
            True, C_GRAY,
        )
        self.screen.blit(header, (PX + 6, PY + 30))

        if not individuals:
            none_s = self.font_sm.render("  (no large fish in population)", True, C_GRAY)
            self.screen.blit(none_s, (PX + 6, PY + 50))
            return

        for i, fi in enumerate(individuals):
            y = PY + 50 + i * 20
            if y + 18 > PY + PH:
                break
            # 色: 60cm以上=金, 50cm以上=オレンジ, それ以外=白
            if fi.legend_candidate:
                col = (255, 215, 0)
            elif fi.length >= 50:
                col = (255, 160, 40)
            else:
                col = C_WHITE

            legend_mark = "★" if fi.legend_candidate else "-"
            max_s = fi.genetic_max_size if fi.genetic_max_size > 0 else fi.length
            hist  = self.population.get_history(fi.fish_id)
            total_c = hist.total_catches if hist else 0
            line = (
                f"  {fi.fish_id:<8}  {fi.length:5.1f}/{max_s:.1f}"
                f"  D{fi.age:<2}"
                f"  {fi.caution:.2f}"
                f"  R{fi.release_count:<2}"
                f"  C{total_c:<2}"
                f"  {legend_mark}"
            )
            self.screen.blit(self.font_sm.render(line, True, col), (PX + 6, y))

    # ------------------------------------------------------------------
    # NPC dialog
    # ------------------------------------------------------------------

    def _open_npc_dialog(self, npc) -> None:
        game_day = self.save_manager.game_day
        lines = self.npc_manager.generate_dialogue(
            npc, self.population, self.env,
            self.save_manager.catch_log, game_day,
        )
        # 既談話でない場合のみ友好度を加算・記録
        if npc.can_talk_today(game_day):
            self.npc_manager.record_conversation(npc, game_day, lines)
        self._npc_dialog_npc   = npc
        self._npc_dialog_lines = lines
        self._npc_dialog_active = True

    def _close_npc_dialog(self) -> None:
        self._npc_dialog_active = False
        self._npc_dialog_npc   = None
        self._npc_dialog_lines = []

    def _draw_npcs(self, cam_x: int, cam_y: int) -> None:
        """探索マップ上にNPCを描画する。"""
        for npc in self.npc_manager.npcs:
            sx = npc.tile_x * TILE_SIZE - cam_x + TILE_SIZE // 2
            sy = npc.tile_y * TILE_SIZE - cam_y + TILE_SIZE // 2
            if -40 < sx < SCREEN_W + 40 and -40 < sy < SCREEN_H + 40:
                col = npc.color
                pygame.draw.circle(self.screen, col, (sx, sy), 10)
                pygame.draw.circle(self.screen, C_BLACK, (sx, sy), 10, 2)
                initial = self.font_sm.render(npc.npc_type[0], True, C_BLACK)
                self.screen.blit(initial,
                                 (sx - initial.get_width() // 2,
                                  sy - initial.get_height() // 2))

    def _draw_npc_dialog(self) -> None:
        """NPC会話ウィンドウを描画する。"""
        npc = self._npc_dialog_npc
        lines = self._npc_dialog_lines

        DW, DH = 700, 160 + max(0, len(lines) - 2) * 26
        DX = SCREEN_W // 2 - DW // 2
        DY = SCREEN_H - DH - 16

        bg = pygame.Surface((DW, DH), pygame.SRCALPHA)
        bg.fill((10, 10, 20, 220))
        self.screen.blit(bg, (DX, DY))
        pygame.draw.rect(self.screen, npc.color, (DX, DY, DW, DH), 2)

        # ── ヘッダー ──
        header_bg = pygame.Surface((DW, 32), pygame.SRCALPHA)
        header_bg.fill((*npc.color, 60))
        self.screen.blit(header_bg, (DX, DY))
        header_txt = self.font.render(
            f"{npc.name}  [{npc.type_label}]   友好度: {npc.friendship}",
            True, npc.color,
        )
        self.screen.blit(header_txt, (DX + 12, DY + 6))

        # ── 会話行 ──
        for i, line in enumerate(lines):
            y = DY + 44 + i * 26
            surf = self.font_sm.render(f"  {line}", True, C_WHITE)
            self.screen.blit(surf, (DX + 8, y))

        # ── フッター ──
        footer = self.font_sm.render(
            "E / ESC : 閉じる", True, C_GRAY
        )
        self.screen.blit(footer,
                         (DX + DW - footer.get_width() - 12, DY + DH - 22))

    def _draw_npc_debug(self) -> None:
        """F3 NPCデバッグオーバーレイ。"""
        npcs = self.npc_manager.npcs
        PW, PH = 560, 56 + len(npcs) * 22 + 10
        PX, PY = SCREEN_W // 2 - PW // 2, 60

        bg = pygame.Surface((PW, PH), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 210))
        self.screen.blit(bg, (PX, PY))
        pygame.draw.rect(self.screen, (180, 120, 255), (PX, PY, PW, PH), 2)

        title = self.font.render("[F3] NPC Information Network", True, (180, 120, 255))
        self.screen.blit(title, (PX + 10, PY + 8))

        header = self.font_sm.render(
            "  Name       Type        Friend  KnownFish  KnownSpots  LastTalk",
            True, C_GRAY,
        )
        self.screen.blit(header, (PX + 6, PY + 30))

        today = self.save_manager.game_day
        for i, npc in enumerate(npcs):
            y = PY + 52 + i * 22
            talked = "今日" if npc.last_talked_day == today else (
                f"Day{npc.last_talked_day}" if npc.last_talked_day >= 0 else "—"
            )
            line = (
                f"  {npc.name:<8} {npc.type_label:<8}"
                f"  {npc.friendship:>3}"
                f"  {len(npc.known_fish):>5}匹"
                f"  {len(npc.known_spots):>4}箇所"
                f"  {talked}"
            )
            self.screen.blit(
                self.font_sm.render(line, True, npc.color),
                (PX + 6, y),
            )

    def _flash(self, msg: str, color: tuple = C_GREEN) -> None:
        self._flash_msg   = msg
        self._flash_timer = _FLASH_DURATION
        self._flash_color = color


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _draw_box(
    surface: pygame.Surface,
    text_surf: pygame.Surface,
    x: int,
    y: int,
    pad: int = 6,
    bg: tuple = (0, 0, 0),
) -> None:
    w = text_surf.get_width()  + pad * 2
    h = text_surf.get_height() + pad * 2
    pygame.draw.rect(surface, bg, (x, y, w, h))
    surface.blit(text_surf, (x + pad, y + pad))
