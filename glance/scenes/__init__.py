"""Importing this package registers every built-in scene."""

from . import (agenda, basic, columns, holiday, instagram, marquee,  # noqa: F401
               pulse, sprite, static_image, todos, weather)
from .base import (  # noqa: F401
    REGISTRY,
    FunctionScene,
    RenderContext,
    Scene,
    error_canvas,
    get_scene,
    register,
    resolve,
)

__all__ = [
    "REGISTRY", "FunctionScene", "RenderContext", "Scene",
    "error_canvas", "get_scene", "register", "resolve",
]
