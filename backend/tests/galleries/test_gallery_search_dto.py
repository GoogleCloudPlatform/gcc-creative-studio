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
"""Tests for the gallery search DTO."""

from src.common.base_dto import GenerationModelEnum
from src.galleries.dto.gallery_search_dto import GallerySearchDto


def test_gallery_search_dto_accepts_argon_model_filter():
    """The gallery filter accepts the Argon model ID."""
    gallery_filter = GallerySearchDto(model="gemini-4-argon")
    assert gallery_filter.model is GenerationModelEnum.GEMINI_4_ARGON
