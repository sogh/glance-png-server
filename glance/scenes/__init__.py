"""Importing this package registers every built-in scene."""

from . import (agenda, baseball, basic, columns, holiday, instagram,  # noqa: F401
               marquee, pulse, sprite, static_image, todos, weather)
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
