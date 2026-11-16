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
"""Canonical frontend mutation payloads used by API DTO contract tests."""

CANONICAL_BROWSER_PAYLOADS: list[tuple[str, str, dict]] = [
    ("POST", "/api/workbench/render", {"timeline_id": 7}),
    (
        "PUT",
        "/api/workbench/timelines/{}",
        {
            "timeline_id": 7,
            "workspace_id": 1,
            "title": "Timeline",
            "video_clips": [
                {
                    "asset_ref": {"id": 12, "type": "media_item"},
                    "trim": {
                        "offset_seconds": 0.0,
                        "duration_seconds": 5.0,
                    },
                    "first_frame_asset_ref": None,
                    "last_frame_asset_ref": None,
                    "placeholder": None,
                    "volume": 1.0,
                    "speed": 1.0,
                }
            ],
            "audio_clips": [
                {
                    "start_at": {
                        "video_clip_index": -1,
                        "offset_seconds": 0.0,
                    },
                    "asset_ref": {"id": 19, "type": "media_item"},
                    "trim": {
                        "offset_seconds": 0.0,
                        "duration_seconds": None,
                    },
                    "volume": 0.2,
                    "fade_in_duration_seconds": 0.5,
                    "fade_out_duration_seconds": 0.5,
                }
            ],
            "transitions": [{"type": "fade", "duration_seconds": 0.5}],
        },
    ),
    (
        "POST",
        "/api/tags",
        {"name": "hero", "workspace_id": 1, "color": "#fff"},
    ),
    ("PUT", "/api/tags/{}", {"name": "renamed"}),
    (
        "POST",
        "/api/tags/bulk-assign",
        {
            "workspace_id": 1,
            "item_ids": [1, 2],
            "item_type": "media_item",
            "tag_names": ["hero"],
        },
    ),
    (
        "POST",
        "/api/folders",
        {
            "name": "Shots",
            "workspaceId": 1,
            "parentId": None,
            "color": None,
        },
    ),
    ("PATCH", "/api/folders/{}", {"name": "Shots V2", "parentId": 3}),
    (
        "POST",
        "/api/folders/move-items",
        {
            "workspaceId": 1,
            "mediaItemIds": [10],
            "sourceAssetIds": [],
            "folderIds": [],
            "destinationFolderId": 2,
            "conflictStrategy": "keep_both",
        },
    ),
    (
        "POST",
        "/api/folders/copy-items",
        {
            "workspaceId": 1,
            "mediaItemIds": [10],
            "destinationFolderId": 2,
        },
    ),
    (
        "POST",
        "/api/gallery/bulk-delete",
        {"items": [{"id": 1, "type": "media_item"}], "workspace_id": 1},
    ),
    (
        "POST",
        "/api/gallery/bulk-download",
        {"items": [{"id": 1, "type": "media_item"}], "workspace_id": 1},
    ),
    (
        "POST",
        "/api/gallery/bulk-copy",
        {
            "items": [{"id": 1, "type": "media_item"}],
            "target_workspace_id": 2,
            "conflict_strategy": "merge",
        },
    ),
    (
        "POST",
        "/api/gallery/bulk-move",
        {
            "items": [{"id": 1, "type": "media_item"}],
            "targetWorkspaceId": 2,
            "conflictStrategy": "keep_both",
        },
    ),
    ("POST", "/api/workspaces", {"name": "Brand Workspace"}),
    (
        "POST",
        "/api/workspaces/{}/invites",
        {"email": "user@example.com", "role": "editor"},
    ),
    ("PUT", "/api/users/{}", {"roles": ["user", "creator"]}),
    (
        "POST",
        "/api/images/generate-images",
        {
            "prompt": "Hero shoe shot",
            "workspaceId": 1,
            "aspectRatio": "1:1",
            "numberOfMedia": 1,
            "useBrandGuidelines": False,
            "sourceMediaItems": [
                {"mediaItemId": 10, "mediaIndex": 0, "role": "input"}
            ],
        },
    ),
    (
        "POST",
        "/api/images/generate-images",
        {
            "prompt": "Hero shoe shot with shared brand context",
            "workspaceId": 1,
            "contextWorkspaceId": 5,
            "parentMediaItemId": 10,
            "aspectRatio": "1:1",
            "numberOfMedia": 1,
            "useBrandGuidelines": True,
            "sourceMediaItems": [
                {"mediaItemId": 10, "mediaIndex": 0, "role": "input"}
            ],
        },
    ),
    (
        "POST",
        "/api/videos/generate-videos",
        {
            "prompt": "Slow pan across studio",
            "workspaceId": 1,
            "aspectRatio": "16:9",
            "numberOfMedia": 1,
        },
    ),
    (
        "POST",
        "/api/videos/generate-videos",
        {
            "prompt": "Slow pan with shared context",
            "workspaceId": 1,
            "contextWorkspaceId": 5,
            "parentMediaItemId": 10,
            "aspectRatio": "16:9",
            "numberOfMedia": 1,
        },
    ),
    (
        "POST",
        "/api/videos/concatenate",
        {
            "name": "Concatenated Video",
            "workspaceId": 1,
            "parentMediaItemId": 10,
            "inputs": [
                {"id": 10, "type": "media_item"},
                {"id": 11, "type": "source_asset"},
            ],
            "aspectRatio": "16:9",
        },
    ),
    (
        "POST",
        "/api/images/generate-images-for-vto",
        {
            "workspaceId": 1,
            "numberOfMedia": 1,
            "personImage": {"sourceAssetId": 5},
            "topImage": {
                "sourceMediaItem": {"mediaItemId": 9, "mediaIndex": 0}
            },
        },
    ),
    (
        "POST",
        "/api/images/generate-images-for-vto",
        {
            "workspaceId": 1,
            "contextWorkspaceId": 5,
            "parentMediaItemId": 9,
            "numberOfMedia": 4,
            "personImage": {"sourceAssetId": 5},
            "topImage": {
                "sourceMediaItem": {"mediaItemId": 9, "mediaIndex": 0}
            },
        },
    ),
    (
        "POST",
        "/api/audios/generate",
        {
            "prompt": "Upbeat synth bed",
            "workspaceId": 1,
            "sampleCount": 1,
            "parentMediaItemId": 8,
        },
    ),
    (
        "POST",
        "/api/brand-guidelines/generate-upload-url",
        {
            "filename": "brand.pdf",
            "contentType": "application/pdf",
            "size": 1024,
            "workspaceId": 1,
        },
    ),
    (
        "POST",
        "/api/brand-guidelines/finalize-upload",
        {
            "workspace_id": 1,
            "gcs_uri": "gs://b/brand.pdf",
            "name": "Brand Book",
            "original_filename": "brand.pdf",
        },
    ),
    (
        "POST",
        "/api/source_assets/generate-upload-url",
        {
            "workspaceId": 1,
            "filename": "photo.png",
            "contentType": "image/png",
            "size": 2048,
        },
    ),
    (
        "POST",
        "/api/source_assets/finalize-upload",
        {
            "workspaceId": 1,
            "folderId": 3,
            "gcsUri": "gs://b/photo.png",
            "filename": "photo.png",
            "mimeType": "image/png",
            "size": 2048,
        },
    ),
    (
        "POST",
        "/api/agent/chat",
        {
            "sessionId": "sess-1",
            "appName": "ads_x",
            "newMessage": {"role": "user", "parts": [{"text": "hi"}]},
            "streaming": True,
            "workspaceId": 1,
        },
    ),
    (
        "PUT",
        "/api/agent/sessions/{}/character",
        {
            "workspaceId": 1,
            "appName": "ads_x",
            "profile": {
                "name": "Ada",
                "role": "creator",
                "gender": "Female",
                "ageRange": "30-35",
                "appearance": "curly hair",
                "clothing": "blue jacket",
                "personality": "warm",
            },
            "assetRef": {"id": 9, "assetType": "generated"},
            "prompt": "studio portrait",
        },
    ),
]
