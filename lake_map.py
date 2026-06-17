import math
import pygame
from constants import (
    MAP_W, MAP_H, TILE_SIZE, SCREEN_W, SCREEN_H,
    TILE_LAND, TILE_WATER, TILE_PATH, TILE_SHORE,
    C_LAND, C_WATER, C_PATH, C_SHORE, C_FISHING_SPOT, C_BLACK, C_YELLOW,
)

_TILE_COLOR = {
    TILE_LAND: C_LAND,
    TILE_WATER: C_WATER,
    TILE_PATH: C_PATH,
    TILE_SHORE: C_SHORE,
}

_SPOT_NAMES = [
    "North Point", "NE Weed Flat", "East Shore",
    "SE Cove", "South Flat", "SW Brush",
    "West Bank", "NW Drop-off", "Island Point", "Rock Pile",
]


class LakeMap:
    """Top-down 50×50 tile lake map with fishing spots on the shore."""

    LAKE_CX = 25
    LAKE_CY = 22
    LAKE_R = 10

    def __init__(self):
        self.width = MAP_W
        self.height = MAP_H
        self.tiles: list[list[int]] = [
            [TILE_LAND] * self.width for _ in range(self.height)
        ]
        self.fishing_spots: list[tuple] = []  # (tile_x, tile_y, name)
        self._generate()

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _generate(self) -> None:
        cx, cy, r = self.LAKE_CX, self.LAKE_CY, self.LAKE_R

        for y in range(self.height):
            for x in range(self.width):
                dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                if dist < r - 1:
                    self.tiles[y][x] = TILE_WATER
                elif dist < r + 1:
                    self.tiles[y][x] = TILE_SHORE

        # Horizontal path south of lake
        for x in range(self.width):
            if self.tiles[36][x] == TILE_LAND:
                self.tiles[36][x] = TILE_PATH
        # Vertical path connecting start area to lake shore
        for y in range(33, self.height):
            if self.tiles[y][cx] == TILE_LAND:
                self.tiles[y][cx] = TILE_PATH
        # Small path east
        for x in range(cx, cx + 12):
            if self.tiles[36][x] == TILE_PATH:
                continue
            if self.tiles[36][x] == TILE_LAND:
                self.tiles[36][x] = TILE_PATH

        # Fishing spots evenly spaced around the lake (on shore ring)
        for i in range(10):
            angle = (i / 10) * 2 * math.pi - math.pi / 2
            sx = int(round(cx + (r + 0.5) * math.cos(angle)))
            sy = int(round(cy + (r + 0.5) * math.sin(angle)))
            sx = max(1, min(self.width - 2, sx))
            sy = max(1, min(self.height - 2, sy))
            # Make sure it's shore, not water
            if self.tiles[sy][sx] != TILE_WATER:
                self.fishing_spots.append((sx, sy, _SPOT_NAMES[i]))

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_walkable(self, tx: int, ty: int) -> bool:
        if not (0 <= tx < self.width and 0 <= ty < self.height):
            return False
        return self.tiles[ty][tx] != TILE_WATER

    def get_nearby_spot(self, tx: int, ty: int, radius: int = 2):
        for sx, sy, name in self.fishing_spots:
            if abs(sx - tx) <= radius and abs(sy - ty) <= radius:
                return (sx, sy, name)
        return None

    def all_spot_names(self) -> list:
        """全スポット名のリストを返す (Phase 7 daily_replenish 用)。"""
        return [name for _, _, name in self.fishing_spots]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def draw(self, surface: pygame.Surface, cam_x: int, cam_y: int) -> None:
        # Only draw tiles in viewport
        start_tx = max(0, cam_x // TILE_SIZE)
        end_tx = min(self.width, start_tx + SCREEN_W // TILE_SIZE + 2)
        start_ty = max(0, cam_y // TILE_SIZE)
        end_ty = min(self.height, start_ty + SCREEN_H // TILE_SIZE + 2)

        for ty in range(start_ty, end_ty):
            for tx in range(start_tx, end_tx):
                color = _TILE_COLOR.get(self.tiles[ty][tx], C_LAND)
                sx = tx * TILE_SIZE - cam_x
                sy = ty * TILE_SIZE - cam_y
                pygame.draw.rect(surface, color, (sx, sy, TILE_SIZE, TILE_SIZE))
                # Subtle grid line
                darker = (
                    max(0, color[0] - 15),
                    max(0, color[1] - 15),
                    max(0, color[2] - 15),
                )
                pygame.draw.rect(surface, darker, (sx, sy, TILE_SIZE, TILE_SIZE), 1)

        # Fishing spot markers
        for sx, sy, name in self.fishing_spots:
            px = sx * TILE_SIZE - cam_x + TILE_SIZE // 2
            py = sy * TILE_SIZE - cam_y + TILE_SIZE // 2
            if -60 < px < SCREEN_W + 60 and -60 < py < SCREEN_H + 60:
                pygame.draw.circle(surface, C_FISHING_SPOT, (px, py), 7, 2)
                pygame.draw.circle(surface, C_YELLOW, (px, py), 3)
