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
"""Tests for the read-time ``audio_analysis`` shim in ``lyria3_text``."""

from unittest.mock import Mock

import pytest

from src.audios import lyria3_text
from src.audios.lyria3_text import normalize_audio_analysis
from src.common.base_dto import MimeTypeEnum
from src.galleries.dto.gallery_response_dto import MediaItemResponse

# Shape stored by early builds of the lyrics feature (mirrors real rows):
# the metadata lines stayed inside ``lyrics`` and there is no ``structure``.
LEGACY_RAW_TEXT = (
    "[0.0:5.3] Darkness descends on a world torn asunder\n"
    "[5.3:10.6] THE SKY BREAKS APART WITH A CATACLYSMIC THUNDER\n\n"
    "Caption: Maximalist Symphonic Metal built to evoke an ocean storm.\n"
    "Driving double-kick drums and soaring strings.\n"
    "Mosic: 4.5\n"
    "BPM: 90.0"
)
LEGACY_TRACK = {"raw_text": LEGACY_RAW_TEXT, "lyrics": LEGACY_RAW_TEXT}
NORMALIZED_TRACK = {
    "raw_text": LEGACY_RAW_TEXT,
    "lyrics": (
        "[0.0:5.3] Darkness descends on a world torn asunder\n"
        "[5.3:10.6] THE SKY BREAKS APART WITH A CATACLYSMIC THUNDER"
    ),
    "structure": {
        "caption": (
            "Maximalist Symphonic Metal built to evoke an ocean storm. "
            "Driving double-kick drums and soaring strings."
        ),
        "mosic": 4.5,
        "bpm": 90,
    },
}


class TestNormalizeAudioAnalysis:
    """Read-time shim that splits metadata out of legacy Lyria 3 tracks."""

    def test_splits_metadata_out_of_legacy_lyrics(self):
        analysis = {"tracks": [LEGACY_TRACK, None]}

        result = normalize_audio_analysis(analysis)

        assert result == {"tracks": [NORMALIZED_TRACK, None]}
        # The stored payload is never mutated.
        assert analysis == {"tracks": [LEGACY_TRACK, None]}

    def test_is_idempotent_and_returns_parsed_payloads_untouched(self):
        once = normalize_audio_analysis({"tracks": [LEGACY_TRACK]})
        parsed = {"tracks": [NORMALIZED_TRACK]}

        assert normalize_audio_analysis(once) is once
        assert normalize_audio_analysis(parsed) is parsed

    def test_instrumental_legacy_track_drops_metadata_only_lyrics(self):
        raw = (
            "Caption: Warm lo-fi hip-hop with Rhodes chords.\n"
            "Mosic: 4.5\n"
            "BPM: 84.5"
        )

        result = normalize_audio_analysis(
            {"tracks": [{"raw_text": raw, "lyrics": raw}]}
        )

        assert result == {
            "tracks": [
                {
                    "raw_text": raw,
                    "structure": {
                        "caption": "Warm lo-fi hip-hop with Rhodes chords.",
                        "mosic": 4.5,
                        "bpm": 84.5,
                    },
                }
            ]
        }

    def test_keeps_tracks_without_metadata_as_stored(self):
        lyrics = "[Verse 1]\nNeon lights on wet asphalt"
        analysis = {
            "tracks": [{"raw_text": lyrics, "lyrics": lyrics, "extra": 1}],
            "version": 2,
        }

        assert normalize_audio_analysis(analysis) is analysis

    def test_preserves_unknown_keys_when_normalizing(self):
        result = normalize_audio_analysis(
            {"tracks": [{**LEGACY_TRACK, "extra": 1}], "version": 2}
        )

        assert result == {
            "tracks": [{**NORMALIZED_TRACK, "extra": 1}],
            "version": 2,
        }

    @pytest.mark.parametrize(
        "analysis",
        [
            None,
            {},
            {"tracks": None},
            {"tracks": "not-a-list"},
            {"tracks": [1, "x", {"lyrics": "no raw text"}, {"raw_text": " "}]},
        ],
    )
    def test_unexpected_shapes_are_returned_unchanged(self, analysis):
        assert normalize_audio_analysis(analysis) is analysis

    def test_parser_errors_never_break_reads(self, monkeypatch):
        monkeypatch.setattr(
            lyria3_text,
            "_extract_lyria3_text",
            Mock(side_effect=RuntimeError("boom")),
        )
        analysis = {"tracks": [LEGACY_TRACK]}

        assert normalize_audio_analysis(analysis) is analysis


