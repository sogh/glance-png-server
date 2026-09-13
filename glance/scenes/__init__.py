"""Importing this package registers every built-in scene."""

from . import (agenda, baseball, basic, columns, entities, holiday,  # noqa: F401
               instagram, marquee, pulse, sprite, static_image, todos, weather)
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
