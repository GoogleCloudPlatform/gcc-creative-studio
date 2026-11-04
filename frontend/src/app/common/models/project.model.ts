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

/**
 * A Workbench project (`/api/projects`): any number of agent chats, each with
 * its own storyboard and timeline, plus manual timelines. Owned by one user
 * inside one workspace, and visible to that owner only.
 */
export interface Project {
  id: number;
  workspace_id: number;
  owner_id: number;
  name: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
  session_count: number;
  /** Most recently used chat of the project, `null` when it has none. */
  latest_session_id: string | null;
  /** Newest manual (storyboard-less) timeline, `null` when it has none. */
  latest_timeline_id: number | null;
}

/** Body of `POST /api/projects`. */
export interface ProjectCreate {
  workspace_id: number;
  name: string;
}

/**
 * Query of `GET /api/projects/resolve`: exactly one child id, so a deep link
 * that only names a chat, storyboard or timeline can find its project.
 */
export type ProjectResolveQuery =
  | {session_id: string}
  | {storyboard_id: number | string}
  | {timeline_id: number | string};
