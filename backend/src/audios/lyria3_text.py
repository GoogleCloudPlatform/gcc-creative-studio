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
    r"^(caption|bpm|mosic|tempo|key|genre|mood|time[ _-]?signature|"
    r"duration(?:_secs)?|good_crop)\s*:\s*(.*)$",
    re.IGNORECASE,
)
_DOUBLE_BRACKET_SECTION = re.compile(
    r"^\[\[\s*([A-Za-z][A-Za-z0-9 _-]*?)\s*\]\]$"
)
_DOUBLE_BRACKET_SEARCH = re.compile(
    r"(?m)^\[\[\s*[A-Za-z][A-Za-z0-9 _-]*?\s*\]\]\s*$"
)
_LETTER_INDEX_CODE = re.compile(r"^([A-Za-z]+)(\d+)$")
_LINE_TIMECODE = re.compile(r"^\[(\d+(?:\.\d+)?)?:(\d+(?:\.\d+)?)?\]\s*(.*)$")
_CAPTION_LEAD_SPLIT = re.compile(
    r",|\b(?:defined|characterized|anchored|featuring|built|designed)\b",
    re.IGNORECASE,
)
_SECTION_ROLE_RE = re.compile(
    r"\b(pre[ -]?chorus|post[ -]?chorus|intro(?:duction)?|outro|coda|"
    r"verse|chorus|refrain|hook|drop|build[ -]?up|riser|breakdown|"
    r"bridge|interlude|instrumental[ -]+break|solo|climax|finale)\b",
    re.IGNORECASE,
)
_ROLE_LABELS: dict[str, str] = {
    "intro": "Intro",
    "introduction": "Intro",
    "verse": "Verse",
    "prechorus": "Pre-Chorus",
    "chorus": "Chorus",
    "refrain": "Chorus",
    "postchorus": "Post-Chorus",
    "hook": "Hook",
    "drop": "Drop",
    "buildup": "Buildup",
    "riser": "Buildup",
    "breakdown": "Breakdown",
    "bridge": "Bridge",
    "interlude": "Interlude",
    "instrumentalbreak": "Interlude",
    "solo": "Solo",
    "climax": "Climax",
    "finale": "Climax",
    "outro": "Outro",
    "coda": "Outro",
}
_INITIAL_LETTER_ROLES: dict[str, str] = {
    "I": "Intro",
    "V": "Verse",
    "P": "Pre-Chorus",
    "C": "Chorus",
    "B": "Bridge",
    "S": "Solo",
    "O": "Outro",
}
_FALLBACK_MIDDLE_ROLES = ("Verse", "Chorus", "Bridge", "Breakdown")


def _coerce_lyria3_scalar(value: str) -> int | float | str:
    """Converts numeric metadata strings (e.g. ``'90.0'``, ``'4.5'``) to numbers."""
    stripped = value.strip()
    try:
        num = float(stripped)
        return int(num) if num.is_integer() else num
    except ValueError:
        return stripped


_LYRIA_3_UNBRACKETED_SECTION_RE = re.compile(
    r"^(?:verse|chorus|pre[- ]?chorus|post[- ]?chorus|bridge|intro|outro|hook|refrain|interlude|coda)\b[^:]{0,20}:",
    re.IGNORECASE,
)


def _extract_role_from_caption(caption: str) -> str | None:
    """Infers a human-readable section role from a section caption's opening."""
    first_sentence = caption.strip().split(".", 1)[0]
    if not first_sentence:
        return None
    lead_clause = _CAPTION_LEAD_SPLIT.split(first_sentence, maxsplit=1)[0]
    for candidate in (lead_clause, first_sentence):
        match = _SECTION_ROLE_RE.search(candidate)
        if match:
            norm = re.sub(r"[\s-]+", "", match.group(1).lower())
            return _ROLE_LABELS.get(norm)
    return None


def _clean_section_lines(
    lines: Sequence[str],
) -> tuple[int | float | None, str | None]:
    """Strips ``[start:end]`` / ``[:]`` prefixes -> ``(start, text)``."""
    start_seconds: int | float | None = None
    cleaned: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        time_match = _LINE_TIMECODE.match(stripped)
        if time_match:
            if time_match.group(1) and start_seconds is None:
                val = _coerce_lyria3_scalar(time_match.group(1))
                if isinstance(val, (int, float)):
                    start_seconds = val
            text_part = time_match.group(3).strip()
        else:
            text_part = stripped
        if text_part and text_part.lower() != "<instrumental>":
            cleaned.append(text_part)
    return start_seconds, ("\n".join(cleaned) or None)


