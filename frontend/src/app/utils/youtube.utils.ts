/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/* eslint-disable n/no-unsupported-features/node-builtins */
export function extractYouTubeVideoId(
  url: string | null | undefined,
): string | null {
  if (!url) return null;
  const trimmed = url.trim();
  if (!trimmed) return null;

  try {
    const parsed = new URL(trimmed);
    const hostname = parsed.hostname.toLowerCase();
    const isYouTube =
      hostname === 'youtube.com' ||
      hostname.endsWith('.youtube.com') ||
      hostname === 'youtube-nocookie.com' ||
      hostname.endsWith('.youtube-nocookie.com');
    const isYoutuBe = hostname === 'youtu.be' || hostname.endsWith('.youtu.be');

    if (isYouTube) {
      if (
        parsed.pathname.startsWith('/embed/') ||
        parsed.pathname.startsWith('/shorts/') ||
        parsed.pathname.startsWith('/v/')
      ) {
        const parts = parsed.pathname.split('/');
        const id = parts[2] || parts[1];
        if (id && id.length === 11) return id;
      }
      const v = parsed.searchParams.get('v');
      if (v && v.length === 11) return v;
    } else if (isYoutuBe) {
      const id = parsed.pathname.slice(1).split('/')[0];
      if (id && id.length === 11) return id;
    } else {
      return null;
    }
  } catch {
    // Ignore invalid URL exceptions and fall back to regex
  }

  // Regex fallback
  const regExp =
    /^.*(youtu\.be\/|v\/|u\/\w\/|embed\/|shorts\/|watch\?v=|&v=)([^#&?]{11})/;
  const match = trimmed.match(regExp);
  return match && match[2].length === 11 ? match[2] : null;
}

export function getYouTubeThumbnailUrl(
  videoId: string | null | undefined,
): string | null {
  if (!videoId) return null;
  return `https://img.youtube.com/vi/${videoId}/mqdefault.jpg`;
}
