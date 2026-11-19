from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema


def include_schemas(app: FastAPI, *models: type[BaseModel]) -> None:
    """Publish models in `components.schemas` even when no endpoint uses them yet.

    For contracts shared between domains before their endpoints exist (FormDefinition), so the
    frontend can generate types from openapi.json. Schemas FastAPI already emits win.
    """
    base: Callable[[], dict[str, Any]] = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = base()
        _, extra = models_json_schema(
            [(m, "validation") for m in models], ref_template="#/components/schemas/{model}"
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for name, definition in extra.get("$defs", {}).items():
            components.setdefault(name, definition)
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
