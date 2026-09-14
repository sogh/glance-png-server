"""Importing this package registers every built-in scene."""

from . import (activity, agenda, banner, baseball, basic, columns,  # noqa: F401
               entities, holiday, instagram, marquee, pulse, sprite,
               static_image, sky, scores, todos, weather)
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
