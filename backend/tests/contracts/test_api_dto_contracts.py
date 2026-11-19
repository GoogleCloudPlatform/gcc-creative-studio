# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Automated backend DTO strictness and frontend-to-backend contract tests."""

from __future__ import annotations

import pathlib
import re
import typing

import fastapi.routing as fr
from pydantic import BaseModel, ValidationError
import pytest

from main import app
from src.common.base_dto import AspectRatioEnum, MimeTypeEnum
from src.common.schema.media_item_model import (
    AssetRoleEnum,
    MediaItemModel,
    SourceMediaItemLink,
)
from src.galleries.dto.gallery_response_dto import SourceMediaItemLinkResponse
from src.images.dto.create_imagen_dto import CreateImagenDto
from src.workbench.dto.workbench_dto import VideoTimeline
from src.workflows.queue.run_state_service import _snapshot_steps
from src.workflows.schema.workflow_model import (
    GenerateAudioInputs,
    GenerateAudioSettings,
    GenerateAudioStep,
    GenerateTextInputs,
    GenerateTextSettings,
    GenerateTextStep,
    GenerateVideoInputs,
    GenerateVideoSettings,
    GenerateVideoStep,
    ImageInputs,
    ImageSettings,
    ImageStep,
    LoopInputs,
    LoopSettings,
    LoopStep,
    StepOutputReference,
    UserInputDefinition,
    UserInputSettings,
    UserInputStep,
    WorkflowCreateDto,
    WorkflowModel,
    WorkflowValidateDto,
)
from src.workflows.schema.workflow_template_model import (
    WorkflowTemplateCreateDto,
    WorkflowTemplateModel,
)
from src.workflows.workflow_yaml_builder import build_workflow_definition
from tests.contracts.canonical_payloads import CANONICAL_BROWSER_PAYLOADS

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FRONTEND_APP_DIR = REPO_ROOT / "frontend" / "src" / "app"
DYNAMIC_SCHEMA_ALLOWLIST = frozenset(
    {
        "StoryboardCreate",
        "StoryboardUpdate",
        "ChatMessagePart",
        "WorkflowExecuteDto",
        "GenerateTextInputs",
    }
)
LEGACY_UNWIRED_FRONTEND_MUTATIONS = frozenset(
    {
        ("POST", "/api/media-templates"),
        ("POST", "/api/source_assets"),
        ("PUT", "/api/source_assets/{}"),
        ("POST", "/api/users"),
        ("POST", "/api/projects"),
        ("PUT", "/api/projects/{}"),
    }
)
MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _iter_api_routes(
    router: object, prefix: str = ""
) -> typing.Iterator[tuple[str, fr.APIRoute]]:
    for route in getattr(router, "routes", []):
        if isinstance(route, fr.APIRoute):
            yield prefix + route.path, route
        elif hasattr(route, "original_router"):
            ctx_prefix = getattr(
                getattr(route, "include_context", None), "prefix", ""
            )
            yield from _iter_api_routes(
                route.original_router, prefix + str(ctx_prefix or "")
            )


def _unwrap_models(ann: object) -> list[type[BaseModel]]:
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return [ann]
    origin = typing.get_origin(ann)
    if origin is None:
        return []
    models: list[type[BaseModel]] = []
    for arg in typing.get_args(ann):
        models.extend(_unwrap_models(arg))
    return models


def _normalize_path(path: str) -> str:
    clean = path.split("?", 1)[0].rstrip("/") or "/"
    return re.sub(r"\{[^}]+\}", "{}", clean)


def _collect_backend_mutation_models() -> (
    dict[tuple[str, str], tuple[str, list[type[BaseModel]]]]
):
    routes: dict[tuple[str, str], tuple[str, list[type[BaseModel]]]] = {}
    for full_path, route in _iter_api_routes(app.router):
        norm = _normalize_path(full_path)
        models: list[type[BaseModel]] = []
        for bp in route.dependant.body_params:
            models.extend(_unwrap_models(bp.field_info.annotation))
        for method in route.methods & MUTATION_METHODS:
            routes[(method, norm)] = (full_path, models)
    return routes