def _assign_section_roles(sections: list[dict[str, Any]]) -> None:
    """Populates ``role`` and ``name`` on each parsed ``[[...]]`` section."""
    letter_counts: dict[str, int] = {}
    sibling_roles: dict[str, str] = {}

    for sec in sections:
        letter = sec.get("letter")
        if isinstance(letter, str):
            letter_counts[letter] = letter_counts.get(letter, 0) + 1
        if letter is None:
            sec["role"] = sec["id"]
            continue
        caption = sec.get("caption")
        role = (
            _extract_role_from_caption(caption)
            if isinstance(caption, str)
            else None
        )
        if role:
            sec["role"] = role
            if role not in {"Intro", "Outro", "Climax"}:
                sibling_roles.setdefault(letter, role)

    use_initials = (
        bool(letter_counts)
        and "A" not in letter_counts
        and set(letter_counts).issubset(_INITIAL_LETTER_ROLES)
    )
    fallback_by_letter: dict[str, str] = {}
    middle_idx = 0
    total = len(sections)

    for pos, sec in enumerate(sections):
        if "role" not in sec:
            letter = str(sec.get("letter") or "")
            if use_initials and letter in _INITIAL_LETTER_ROLES:
                sec["role"] = _INITIAL_LETTER_ROLES[letter]
            elif pos == 0 and letter_counts.get(letter, 0) == 1 and total >= 3:
                sec["role"] = "Intro"
            elif (
                pos == total - 1
                and letter_counts.get(letter, 0) == 1
                and total >= 2
            ):
                sec["role"] = "Outro"
            elif letter in sibling_roles:
                sec["role"] = sibling_roles[letter]
            elif letter in fallback_by_letter:
                sec["role"] = fallback_by_letter[letter]
            else:
                assigned = (
                    _FALLBACK_MIDDLE_ROLES[middle_idx]
                    if middle_idx < len(_FALLBACK_MIDDLE_ROLES)
                    else "Section"
                )
                middle_idx += 1
                if letter:
                    fallback_by_letter[letter] = assigned
                sec["role"] = assigned

        sec_role = str(sec["role"])
        sec_idx = sec.get("index")
        sec["name"] = (
            f"{sec_role} {sec_idx}" if sec_idx is not None else sec_role
        )


def _parse_sectioned_plain_block(
    block: str,
) -> tuple[str | None, dict[str, Any]]:
    """Parses Lyria 3 Pro ``[[LetterIndex]]`` vocals, metadata, and captions."""
    structure: dict[str, Any] = {}
    preamble: list[str] = []
    chunks: list[tuple[str, bool, list[str]]] = []
    current_chunk: tuple[str, bool, list[str]] | None = None
    seen_metadata = False
    in_multiline_caption = False

    for raw_line in block.splitlines():
        stripped = raw_line.strip()
        sec_match = _DOUBLE_BRACKET_SECTION.match(stripped)
        if sec_match:
            in_multiline_caption = False
            current_chunk = (sec_match.group(1), seen_metadata, [])
            chunks.append(current_chunk)
            continue

        meta_match = _LYRIA_3_META_LINE.match(stripped)
        if meta_match:
            current_chunk = None
            seen_metadata = True
            norm_key = re.sub(r"[\s-]+", "_", meta_match.group(1).lower())
            raw_val = meta_match.group(2).strip()
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
            if not stripped.startswith(
                "["
            ) and not _LYRIA_3_UNBRACKETED_SECTION_RE.match(stripped):
                prev = structure.get("caption", "")
                structure["caption"] = f"{prev} {stripped}".strip()
                continue
            in_multiline_caption = False

        if current_chunk is not None:
            current_chunk[2].append(raw_line)
        elif stripped:
            preamble.append(stripped)

    instrumental_preamble = (
        len(preamble) == 1 and preamble[0].lower() == "<instrumental>"
    )
    sections_by_id: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    id_counts: dict[str, int] = {}

    normalized_chunks: list[
        tuple[str, str | None, int | None, bool, list[str]]
    ] = []
    for raw_tag, after_meta, lines in chunks:
        code_match = _LETTER_INDEX_CODE.match(raw_tag.strip())
        if code_match:
            letter: str | None = code_match.group(1).upper()
            idx: int | None = int(code_match.group(2))
            sec_id = f"{letter}{idx}"
        else:
            letter = None
            idx = None
            sec_id = raw_tag.strip()
        id_counts[sec_id] = id_counts.get(sec_id, 0) + 1
        normalized_chunks.append((sec_id, letter, idx, after_meta, lines))

    for sec_id, letter, idx, after_meta, lines in normalized_chunks:
        start_sec, text = _clean_section_lines(lines)
        text_str = text or ""
        looks_like_single_caption = (
            len(text_str) >= 120 and "\n" not in text_str and ". " in text_str
        )
        is_caption = (
            sec_id in seen_ids
            or after_meta
            or instrumental_preamble
            or (id_counts[sec_id] == 1 and looks_like_single_caption)
        )
        seen_ids.add(sec_id)
        sec = sections_by_id.get(sec_id)
        if sec is None:
            sec = {"id": sec_id}
            if letter is not None:
                sec["letter"] = letter
            if idx is not None:
                sec["index"] = idx
            sections_by_id[sec_id] = sec
        if start_sec is not None and "start_seconds" not in sec:
            sec["start_seconds"] = start_sec
        if text:
            field = "caption" if is_caption else "lyrics"
            sec[field] = f"{sec[field]}\n{text}" if field in sec else text

    sections_list = list(sections_by_id.values())
    if sections_list:
        _assign_section_roles(sections_list)
        structure["sections"] = sections_list

    lyrics_blocks: list[str] = []
    if preamble and not instrumental_preamble:
        lyrics_blocks.append("\n".join(preamble))
    for sec in sections_list:
        sec_lyrics = sec.get("lyrics")
        if sec_lyrics:
            sec_name = sec["name"]
            lyrics_blocks.append(f"[{sec_name}]\n{sec_lyrics}")
    return ("\n\n".join(lyrics_blocks) or None), structure


