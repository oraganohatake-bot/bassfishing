import pygame
from constants import TILE_SIZE, C_PLAYER, C_BLACK, C_WHITE


class Player:
    """Top-down player character on the lake map.

    Uses tile-based movement with smooth pixel animation.
    """

    MOVE_SPEED = 4.0  # pixels per frame

    def __init__(self, tile_x: int, tile_y: int):
        self.tile_x = tile_x
        self.tile_y = tile_y
        self.px = float(tile_x * TILE_SIZE)
        self.py = float(tile_y * TILE_SIZE)
        self._target_px = self.px
        self._target_py = self.py
        self._moving = False
        self.face: tuple = (0, 1)  # (dx, dy) – initially facing south

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def teleport(self, tile_x: int, tile_y: int) -> None:
        """Instantly move the player to a tile position (used by load)."""
        self.tile_x = tile_x
        self.tile_y = tile_y
        self.px = float(tile_x * TILE_SIZE)
        self.py = float(tile_y * TILE_SIZE)
        self._target_px = self.px
        self._target_py = self.py
        self._moving = False

    def handle_input(self, keys, lake_map) -> None:
        if self._moving:
            return

        dx, dy = 0, 0
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy = -1
        elif keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy = 1
        elif keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx = -1
        elif keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx = 1

        if dx or dy:
            self.face = (dx, dy)
            ntx, nty = self.tile_x + dx, self.tile_y + dy
            if lake_map.is_walkable(ntx, nty):
                self.tile_x = ntx
                self.tile_y = nty
                self._target_px = float(ntx * TILE_SIZE)
                self._target_py = float(nty * TILE_SIZE)
                self._moving = True

    def update(self) -> None:
        if not self._moving:
            return
        ddx = self._target_px - self.px
        ddy = self._target_py - self.py
        dist = (ddx ** 2 + ddy ** 2) ** 0.5
        if dist <= self.MOVE_SPEED:
            self.px = self._target_px
            self.py = self._target_py
            self._moving = False
        else:
            self.px += (ddx / dist) * self.MOVE_SPEED
            self.py += (ddy / dist) * self.MOVE_SPEED

    def draw(self, surface: pygame.Surface, cam_x: int, cam_y: int) -> None:
        sx = int(self.px - cam_x)
        sy = int(self.py - cam_y)
        half = TILE_SIZE // 2
        # Shadow
        pygame.draw.ellipse(surface, (0, 0, 0, 100), (sx + 6, sy + TILE_SIZE - 6, TILE_SIZE - 12, 8))
        # Body (yellow square with border)
        body_rect = pygame.Rect(sx + 4, sy + 4, TILE_SIZE - 8, TILE_SIZE - 8)
        pygame.draw.rect(surface, C_PLAYER, body_rect, border_radius=4)
        pygame.draw.rect(surface, C_BLACK, body_rect, 2, border_radius=4)
        # Direction dot
        fx, fy = self.face
        cx = sx + half
        cy = sy + half
        pygame.draw.circle(surface, C_WHITE, (cx + fx * 8, cy + fy * 8), 3)
