"""Bass RPG – entry point.

Works both on desktop (``python3 main.py``) and in the browser via pygbag
(WebAssembly). pygbag requires the top-level entry to be an async coroutine
launched with ``asyncio.run``.

Any startup/runtime exception is rendered straight onto the pygame canvas so
it stays visible on devices (phones) where the browser console is not
reachable.
"""

import asyncio
import traceback


def _show_fatal(tb: str) -> None:
    """Best-effort: paint a traceback onto a pygame window so it is readable
    on a phone screen where no console is available."""
    try:
        import pygame
        if not pygame.get_init():
            pygame.init()
        surf = pygame.display.get_surface()
        if surf is None:
            surf = pygame.display.set_mode((1280, 720))
        surf.fill((18, 18, 28))
        font = pygame.font.Font(None, 26)
        y = 16
        surf.blit(font.render("STARTUP ERROR:", True, (255, 80, 80)), (16, y))
        y += 36
        for line in tb.splitlines():
            # wrap long lines so nothing runs off the right edge on mobile
            while line:
                chunk, line = line[:96], line[96:]
                surf.blit(font.render(chunk, True, (255, 170, 170)), (16, y))
                y += 26
        pygame.display.flip()
    except Exception:
        pass


async def main() -> None:
    try:
        from game import Game
        await Game().run()
    except BaseException:
        tb = traceback.format_exc()
        print(tb)
        _show_fatal(tb)
        # Keep the error frame on screen instead of exiting to a blank canvas.
        while True:
            await asyncio.sleep(0.2)


if __name__ == "__main__":
    asyncio.run(main())