def _check_model_tree(
    model: type[BaseModel],
    origin: str,
    visited: set[type[BaseModel]],
    violations: list[str],
) -> None:
    if model in visited or model.__name__ in DYNAMIC_SCHEMA_ALLOWLIST:
        return
    visited.add(model)
    if model.model_config.get("extra") != "forbid":
        violations.append(f"{origin} -> {model.__name__}")
    for fname, finfo in model.model_fields.items():
        for child in _unwrap_models(finfo.annotation):
            _check_model_tree(child, f"{origin}.{fname}", visited, violations)


def _scan_frontend_json_mutations() -> list[tuple[str, str, str]]:
    calls: list[tuple[str, str, str]] = []
    base_re = re.compile(
        r"\b([A-Za-z_]\w*Url|API_BASE_URL)\s*=\s*"
        r"(?:[`'\"]([^`'\"]*(?:environment\.backendURL|/api/)[^`'\"]*)[`'\"]|"
        r"(environment\.backendURL))\s*;"
    )
    local_url_re = re.compile(r"(?:const|let)\s+(\w+)\s*=\s*`([^`]*)`\s*;")
    http_re = re.compile(
        r"this\.http\s*\.\s*(post|put|patch)\b"
        r"(?:<(?:[^<>]|<[^<>]*>)*>)?\s*\(\s*"
        r"(`[^`]+`|['\"][^'\"]+['\"]|[A-Za-z_][A-Za-z0-9_.]+)\s*,\s*([^,\)]+)",
        re.MULTILINE,
    )
    for svc in sorted(FRONTEND_APP_DIR.rglob("*.service.ts")):
        txt = svc.read_text(encoding="utf-8")
        field_vars: dict[str, str] = {"environment.backendURL": "/api"}
        for m in base_re.finditer(txt):
            expr = m.group(2) or m.group(3)
            resolved = expr.replace("${environment.backendURL}", "/api")
            if resolved == "environment.backendURL":
                resolved = "/api"
            field_vars[f"this.{m.group(1)}"] = resolved.rstrip("/")
            field_vars[m.group(1)] = resolved.rstrip("/")

        local_assigns: list[tuple[int, str, str]] = []
        for m in local_url_re.finditer(txt):
            val = m.group(2).replace("${environment.backendURL}", "/api")
            for k, v in field_vars.items():
                val = val.replace(f"${{{k}}}", v)
            local_assigns.append((m.start(), m.group(1), val))

        for m in http_re.finditer(txt):
            method = m.group(1).upper()
            url_arg = m.group(2).strip()
            body_arg = m.group(3).strip()
            if "formdata" in body_arg.lower() or "signedurl" in url_arg.lower():
                continue
            raw_url = url_arg[1:-1] if url_arg[0] in "`'\"" else ""
            if not raw_url:
                raw_url = field_vars.get(url_arg, "")
                if not raw_url:
                    prior = [
                        val
                        for pos, name, val in local_assigns
                        if pos < m.start() and name == url_arg
                    ]
                    raw_url = prior[-1] if prior else ""
            for k, v in field_vars.items():
                raw_url = raw_url.replace(f"${{{k}}}", v)
            raw_url = raw_url.replace("${environment.backendURL}", "/api")
            if not raw_url.startswith("/api/"):
                continue
            templated = re.sub(r"\$\{[^}]+\}", "{param}", raw_url)
            calls.append((svc.name, method, _normalize_path(templated)))
    return calls


