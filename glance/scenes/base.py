"""Scene abstraction: everything the panel can display is a Scene.

A Scene answers two questions -- "do you have anything worth showing right
now?" (`available`) and "draw it" (`render`). The carousel only rotates
through scenes that answer yes to the first, which is what makes an empty
todo list quietly drop out of the rotation instead of showing an empty box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

from ..canvas import Canvas
from ..config import Settings
from ..sources.holidays import Holiday
from ..sources.calendars import CalendarSet
from ..sources.ics import CalendarSource
from ..sources.todos import TodoSource


@dataclass
class RenderContext:
    """Everything a scene is allowed to read. Scenes never fetch on their own."""

    settings: Settings
    now: datetime
    calendar: CalendarSource | None = None
    calendars: CalendarSet | None = None
    todos: TodoSource | None = None
    holidays: list[Holiday] = field(default_factory=list)
    width_override: int | None = None

    @property
    def width(self) -> int:
        """Panel width for this render.

        Normally the configured width, but overridable per request so you can
        check what your hardware actually is without editing config.
        """
        return self.width_override or self.settings.width

    def canvas(self) -> Canvas:
        return Canvas(width=self.width)

    @property
    def today(self):
        return self.now.date()


class Scene(Protocol):
    id: str

    def available(self, ctx: RenderContext, params: dict[str, Any]) -> bool: ...
    def render(self, ctx: RenderContext, params: dict[str, Any]) -> Canvas: ...


@dataclass
class FunctionScene:
    """Wraps a plain render function into a Scene."""

    id: str
    render_fn: Callable[[RenderContext, dict[str, Any]], Canvas]
    available_fn: Callable[[RenderContext, dict[str, Any]], bool] | None = None
    description: str = ""

    def available(self, ctx: RenderContext, params: dict[str, Any]) -> bool:
        return True if self.available_fn is None else self.available_fn(ctx, params)

    def render(self, ctx: RenderContext, params: dict[str, Any]) -> Canvas:
        return self.render_fn(ctx, params)


REGISTRY: dict[str, Scene] = {}


def register(
    scene_id: str,
    available: Callable[[RenderContext, dict[str, Any]], bool] | None = None,
    description: str = "",
) -> Callable[[Callable[[RenderContext, dict[str, Any]], Canvas]], Callable[..., Canvas]]:
    """Decorator registering a render function under a scene id."""

    def wrap(fn: Callable[[RenderContext, dict[str, Any]], Canvas]):
        REGISTRY[scene_id] = FunctionScene(
            id=scene_id, render_fn=fn, available_fn=available, description=description
        )
        return fn

    return wrap


def get_scene(ref: str) -> Scene | None:
    return REGISTRY.get(ref)


def error_canvas(ctx: RenderContext, message: str, title: str = "ERROR") -> Canvas:
    """A card the panel can show when a scene blows up.

    Rendering something legible beats a 500: the device caches whatever it last
    fetched, and a silent failure looks identical to a working display.
    """
    c = ctx.canvas()
    c.clear("black")
    c.fill_rect(0, 0, c.width, 7, (60, 0, 0))
    c.text(2, 1, title, "red", "3x5")
    from ..fonts import get_font

    font = get_font("3x5")
    lines = font.wrap(message, c.width - 4)[:4]
    c.text_block(2, 9, lines, "orange", font, leading=1)
    return c


def resolve(ref: str, params: dict[str, Any] | None = None) -> tuple[Scene | None, dict[str, Any]]:
    """Look up a scene by reference, supporting `prefix:argument` form.

    "static:winter-cabin" resolves to the `static` scene with name=winter-cabin,
    which is what lets a channel list a Photoshop file inline.
    """
    merged = dict(params or {})
    if ":" in ref:
        prefix, arg = ref.split(":", 1)
        scene = REGISTRY.get(prefix)
        if scene is not None:
            merged.setdefault("name", arg)
            return scene, merged
    return REGISTRY.get(ref), merged
