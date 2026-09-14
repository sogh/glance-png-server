"""Importing this package registers every built-in scene."""

from . import (activity, agenda, banner, baseball, basic, columns,  # noqa: F401
               entities, holiday, instagram, language, pulse, rankings,
               scores, sky, sprite, static_image, todos, weather)
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