def _iter_http_post_calls(node: object) -> typing.Iterator[tuple[str, dict]]:
    if isinstance(node, dict):
        if node.get("call") == "http.post" and isinstance(
            node.get("args"), dict
        ):
            yield str(node["args"].get("url", "")), node["args"].get("body", {})
        for v in node.values():
            yield from _iter_http_post_calls(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_http_post_calls(item)


def _subst_runtime_expr(val: typing.Any) -> typing.Any:
    if isinstance(val, dict):
        return {k: _subst_runtime_expr(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_subst_runtime_expr(v) for v in val]
    if not isinstance(val, str):
        return val
    m = re.fullmatch(r"\$\{(.+)\}", val)
    if not m:
        return val
    expr = m.group(1)
    exact: dict[str, typing.Any] = {
        "run_id": "run-1",
        "exec_id": "exec-1",
        "args.workspace_id": 1,
        "current_step": "step_text",
        "e": {"message": "step failed"},
    }
    if expr in exact:
        return exact[expr]
    if expr.endswith("_idx"):
        return 0
    if "generated_image" in expr or "current_item" in expr:
        return 42
    return "resolved-value"


def test_all_mutation_body_dtos_forbid_extra_fields() -> None:
    """Mutation body DTOs and nested sub-models must forbid extra fields."""
    routes = _collect_backend_mutation_models()
    assert len(routes) >= 40
    violations: list[str] = []
    visited: set[type[BaseModel]] = set()
    for (method, path), (_, models) in sorted(routes.items()):
        for model in models:
            _check_model_tree(
                model, f"{method} {path}::{model.__name__}", visited, violations
            )
    assert not violations, f"DTOs missing extra='forbid': {violations}"
    assert VideoTimeline.model_config.get("alias_generator") is None


def test_frontend_json_mutation_endpoints_match_backend_routes() -> None:
    """Frontend HTTP mutations must resolve to registered backend routes."""
    backend_routes = _collect_backend_mutation_models()
    fe_calls = [
        c
        for c in _scan_frontend_json_mutations()
        if (c[1], c[2]) not in LEGACY_UNWIRED_FRONTEND_MUTATIONS
    ]
    matched = [c for c in fe_calls if (c[1], c[2]) in backend_routes]
    assert len(matched) >= 50, f"Too few resolved calls: {len(matched)}"
    missing = [
        f"{svc}: {method} {norm}"
        for svc, method, norm in fe_calls
        if (method, norm) not in backend_routes
    ]
    assert not missing, f"Frontend mutations without backend route: {missing}"


def test_compiled_workflow_step_bodies_match_executor_dtos() -> None:
    """Compiled Cloud Workflows HTTP bodies validate against executor DTOs."""
    exec_url = "https://executor.example/api/workflows-executor"
    steps = [
        UserInputStep(
            step_id="user_in",
            settings=UserInputSettings(
                definitions=[
                    UserInputDefinition(id="topic", name="topic", type="text")
                ]
            ),
        ),
        GenerateTextStep(
            step_id="step_text",
            inputs=GenerateTextInputs(
                prompt=StepOutputReference(step="user_in", output="topic")
            ),
            settings=GenerateTextSettings(
                model="gemini-2.5-flash", temperature=0.3
            ),
        ),
        ImageStep(
            step_id="step_image",
            inputs=ImageInputs(
                prompt=StepOutputReference(step="step_text", output="result")
            ),
            settings=ImageSettings(mode="generate_image"),
        ),
        GenerateVideoStep(
            step_id="step_video",
            inputs=GenerateVideoInputs(
                prompt="Animate",
                input_images=StepOutputReference(
                    step="step_image", output="generated_image"
                ),
            ),
            settings=GenerateVideoSettings(model="veo-3.1-generate-001"),
        ),
        GenerateAudioStep(
            step_id="step_audio",
            inputs=GenerateAudioInputs(prompt="Synth bed"),
            settings=GenerateAudioSettings(model="lyria-002"),
        ),
        LoopStep(
            step_id="step_loop",
            inputs=LoopInputs(
                items_text="a,b",
                loop_ending=StepOutputReference(
                    step="loop_img", output="loop_ending"
                ),
            ),
            settings=LoopSettings(mode="text_input", item_type="image"),
        ),
        ImageStep(
            step_id="loop_img",
            inputs=ImageInputs(
                prompt="Render item",
                input_images=StepOutputReference(
                    step="step_loop", output="current_item"
                ),
            ),
            settings=ImageSettings(mode="generate_image"),
        ),
    ]
    definition = build_workflow_definition(steps, executor_url=exec_url)
    routes = _collect_backend_mutation_models()
    seen_paths: set[str] = set()
    for url, raw_body in _iter_http_post_calls(definition):
        if "/runs/" in url and "/finished" in url:
            route_path = "/api/workflows-executor/runs/{}/finished"
        else:
            prefix = "https://executor.example"
            assert url.startswith(prefix), url
            route_path = url[len(prefix) :]
        seen_paths.add(route_path)
        _, models = routes[("POST", route_path)]
        body = _subst_runtime_expr(raw_body)
        models[0].model_validate(body)
        with pytest.raises(ValidationError):
            models[0].model_validate({**body, "unexpectedExtraField": True})

    expected_paths = {
        "/api/workflows-executor/generate_text",
        "/api/workflows-executor/image",
        "/api/workflows-executor/generate_video",
        "/api/workflows-executor/generate_audio",
        "/api/workflows-executor/resolve-loop-items",
        "/api/workflows-executor/runs/{}/finished",
    }
    assert seen_paths == expected_paths


@pytest.mark.parametrize(
    ("method", "path", "payload"), CANONICAL_BROWSER_PAYLOADS
)
def test_canonical_browser_payloads_validate_and_reject_extras(
    method: str, path: str, payload: dict
) -> None:
    """Canonical browser payloads validate and reject unexpected keys."""
    routes = _collect_backend_mutation_models()
    _, models = routes[(method, path)]
    assert models
    model = models[0]
    model.model_validate(payload)
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "unexpectedExtraField": True})