def _parse_lyria3_plain_block(block: str) -> tuple[str | None, dict[str, Any]]:
    """Splits a plain-text Lyria 3 block into ``(lyrics, structure)``."""
    if _DOUBLE_BRACKET_SEARCH.search(block):
        return _parse_sectioned_plain_block(block)

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
            if not stripped.startswith(
                "["
            ) and not _LYRIA_3_UNBRACKETED_SECTION_RE.match(stripped):
                prev = structure.get("caption", "")
                structure["caption"] = f"{prev} {stripped}".strip()
                continue
            in_multiline_caption = False

        lyrics_lines.append(raw_line)

    cleaned_lyrics = "\n".join(lyrics_lines).strip()
    return (cleaned_lyrics or None), structure


def _extract_section_lyrics(sections: Sequence[Any]) -> str | None:
    """Extracts formatted ``[Label]\\nLyrics`` text from a sequence of section dicts."""
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
        for sec in sections
        if isinstance(sec, dict)
        and isinstance((sec_text := sec.get("lyrics")), str)
        and sec_text.strip()
    ]
    return "\n\n".join(section_lyrics) if section_lyrics else None


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
            existing_structure = entry.get("structure")
            if isinstance(existing_structure, dict):
                entry["structure"] = {**existing_structure, **parsed_json}
            elif isinstance(existing_structure, list):
                merged = {"sections": existing_structure, **parsed_json}
                entry["structure"] = merged
            else:
                entry["structure"] = dict(parsed_json)

            inline_lyrics = parsed_json.get("lyrics")
            if isinstance(inline_lyrics, str) and inline_lyrics.strip():
                lyrics_parts.append(inline_lyrics.strip())
            elif isinstance(parsed_json.get("sections"), list):
                sec_lyrics = _extract_section_lyrics(parsed_json["sections"])
                if sec_lyrics:
                    lyrics_parts.append(sec_lyrics)
        elif isinstance(parsed_json, list):
            sec_lyrics = _extract_section_lyrics(parsed_json)
            if sec_lyrics:
                lyrics_parts.append(sec_lyrics)
            existing_structure = entry.get("structure")
            if isinstance(existing_structure, dict):
                existing_structure.setdefault("sections", parsed_json)
            else:
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
                elif isinstance(existing_structure, list):
                    entry["structure"] = {
                        **plain_structure,
                        "sections": existing_structure,
                    }
                elif existing_structure is None:
                    entry["structure"] = plain_structure

    if lyrics_parts:
        entry["lyrics"] = "\n\n".join(lyrics_parts)

    return entry


def normalize_audio_analysis(
    analysis: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Re-derives lyrics/structure for tracks stored before full parsing.

    Early builds stored ``Caption`` / ``BPM`` / ``Mosic`` lines inside
    ``lyrics`` with no ``structure``, or stored ``lyria-3-pro-preview``
    ``[[LetterIndex]]`` sections inside ``lyrics`` with scalar-only
    ``structure``. ``raw_text`` was always stored, so re-running the
    write-time parser on it is lossless and idempotent.
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
    """Splits metadata and ``[[...]]`` sections out of stored tracks."""
    if not isinstance(track, dict):
        return track
    raw_text = track.get("raw_text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return track
    existing_structure = track.get("structure")
    if "structure" in track:
        needs_section_upgrade = (
            isinstance(existing_structure, dict)
            and "sections" not in existing_structure
            and bool(_DOUBLE_BRACKET_SEARCH.search(raw_text))
        )
        if not needs_section_upgrade:
            return track
    parsed = _extract_lyria3_text({"output_text": raw_text})
    if not parsed or "structure" not in parsed:
        # No metadata to split out (e.g. tagged lyrics only): keep as stored.
        return track
    normalized = {**track, **parsed}
    if isinstance(existing_structure, dict) and isinstance(
        parsed.get("structure"), dict
    ):
        normalized["structure"] = {
            **existing_structure,
            **parsed["structure"],
        }
    if "lyrics" not in parsed:
        # Instrumental: the metadata/captions were the only "lyrics".
        normalized.pop("lyrics", None)
    return normalized
