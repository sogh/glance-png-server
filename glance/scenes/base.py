"""Scene abstraction: everything the panel can display is a Scene.

A Scene answers two questions -- "do you have anything worth showing right
now?" (`available`) and "draw it" (`render`). The carousel only rotates
through scenes that answer yes to the first, which is what makes an empty
todo list quietly drop out of the rotation instead of showing an empty box.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Protocol

from ..canvas import Canvas
from ..config import Settings
from ..sources.holidays import Holiday
from ..sources.calendars import CalendarSet
from ..sources.ics import CalendarSource
from ..sources.weather import WeatherSource
from ..sources.todos import TodoSource


@dataclass
class Param:
    """One knob a scene exposes.

    Scenes used to be configured through a raw JSON box, so the only way to
    learn what a scene accepted was to read its source, and a typo was
    silently ignored. Declaring them lets the editor draw real controls and
    lets a save be checked.

    `options` may be a literal list or a marker resolved at request time
    against live state: "@sprites", "@fonts", "@calendars", "@static",
    "@colors", "@scenes".
    """

    name: str
    type: str = "text"                     # text | number | bool | select | color
    default: Any = None
    options: list[str] | str | None = None
    help: str = ""
    minimum: float | None = None
    maximum: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "type": self.type, "default": self.default,
            "options": self.options, "help": self.help,
            "min": self.minimum, "max": self.maximum,
        }

    def coerce(self, value: Any) -> Any:
        """Best-effort conversion, so "3" from a form field becomes 3."""
        if value is None or value == "":
            return None
        if self.type == "number":
            number = float(value)
            return int(number) if number.is_integer() else number
        if self.type == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on")
        return value

    def check(self, value: Any) -> str | None:
        """Return a complaint, or None if the value is fine."""
        try:
            value = self.coerce(value)
        except (TypeError, ValueError):
            return f"{self.name}: {value!r} is not a number"
        if value is None:
            return None
        if self.type == "number":
            if self.minimum is not None and value < self.minimum:
                return f"{self.name}: {value} is below {self.minimum}"
            if self.maximum is not None and value > self.maximum:
                return f"{self.name}: {value} is above {self.maximum}"
        if self.type == "select" and isinstance(self.options, list):
            if str(value) not in [str(o) for o in self.options]:
                return f"{self.name}: {value!r} is not one of {self.options}"
        return None


@dataclass
class RenderContext:
    """Everything a scene is allowed to read. Scenes never fetch on their own."""

    settings: Settings
    now: datetime
    calendar: CalendarSource | None = None
    calendars: CalendarSet | None = None
    weather: WeatherSource | None = None
    instagram: Any = None
    baseball: Any = None
    homeassistant: Any = None
    todos: TodoSource | None = None
    holidays: list[Holiday] = field(default_factory=list)
    width_override: int | None = None
    brightness: float | None = None   # None = use the schedule
    scoreboards: dict[str, Any] = field(default_factory=dict)
    logos: Any = None                 # sources.logos.LogoStore
    vocabulary: Any = None            # sources.vocabulary.Vocabulary
    mode_set: Any = None              # sources.modes.ModeSet
    _modes: frozenset[str] | None = field(default=None, repr=False, compare=False)

    @property
    def modes(self) -> frozenset[str]:
        """Modes in force right now -- see sources/modes.py.

        Worked out on first use and remembered for the life of this context,
        which is one request. Deciding costs a calendar parse, and most panels
        never ask, so doing it eagerly would tax every render for a feature
        most of them do not use.
        """
        if self._modes is None:
            if self.mode_set is None:
                self._modes = frozenset()
            else:
                try:
                    self._modes = self.mode_set.active(self.now, self.calendars)
                except Exception:  # noqa: BLE001 - never take the panel down
                    self._modes = frozenset()
        return self._modes

    @property
    def width(self) -> int:
        """Panel width for this render.

        Normally the configured width, but overridable per request so you can
        check what your hardware actually is without editing config.
        """
        return self.width_override or self.settings.width

    @property
    def height(self) -> int:
        """Always 32 -- Glance panels have no other height."""
        from ..canvas import PANEL_HEIGHT

        return PANEL_HEIGHT

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
    params: list[Param] = field(default_factory=list)

    def available(self, ctx: RenderContext, params: dict[str, Any]) -> bool:
        return True if self.available_fn is None else self.available_fn(ctx, params)

    def render(self, ctx: RenderContext, params: dict[str, Any]) -> Canvas:
        return self.render_fn(ctx, params)


REGISTRY: dict[str, Scene] = {}


# Params every entry accepts, whatever the scene.
COMMON_PARAMS = [
    Param("always", "bool", False,
          help="Stay in the rotation even with nothing to show"),
]


def register(
    scene_id: str,
    available: Callable[[RenderContext, dict[str, Any]], bool] | None = None,
    description: str = "",
    params: list[Param] | None = None,
) -> Callable[[Callable[[RenderContext, dict[str, Any]], Canvas]], Callable[..., Canvas]]:
    """Decorator registering a render function under a scene id."""

    def wrap(fn: Callable[[RenderContext, dict[str, Any]], Canvas]):
        REGISTRY[scene_id] = FunctionScene(
            id=scene_id, render_fn=fn, available_fn=available,
            description=description, params=params or [],
        )
        return fn

    return wrap


def schema_for(scene_id: str) -> list[Param]:
    scene = REGISTRY.get(scene_id)
    return list(getattr(scene, "params", []) or []) if scene else []


def resolve_static_options(marker: Any) -> Any:
    """Resolve the markers that do not depend on running state."""
    if not isinstance(marker, str) or not marker.startswith("@"):
        return marker
    if marker == "@colors":
        from ..palette import NAMED
        return sorted(NAMED)
    if marker == "@fonts":
        from ..fonts import FONTS
        return sorted(FONTS)
    if marker == "@sprites":
        from ..sprites import SPRITES
        return sorted(SPRITES)
    if marker == "@scenes":
        return sorted(REGISTRY)
    return None          # @calendars / @static need app state; not checkable here


def validate_params(scene_id: str, values: dict[str, Any],
                    resolve: Callable[[Any], Any] | None = None) -> list[str]:
    """Complaints about a set of params. Unknown keys are reported rather than
    rejected: they are almost always typos, but refusing them outright would
    break a config that predates the schema."""
    schema = {p.name: p for p in schema_for(scene_id)}
    schema.update({p.name: p for p in COMMON_PARAMS})
    problems: list[str] = []
    for key, value in (values or {}).items():
        param = schema.get(key)
        if param is None:
            known = ", ".join(sorted(schema)) or "none"
            problems.append(f"{key!r} is not a parameter of {scene_id} (known: {known})")
            continue
        # Options are declared as markers so they can reflect live state;
        # resolve them before checking, or a select can never be validated.
        checked = param
        if isinstance(param.options, str):
            options = (resolve or resolve_static_options)(param.options)
            if isinstance(options, list):
                checked = replace(param, options=options)
            else:
                checked = replace(param, options=None, type="text")
        complaint = checked.check(value)
        if complaint:
            problems.append(complaint)
    return problems


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
