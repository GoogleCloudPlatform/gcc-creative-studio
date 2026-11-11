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
"""Lyria 3 lyrics / song-structure parsing (single source of truth).

Turns the text blocks Lyria 3 returns next to the audio into the
``audio_analysis = {"tracks": [{"raw_text", "lyrics"?, "structure"?} | None]}``
payload stored on media items. The frontend renders that payload as-is and
never parses Lyria text itself.

This module must stay free of application imports: the audio worker
(``audio_service``) and the gallery response DTO both import it, and
``audio_service`` already imports the DTO. The underscore helpers are
internal to ``src.audios``; ``normalize_audio_analysis`` is the public
read-time entry point.
"""

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)


def _get_attr_or_key(obj: Any, name: str) -> Any:
    """Reads ``name`` from a pydantic model / object or a plain dict."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


_LYRIA_3_META_LINE = re.compile(
    r"^(caption|bpm|mosic|tempo|key|genre|mood|time[ _-]?signature|duration)"
    r"\s*:\s*(.*)$",
    re.IGNORECASE,
)


def _coerce_lyria3_scalar(value: str) -> int | float | str:
    """Converts numeric metadata strings (e.g. ``'90.0'``, ``'4.5'``) to numbers."""
    stripped = value.strip()
    try:
        num = float(stripped)
        return int(num) if num.is_integer() else num
    except ValueError:
        return stripped


def _parse_lyria3_plain_block(block: str) -> tuple[str | None, dict[str, Any]]:
    """Splits a plain-text Lyria 3 block into ``(lyrics, structure)``."""
    lyrics_lines: list[str] = []
    structure: dict[str, Any] = {}
    in_multiline_caption = False

    for raw_line in block.splitlines():
        stripped = raw_line.strip()
        match = _LYRIA_3_META_LINE.match(stripped)
        if match:
            norm_key = re.sub(r"[\s-]+", "_", match.group(1).lower())
            raw_val = match.group(2).strip()
            if norm_key == "caption":
                if raw_val:
                    structure["caption"] = raw_val
                in_multiline_caption = True
            else:
                if raw_val:
                    structure[norm_key] = _coerce_lyria3_scalar(raw_val)
                in_multiline_caption = False
            continue

        if in_multiline_caption:
            if not stripped:
                in_multiline_caption = False
                continue
            if not stripped.startswith("["):
                prev = structure.get("caption", "")
                structure["caption"] = f"{prev} {stripped}".strip()
                continue
            in_multiline_caption = False

        lyrics_lines.append(raw_line)

    cleaned_lyrics = "\n".join(lyrics_lines).strip()
    return (cleaned_lyrics or None), structure


def _collect_text_items(items: Any) -> list[str]:
    """Collects non-empty ``type == 'text'`` strings from an interaction item sequence."""
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return []
    return [
        text_val.strip()
        for item in items
        if _get_attr_or_key(item, "type") == "text"
        and isinstance((text_val := _get_attr_or_key(item, "text")), str)
        and text_val.strip()
    ]


def _extract_lyria3_text(interaction: Any) -> dict[str, Any] | None:
    """Extracts lyrics and/or song structure text from a Lyria 3 ``Interaction``."""
    blocks: list[str] = []
    steps = _get_attr_or_key(interaction, "steps")
    if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)):
        for step in steps:
            step_type = _get_attr_or_key(step, "type")
            if isinstance(step_type, str) and step_type != "model_output":
                continue
            blocks.extend(
                _collect_text_items(_get_attr_or_key(step, "content"))
            )

    if not blocks:
        blocks = _collect_text_items(_get_attr_or_key(interaction, "outputs"))

    if not blocks:
        output_text = _get_attr_or_key(interaction, "output_text")
        if isinstance(output_text, str) and output_text.strip():
            blocks.append(output_text.strip())

    if not blocks:
        return None

    entry: dict[str, Any] = {"raw_text": "\n\n".join(blocks)}
    lyrics_parts: list[str] = []

    for block in blocks:
        parsed_json: Any = None
        if block.startswith(("{", "[")):
            try:
                parsed_json = json.loads(block)
            except ValueError:
                parsed_json = None

        if isinstance(parsed_json, dict):
            entry["structure"] = parsed_json
            inline_lyrics = parsed_json.get("lyrics")
            if isinstance(inline_lyrics, str) and inline_lyrics.strip():
                lyrics_parts.append(inline_lyrics.strip())
            elif isinstance(parsed_json.get("sections"), list):
                section_lyrics = [
                    (
                        f"[{label.strip()}]\n{sec_text.strip()}"
                        if isinstance(
                            (label := sec.get("name") or sec.get("section")),
                            str,
                        )
                        and label.strip()
                        else sec_text.strip()
                    )
                    for sec in parsed_json["sections"]
                    if isinstance(sec, dict)
                    and isinstance((sec_text := sec.get("lyrics")), str)
                    and sec_text.strip()
                ]
                if section_lyrics:
                    lyrics_parts.append("\n\n".join(section_lyrics))
        elif isinstance(parsed_json, list):
            entry["structure"] = parsed_json
        else:
            plain_lyrics, plain_structure = _parse_lyria3_plain_block(block)
            if plain_lyrics:
                lyrics_parts.append(plain_lyrics)
            if plain_structure:
                existing_structure = entry.get("structure")
                if isinstance(existing_structure, dict):
                    for key, val in plain_structure.items():
                        existing_structure.setdefault(key, val)
                elif existing_structure is None:
                    entry["structure"] = plain_structure

    if lyrics_parts:
        entry["lyrics"] = "\n\n".join(lyrics_parts)

    return entry


def normalize_audio_analysis(
    analysis: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Re-derives lyrics/structure for tracks stored before plain-text parsing.

    Early builds of the lyrics feature stored the ``Caption`` / ``BPM`` /
    ``Mosic`` lines inside ``lyrics`` and no ``structure``. ``raw_text`` was
    always stored, so re-running the write-time parser on it is lossless.

    Read-time shim (used by ``MediaItemResponse``) instead of a backfill:
    tracks that already carry ``structure`` are returned untouched, the result
    is idempotent, and any unexpected error returns the input unchanged so a
    malformed row can never break a gallery read. Delete it once those legacy
    rows no longer matter.
    """
    if not isinstance(analysis, dict):
        return analysis
    tracks = analysis.get("tracks")
    if not isinstance(tracks, list):
        return analysis
    try:
        normalized_tracks = [_normalize_legacy_track(track) for track in tracks]
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Could not normalize audio_analysis tracks; returning them as-is.",
            exc_info=True,
        )
        return analysis
    if normalized_tracks == tracks:
        return analysis
    return {**analysis, "tracks": normalized_tracks}


def _normalize_legacy_track(track: Any) -> Any:
    """Splits metadata out of one stored track unless it is already parsed."""
    if not isinstance(track, dict) or "structure" in track:
        return track
    raw_text = track.get("raw_text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return track
    parsed = _extract_lyria3_text({"output_text": raw_text})
    if not parsed or "structure" not in parsed:
        # No metadata to split out (e.g. tagged lyrics only): keep as stored.
        return track
    normalized = {**track, **parsed}
    if "lyrics" not in parsed:
        # Instrumental: the metadata lines were the only "lyrics".
        normalized.pop("lyrics", None)
    return normalized