def test_request_dtos_stay_strict_while_persisted_models_ignore_extra_keys(
    api_client,
) -> None:
    """HTTP DTOs reject extras (even legacy steps) while DB reads strip them."""
    legacy_step = {
        "step_id": "img_1",
        "type": "generate_image",
        "legacyStepJunk": True,
        "inputs": {
            "prompt": "sun",
            "input_images": [
                {
                    "previewUrl": "https://example.com/a.png",
                    "legacyRefKey": "old",
                    "sourceMediaItem": {
                        "mediaItemId": 1,
                        "mediaIndex": 0,
                        "role": "input",
                        "legacyLinkKey": 9,
                    },
                },
                {"step": "u1", "output": "x", "legacyOutKey": 1},
            ],
            "legacyInputKey": "drop-me",
        },
        "settings": {"aspect_ratio": "1:1", "legacySettingKey": "old"},
    }
    for dto_cls in (
        WorkflowCreateDto,
        WorkflowValidateDto,
        WorkflowTemplateCreateDto,
    ):
        with pytest.raises(ValidationError):
            dto_cls.model_validate({"name": "WF", "steps": [legacy_step]})

    resp = api_client.post(
        "/api/workflows", json={"name": "WF", "steps": [legacy_step]}
    )
    assert resp.status_code == 422

    with pytest.raises(ValidationError):
        CreateImagenDto.model_validate(
            {
                "prompt": "cat",
                "sourceMediaItems": [
                    {
                        "mediaItemId": 1,
                        "mediaIndex": 0,
                        "role": "input",
                        "extraKey": True,
                    }
                ],
            }
        )

    wf = WorkflowModel.model_validate(
        {"id": "wf-1", "user_id": 1, "name": "WF", "steps": [legacy_step]}
    )
    assert wf.steps[0].settings.mode == "generate_image"
    tpl = WorkflowTemplateModel.model_validate(
        {
            "id": "tpl-1",
            "user_id": 1,
            "name": "TPL",
            "steps": [
                {
                    "step_id": "u1",
                    "type": "user_input",
                    "settings": {
                        "definitions": [
                            {"name": "p", "type": "text", "legacyDefKey": 1}
                        ],
                        "legacySet": 2,
                    },
                }
            ],
        }
    )
    assert tpl.steps[0].settings.definitions[0].name == "p"
    snap_steps = _snapshot_steps({"name": "Run", "steps": [legacy_step]})
    assert len(snap_steps) == 1

    item = MediaItemModel.model_validate(
        {
            "user_id": 1,
            "user_email": "t@example.com",
            "workspace_id": 1,
            "mime_type": MimeTypeEnum.IMAGE_PNG,
            "model": "imagen-3.0",
            "aspect_ratio": AspectRatioEnum.RATIO_1_1,
            "gcs_uris": ["gs://b/o.png"],
            "source_media_items": [
                {
                    "media_item_id": 5,
                    "media_index": 0,
                    "role": AssetRoleEnum.INPUT,
                    "legacy_link_col": "ignored",
                },
                SourceMediaItemLink(
                    media_item_id=6, media_index=1, role=AssetRoleEnum.INPUT
                ),
            ],
        }
    )
    assert item.source_media_items is not None
    assert [link.media_item_id for link in item.source_media_items] == [5, 6]
    resp_link = SourceMediaItemLinkResponse.model_validate(
        {
            "media_item_id": 5,
            "media_index": 0,
            "role": AssetRoleEnum.INPUT,
            "presigned_url": "https://example.com/p",
            "gcs_uri": "gs://b/p.png",
            "legacy_extra": "ignored",
        }
    )
    assert resp_link.media_item_id == 5