class TestMediaItemResponseAudioAnalysis:
    """``GET /gallery/item/{id}`` responses carry normalized tracks."""

    @staticmethod
    def _response(audio_analysis):
        return MediaItemResponse(
            id=1,
            workspace_id=1,
            user_email="test@example.com",
            mime_type=MimeTypeEnum.AUDIO_MPEG,
            model="lyria-3-pro-preview",
            aspect_ratio="16:9",
            gcs_uris=["gs://bucket/track.mp3"],
            audio_analysis=audio_analysis,
        )

    def test_gallery_item_response_normalizes_legacy_tracks(self):
        response = self._response({"tracks": [LEGACY_TRACK]})

        assert response.audio_analysis == {"tracks": [NORMALIZED_TRACK]}

    def test_gallery_item_response_without_audio_analysis(self):
        assert self._response(None).audio_analysis is None


class TestExtractLyria3TextEdgeCases:
    """Mixed block orders and unbracketed lyric section headers."""

    def test_extract_lyria3_text_merges_plain_metadata_before_json_dict_and_json_list_sections(
        self,
    ):
        plain_meta = "BPM: 122\nKey: F# minor\nCaption: Atmospheric synth pop."
        json_dict_block = (
            '{"sections": [{"name": "Verse 1", "lyrics": "City lights fade"}]}'
        )
        merged_dict = lyria3_text._extract_lyria3_text(
            {
                "outputs": [
                    {"type": "text", "text": plain_meta},
                    {"type": "text", "text": json_dict_block},
                ]
            }
        )
        assert merged_dict is not None
        assert merged_dict["structure"]["bpm"] == 122
        assert merged_dict["structure"]["key"] == "F# minor"
        assert merged_dict["structure"]["caption"] == "Atmospheric synth pop."
        assert merged_dict["structure"]["sections"] == [
            {"name": "Verse 1", "lyrics": "City lights fade"}
        ]
        assert merged_dict["lyrics"] == "[Verse 1]\nCity lights fade"

        json_list_block = (
            '[{"section": "Chorus", "lyrics": "Hold on to the night"}]'
        )
        merged_list = lyria3_text._extract_lyria3_text(
            {
                "outputs": [
                    {"type": "text", "text": json_list_block},
                    {"type": "text", "text": plain_meta},
                ]
            }
        )
        assert merged_list is not None
        assert merged_list["structure"] == {
            "bpm": 122,
            "key": "F# minor",
            "caption": "Atmospheric synth pop.",
            "sections": [
                {"section": "Chorus", "lyrics": "Hold on to the night"}
            ],
        }
        assert merged_list["lyrics"] == "[Chorus]\nHold on to the night"

    def test_parse_lyria3_plain_block_stops_multiline_caption_at_unbracketed_section_headers(
        self,
    ):
        block = (
            "Caption: Upbeat indie rock anthem\n"
            "with bright jangly guitars.\n"
            "Verse 1:\n"
            "Running down the boulevard\n"
            "Chorus:\n"
            "Never looking back"
        )
        lyrics, structure = lyria3_text._parse_lyria3_plain_block(block)
        assert structure == {
            "caption": "Upbeat indie rock anthem with bright jangly guitars."
        }
        assert lyrics == (
            "Verse 1:\nRunning down the boulevard\nChorus:\nNever looking back"
        )
