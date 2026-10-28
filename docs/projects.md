# Workbench projects

A **project** groups one user's Workbench work inside one workspace: their agent chats, each chat's storyboard and timeline, and their manual timelines. Projects are **owner-only**. Vertex AI Agent Engine (or the local Izumi container) remains the source of truth for the conversations themselves; Creative Studio only records which project each chat belongs to.

This document holds the design and the rules that keep it working. `GEMINI.md` keeps a short summary that points here.

## Data model

The tables are created by migration `b3f1c9d2e8a4`:

| Table / column | Notes |
|---|---|
| `projects` | `workspace_id`, `owner_id`, `name` (1–120 chars), `is_default`. The partial unique index `uq_projects_default_per_owner` allows one default project per (workspace, owner), so `ProjectRepository.ensure_default` (`INSERT … ON CONFLICT DO NOTHING`) is race-safe. |
| `storyboards.project_id` | `NOT NULL`. |
| `timelines.project_id` | Nullable. Only legacy rows the migration could not attribute are `NULL`, and those are **admin-only**. |
| `agent_sessions` | The chat registry: `session_id` → project, owner, workspace, `app_name`, `title`, `summary`, `last_used_at`, and `restored_at` (migration `d7e3b1a9c5f2`, see [Restoring an expired chat](#restoring-an-expired-chat)). |

There are deliberately no ORM relationships on `Project`. Deletes rely on the foreign keys' `ON DELETE CASCADE`: `scenes`, `timelines` (from their storyboard), `video_clips`, `audio_clips`, `agent_sessions`, `storyboards.project_id` and `timelines.project_id`. `BaseRepository.delete` is a bulk SQL `DELETE`, so ORM cascades never run.

### Backfill (non-destructive)

- Every (workspace, user) that owns storyboards gets one "Default project", and all of that user's records in the workspace are attached to it.
- A timeline follows its storyboard, or the storyboard of its session.
- **Legacy orphans** are the timelines with neither: no storyboard, and no session that owns one. When `timelines.workspace_id` names a real workspace, an orphan goes to the **workspace owner's** Default project, whatever its `user_id`. Its creator therefore loses it: in the public workspace, the owner is the admin. This is an accepted trade-off, since the pre-projects UI never sent `user_id` for manual timelines. All other orphans keep `project_id = NULL`.
- Chats that storyboards reference are registered, with no activity time. Some may no longer exist: before projects, "Delete chat" removed the agent session but left `storyboards.session_id` in place. See [Chat activity](#chat-activity-and-latest_session_id).
- An environment that ever ran the old `feature/projects` branch has the revision `fa5148bc6f42_create_projects_table` and an existing `projects` table. Both must be cleaned up by hand before this migration can run.

## Access rules

- `ProjectAuth.authorize` = owner **and** `workspace_auth.authorize`. Projects cannot be shared: owning a public workspace grants nothing, and neither does the admin role.
- `TimelineAuth` guards every timeline-by-id route, and both render routes, through the timeline's project.
- The storyboard GET/PUT/DELETE-by-id routes call `ProjectService.authorize_storyboard` (owner, then `ProjectAuth`) **before anything else**. Loading a storyboard presigns a URL per scene, so that work must never run for a caller who is then refused.
- `GET /api/storyboards` returns only the caller's storyboards, in a workspace they may access.
- On timeline create, the server stamps `user_id`, `workspace_id` and `project_id`; client values are ignored. A timeline PUT never moves `project_id` (it may only claim a `NULL`), and it may only re-link a storyboard of the same project. Its `workspace_id` follows the owning project, including the one a legacy row claims through the storyboard; only a row that stays unattributed keeps the payload's value.
- Name guard methods `authorize` or `ensure_*`, never `assert_*`. Tests replace these classes with mocks, and `unittest.mock` rejects attributes whose names start with `assert`.

## Filing records into projects

- **Izumi never sends `project_id`.** It creates storyboards and timelines with `{workspace_id, session_id}` only, and the registry files them into the chat's project. Never add `project_id` to Izumi tools.
- `ProjectService.resolve_project_for_write` picks, in this order: the storyboard's project → an explicit `project_id` → the registered `session_id` (same workspace) → the user's default project.
- It **never adopts a client-sent `session_id`**. The id proves nothing about ownership, and Agent Engine addresses `{agent}/sessions/{id}` with no user scoping, so registering it would let a caller claim another user's unregistered chat and then delete it. The user-scoped `list_sessions` adopts such a chat into the same default project instead.
- `create_session` resolves the project **before** creating the agent session, so a refused project never leaves an orphan session behind.

## Chats (agent sessions)

- Chats are owner-only on **every session-by-id path**, not just through the registry. `_ensure_session_owner` compares the fetched session's own `user_id` on the messages, detail, `_load_session_state` (characters, storyboard sync) and delete paths. The best-effort detail path re-raises its `ForeignSessionError`, a 403 `HTTPException` subclass.
- `delete_session`:
  - checks the registry and refuses an unregistered foreign chat;
  - never deletes after a failed read (`_get_session_or_none` answers 502);
  - does not swallow a refused workspace;
  - answers 409 (`BUSY_CHAT_DELETE_DETAIL`) while the chat `_is_run_active`, since the run would die at its next `append_event`. The check runs after the owner and workspace checks, so a foreign chat still gets 403, and right before the agent delete, with no await in between. It is per process, with the same caveat as the run guard;
  - only drops the registry row of a chat already gone from the agent.
- `chat()` refuses a foreign chat first, before anything reads the session or `process_stream` appends the caller's token to it. `_ensure_chat_owner` uses the registry row's owner, or, for an unregistered chat only, the fetched session's owner. It answers 403, or 502 when that read fails.
- `_map_session_to_dto` strips the bearer token (`_SECRET_STATE_KEYS`) from the state and from each event's `state_delta`/`stateDelta`: the agent needs the token, a browser never does.
- `list_sessions` adopts unregistered chats (from before projects, or from the ADK dev UI) into the default project, so `GET /api/agent/sessions` can write, idempotently. It never deletes registry rows missing from a partial listing.
- **Expired chats.** Agent Engine sessions expire, and the local Izumi store (the Firestore emulator) forgets every session when it restarts, but the registry row survives. `GET /api/agent/sessions?include_expired=true` appends the caller's registered chats that the listing lacks, flagged `expired: true`, newest first, after the live ones (`_expired_session_dtos`).
  - Only rows with a recorded `last_used_at` count: Creative Studio saw those chats alive. Rows without one are the backfill's dead ids (chats deleted before projects existed) and must stay hidden.
  - The project filter and the agent (`app_name`, `NULL` = `ads_x`) apply.
  - The flag is opt-in, so every other caller keeps the exact listing.
  - An expired chat that still owns one of the caller's storyboards is flagged `restorable` (`StoryboardRepository.session_ids_with_storyboards`, one query for the whole listing).
  - A restored chat whose new session expired too keeps `restored: true` (`restored_at` is never cleared), like every DTO built from a registry row.
- **Titles** live in the registry (`PATCH /api/agent/sessions/{id}`). Old `izumi_topics` localStorage entries are imported once, and an entry is removed only after the server has saved it.
  - A title is generated only when the chat has neither a `topics` entry (kept in memory for the visit) nor a server `title`. Without both checks, `generateTitle` would run on every message and keep renaming the chat.
  - The title callbacks use the session id captured when the message was sent.
  - `updateSessionMetadata` clamps to the DTO limits (200 / 1000 characters), because the fallback title is the user's whole first message.

### Restoring an expired chat

An expired chat's conversation is gone, but its storyboard and timeline are Postgres rows that survive. Restoring brings them back in **the same chat** (registry row, project and title kept) on a new agent session.

- `POST /api/agent/sessions/{id}/restore` (`AgentService.restore_session`) refuses before creating anything:
  - 404 for an unregistered chat, 403 (`ForeignSessionError`) for another user's, 400 when `workspace_id` names another workspace, then `workspace_auth` on the chat's workspace;
  - 409 `This chat has not expired.` while the agent still has the session (`_get_session_or_none`; a failed read answers 502);
  - 409 `This chat has no storyboard to restore.` when the chat owns none of the caller's storyboards.
- Then it creates the session (state `{workspace_id, token}`, like `create_session`) and moves the registry row first: `replace_session_id(old, new, restored=True)` is the claim. A concurrent restore (a double click) finds no row, deletes its own new session (`delete_sessions_best_effort`) and answers 409 `This chat was already restored.` Only then does `StoryboardRepository.reassign_session` move the caller's storyboards of the chat; timelines follow their storyboard.
- The response DTO is built from a fresh `agent_session_repo.get`: the bulk `UPDATE` expires the row's `func.now()` columns, and reading an expired attribute in async SQLAlchemy raises `MissingGreenlet`.
- **A restored chat is never run by Izumi.** `restored_at` marks it and `SessionResponseDto.restored` reports it. `chat()` answers 409 (`RESTORED_CHAT_DETAIL`) right after the owner check, before `touch` or any session read. The new session has no memory of the campaign, so a run would start a new one, and the agent's storyboard tools reuse the chat's records: `create_storyboard(reuse_session_record=True)` finds the chat's storyboard by session (`find_latest_by_session`), `update_storyboard_data` clears its scenes, and `create_timeline(reuse_for_storyboard=…)` replaces its timeline. The user edits the storyboard and timeline by hand, and starts a new chat for new Izumi work. **Do not lift the lock without solving that reuse first.**
- The session-detail path re-creates a missing session too (a `?storyboardId=` link, or a chat that expired after it was listed). `_register_recreated_session` marks that chat restored only when a storyboard came back with it (`restored=storyboard is not None`): an empty expired chat keeps working with Izumi as before. `replace_session_id(restored=False)` never clears an existing mark.

### Chat activity and `latest_session_id`

Entering a project resumes its `latest_session_id`. That is the project's chat with the latest `agent_sessions.last_used_at` (NULLs last), then the latest `created_at`, then the highest `id`.

- `touch`, called from `chat()`, records activity. It is owner-scoped because `chat()` calls it before the agent has validated the id. `register` and `replace_session_id` set the time as well.
- Rows the migration backfilled, or that were adopted, have no recorded activity. `_apply_session_registry` gives them the Agent Engine listing's update time: it passes the time to `adopt`, and `AgentSessionRepository.seed_last_used` fills a missing `last_used_at`. `seed_last_used` never overwrites a recorded time and only writes the user's own rows.
  - A registered chat missing from the listing (deleted outside the Workbench) keeps `NULL` and sorts last.
  - The `CASE` in `seed_last_used` casts its values to `timestamptz` explicitly. Keep the cast: Postgres cannot type bare `CASE` parameters for that column.
- Until the first listing (the first entry after the migration), `latest_session_id` can still name a chat that no longer exists. When the chat the URL names is missing from the project's listing, the chat resumes the project's **most recently updated** listed chat, or starts a new chat if the project has none. No error is shown.

## Deleting a project

- `DELETE /api/projects/{id}` answers **409** in two cases:
  - for the default project (`DEFAULT_PROJECT_DELETE_DETAIL`). Deleting it would only lose its content, since `ensure_default` re-creates it empty; the switcher offers no Delete on it;
  - while any of the project's chats `_is_run_active`. The check is per process, with the same caveat as the run guard.
- Both service steps authorize on their own:
  1. `prepare_project_delete(user, id)` checks the owner and the default project, then returns the registry's `{session_id: app_name}`. It runs before any agent session is touched.
  2. `delete_project(user, id)` checks again before deleting.
- `delete_sessions_best_effort` deletes each chat from its own agent (`app_name`), at most `_SESSION_DELETE_CONCURRENCY` (4) at a time:
  - `_sessions_delete` runs the synchronous Vertex call in `asyncio.to_thread`;
  - `_is_session_not_found` decides by the error's int `code` (genai `APIError`, api_core `NotFound`), and only falls back to the message when there is no code. The fallback matches "not found", never a bare "404": a port (`:4040`) or an id in an outage message would otherwise pass for "already gone".

  `ON DELETE CASCADE` then removes the rest. An agent session that could not be deleted is re-adopted into the default project on the next listing.

## Frontend

### `ProjectStateService`: owner of `projectId`

Provided by `WorkbenchComponent` (not root), it is the only writer of `projectId`. It reconciles every (URL, workspace) emission with `switchMap`, and the latest one wins:

1. The URL names the active project of the active workspace: nothing to do. This is the steady state, and also the echo of its own navigations.
2. First load, or no `projectId`, while a chat, storyboard or timeline id is in the URL: that child is resolved through `GET /api/projects/resolve`, in the order session > storyboard > timeline. The child wins a conflict with `projectId`. A child in another workspace switches the workspace first and is adopted when it emits. **Never resolve the child on every URL change:** after a workspace switch the URL still names the old chat, and resolving it would send the user straight back to the old workspace. A spec covers this.
3. A listed `projectId` (Back/Forward) is adopted after `beforeLeave` has run. The hook is not awaited, but it runs synchronously within the URL emission, before the Workbench (which subscribes after this service) reacts. The flush therefore still saves the project being left. Deep-link adoptions resolve asynchronously and never flush. Any activation clears a pending cross-workspace adoption.
4. Anything else enters the workspace's last project (`cs.workbench.lastProjectByWorkspace`), else its default project. The key holds a JSON object of workspace id → project id. Any other value (arrays included) counts as empty and is rewritten as an object at the next activation.

**Entering a project is ONE merge navigation:** `{projectId, sessionId: latest_session_id, storyboardId: null, timelineId: latest_session_id ? null : latest_timeline_id}`. Several merge navigations in one tick are computed from the same old URL and cancel each other, so never add a second navigate for the same transition. The navigation happens after two steps:

- `beforeLeave`, in which the Workbench flushes its pending autosave. The wait ends at the hook's first value, completion or error, or after `BEFORE_LEAVE_TIMEOUT_MS`. The timeout matters because `saveTimeline()` returns a hot Subject that never settles when a newer save cancels its request; without it, `loading` stayed true and the switcher stayed disabled.
  - The flushed save belongs to the project being left, but on a workspace switch `WorkspaceStateService` has already moved on. `saveTimeline()` therefore sends `activeProjectWorkspaceId`, which `activate()` sets together with `activeProjectId`, and falls back to the switcher's workspace only while no project is active. Pairing the old project with the new workspace made `resolve_project_for_write` answer 400 to the first save of a timeline without a storyboard, and the flush dropped its edits.
- The shared resets: `AgentChatService.resetConversation` and `TimelineStateService.resetForProjectSwitch`.

With rapid switches, only the latest entry applies (`entrySeq`).

### Chat (`ChatInterfaceComponent`)

- It waits for `projectState.isReadyFor(workspaceId, urlProjectId)`. Adopting a project can leave the URL unchanged, so the session loader also re-runs on `toObservable(activeProjectId)`. It handles each URL state only once (`lastGatedParams`); otherwise a plain reload left the chat loading forever.
- A project change resets the chat without navigating. `sessionsLoadSeq` drops late `getSessions` responses, and the sessions cache is keyed by project.
- When the URL names a chat that the project's listing does not contain, the chat opens the most recent listed chat, or a new one (see [Chat activity](#chat-activity-and-latest_session_id)).
- **Expired chats are listed, never opened.** `AgentChatService.getSessions` asks for them but keeps them in `expiredSessions`. `sessions`, and what `getSessions` emits, hold only chats that can be opened, so the URL resume, `mostRecentSession`, `deleteChat` and every other path behave as before. The picker appends expired chats with an `Expired` badge (`studio-dropdown` options take `disabled` and `badge`). The picker also shows when a project only has expired chats.
  - A disabled option uses `mat-button`'s `[disabled]` + `[disabledInteractive]`: Material sets `aria-disabled="true"` but not the native `disabled` attribute, so the tooltip still shows, and `selectOption` drops the click. A raw `[attr.aria-disabled]` binding does not work: `MatButton`'s host binding overrides it.
  - Only a `restorable` expired chat is selectable. `onSessionChange` hands it to `restoreExpiredChat`, which calls `AgentChatService.restoreSession`, moves the chat from `expiredSessions` to the top of `sessions`, and opens it through `loadChatMessages`: the detail returns the moved storyboard, and the timeline loads as for any chat. The others stay disabled and are ignored.
  - `studio-dropdown` keeps its own `value` once an option is clicked, so `resetSessionPicker()` points it back at the open chat until the restore succeeds (otherwise a failed restore left the expired chat displayed as open).
  - The restore request is tracked in `loadSubscription` (torn down with the component), locks the picker through `isLoadingHistory`, and a response that arrives after the user moved on (New Chat) only updates the lists.
  - A URL naming an expired chat still resumes the latest live chat: restoring is always an explicit click.
- **Restored chats are locked for Izumi.** `AgentChatService.chatRestored` holds the open chat's `restored` flag. It lives in the service, like `finalVideoReady`, because a chat panel created later skips the detail load when the URL already matches its state. That skip (`urlMatchesCurrentState`) also drops the `isLoadingHistory` lock raised by `loadChatSessions()`, unless a history request is still in flight: the agent panel is rebuilt (`*ngIf`) on every reopen, and without it the panel stayed on "Loading history..." and hid the banner. Every session-detail handler sets it (`loadChatMessages` and the storyboard-first branch of `loadChatSessions`), and `startNewChat`, `resetConversationState`, `onAgentChange` and `resetConversation` clear it.
  - Once loaded, the composer is swapped for the restored-chat banner, which offers "New chat". While a chat loads, the disabled composer stays in place so the panel does not jump.
  - `sendChatMessage` (which the storyboard's `generateVideoRequest$` also goes through) and `canRetry` refuse a restored chat; the backend answers 409 anyway.
  - Restored chats carry a `Restored` badge in the picker, and no welcome message ("How can I help you today?" would contradict the banner).

**Entering the Workbench must load the project's chat.** A chat counts as loaded only while BOTH `currentSessionId` and the shared `selectedSessionId` name it. When this breaks, the right project is selected but the chat, the storyboard and the timeline stay empty until the user switches to another project and back. The rules:

1. Only the chat writes a non-null `selectedSessionId`, meaning history is loaded or a storyboard pick is being loaded. The Workbench `queryParams` subscription only sets `loadedTimelineId` and `activeToolButton`. It must never mirror the URL's `sessionId` into `selectedSessionId`: a chat panel created afterwards would take the session as already loaded and show an empty chat.
2. `resetConversation()` cannot reach a mounted chat's `currentSessionId`, so `isDifferentSession` also compares the shared `selectedSessionId`. That covers the header "Workbench" link re-entering the same project, and a panel opened before the entry.
3. `WorkbenchComponent`'s **constructor** resets both root services. Its effects first run in a microtask *before* `ngOnInit`, so a reset in `ngOnInit` or `ProjectStateService.init()` is too late: the previous visit's storyboard would already have fetched its timeline and reopened the chat on a stale session. Trade-off: a run left in flight across Workbench visits is resumed by `checkAndResumePolling` on load, not through `interruptedSessionId`.
4. The timeline effect drops superseded responses (`requestSeq !== timelineLoadSeq`) in both `next` and `error`. Applying one could show, and autosave, the previous project's timeline in the project just entered.
5. When the URL names a `timelineId`, the chat's project/workspace-change reset leaves the editor alone (`resetConversationState({keepTimeline})`). The Workbench, subscribed first, has already pointed `loadedTimelineId` at that timeline for the same emission; clearing it left every manual-timeline project empty.
6. The chat tears down its URL listener and its `generateVideoRequest$` subscription in `ngOnDestroy`. It is destroyed whenever its panel closes, and leftover listeners would reset the shared state on every switch and re-send video requests. `loadChatSessions()` replaces its listener and forgets `lastGatedParams`, so a restart reloads.
7. The timeline effect skips only a reload of the timeline being saved (`savingTimelineId`). Skipping every load while `isSaving` left the editor bound to a timeline it never loaded, and the next autosave overwrote that timeline.

The chat spec's `getActiveWorkspaceId` mock returns `null` on its first call, which hides this class of bug. Specs for it set the workspace explicitly.

### Autosave across project switches

- A save that lands after a switch (`projectAtSave`) touches neither `loadedTimelineId` nor the URL.
- The debounced autosave is skipped once the flush has cleared `hasPendingSave`. Otherwise it would save the still-empty timeline of the project just entered.
- Edits queued in a project that is no longer active (`pendingSaveIsStale()`) are neither autosaved nor flushed. That covers a project left through a deep link, and a deleted project, which `deleteProject` leaves via `enter(next, {flush: false})`.
- The debounced autosave subscribes with an empty `error` callback. When a save fails, `saveTimeline()` logs it, shows `Failed to save changes`, then errors its Subject. Without a callback, RxJS rethrew that error from a timer, and Angular's `ErrorHandler` logged it a second time.

### Project switcher (`app-project-switcher`, standalone)

- The rows are `mat-menu-item`s, for keyboard support: arrow keys, Home/End, typeahead, initial focus. The SCSS undoes Material's item look: state-layer tokens, the 48px min-height, label typography, icon colours, and the global `styles.scss` menu-icon margins. Compare computed styles before and after touching it.
- Leaving an inline editor puts the focus back on the item that opened it (`afterNextRender`).
- Saving a rename whose trimmed name is unchanged just closes the editor, without a `PATCH` (it would only bump `updated_at`). The check comes before `saving` is set: returning after it would leave the flag on, and lock every later rename and create.
- The trigger's `aria-label` starts with the visible project name (WCAG 2.5.3).
- The default project has no Delete, and a refused delete shows the backend `detail`.
- Keystrokes in the inline inputs never reach `mat-menu`: its typeahead would steal the focus, and Escape would close the menu.
- The component must not import `MatDialogModule`. That module re-provides `MatDialog` in the standalone component's injector, shadowing the root service and any test double (`MatDialog` is `providedIn: 'root'`).

## Specs that pin these rules

- **Backend:**
  - `tests/agents/test_agent_service_registry.py`: adoption, activity seeding, expired chats (`TestExpiredSessions`), restores (`TestRestoreSession`, `test_a_restored_chat_is_never_run`), owner-only sessions, deletes;
  - `tests/agents/test_agent_session_repository.py`;
  - `tests/agents/test_agent_controller.py`: `test_restore_session_route`, `test_chat_route_refuses_a_restored_chat`;
  - `tests/projects/`;
  - `tests/workbench/test_timeline_auth_guard.py`.
- **Workbench:**
  - `Entering the Workbench`;
  - `while a save is in flight`;
  - `drops an autosave queued in a project that was left`;
  - `handles a failed debounced autosave instead of rethrowing it`;
  - `never applies a superseded timeline response`;
  - `drops the in-flight timeline once a project entry reset the editor`.
- **Chat, under `Projects`:**
  - `reloads the chat when the project it shows is entered again`;
  - `loads the chat when the panel was opened before the project entry`;
  - `does not fetch a chat that is already loaded again`;
  - `keeps the timeline the URL names when a project is entered`;
  - `when the chat the URL names is gone`;
  - `expired chats` (with `with a storyboard (restorable)`, and `StudioDropdownComponent option states`);
  - `restored chats`;
  - `listener lifecycle`.

## Known limitations

- The "chat still running" 409 is per process. With several Cloud Run instances, a run on another instance goes undetected.
- Agent sessions are deleted best-effort.
- Registry rows of chats deleted outside Creative Studio are never pruned. They keep a `NULL` activity time and sort last.
- Restoring an expired chat brings back only its storyboard and timeline: its messages are lost, and Izumi cannot continue a restored chat (a new chat can). An expired chat without a storyboard cannot be restored. A chat deleted outside Creative Studio after it was listed cannot be told apart from an expired one, and shows as expired too.
