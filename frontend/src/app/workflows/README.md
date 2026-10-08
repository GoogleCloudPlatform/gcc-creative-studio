# ⚡ Workflows Module

Welcome to the **Workflows** module! A workflow lets you chain multiple AI generation steps together into a reusable, automated pipeline.

---

## 1. How a Workflow Works

A workflow is a chain of connected **Steps** (nodes). Each step can use outputs from previous steps as its inputs.

```text
[ User Input ] ──► [ Generate Text ] ──► [ Generate Image ] ──► [ Generate Video ]
  (prompt)           (script/idea)         (keyframe img)         (final video)
```

### Lifecycle of a Run
When you click **Run**, your workflow doesn't just fire blindly—it goes through a **Fair Queue**:

```text
[ QUEUED ] ──► [ RUNNING ] ──► [ COMPLETED ]
                    │
                    ├──► (Transient error) ──► [ STEP_FAILED (Auto-Retrying) ] ──┐
                    │                                                            ▼
                    └──► (Needs user fix)  ──► [ NEEDS_ATTENTION (Paused) ] ──► Resume!
```

1. **Build:** Add steps (`user_input`, `generate_text`, `image`, `crop_image`, `generate_video`, `generate_audio`, `loop`) and link their inputs/outputs in the **Workflow Editor**.
2. **Queue (`QUEUED`):** Submitted runs enter a fair round-robin queue across users so no single user hogs capacity.
3. **Execute (`RUNNING`):** Steps run in order. The UI polls run progress and updates each step's state live.
4. **Finish (`COMPLETED`):** All generated media and text outputs are saved and viewable in **Execution History**.

---

## 2. How Step Retry & Resume Works

AI generation (especially video and image) can take time or hit temporary hiccups. Workflows use a **3-Layer Safety Net** so **completed steps are never lost or re-billed**:

```text
Step 1: Text (✅ Saved) ──► Step 2: Image (✅ Saved) ──► Step 3: Video (❌ Safety Block)
                                                               │
                                                   Run pauses in NEEDS_ATTENTION
                                                               │
                                                User edits prompt & clicks "Resume"
                                                               │
Step 1: (⏭️ Skipped)    ──► Step 2: (⏭️ Skipped)     ──► Step 3: Video (🔄 Runs & ✅ Completes!)
```

### The 3 Layers
* **Layer 1 – Instant Retry (In-Process):** Quick network blips or momentary rate limits are retried automatically in a few seconds.
* **Layer 2 – Step Polling & Auto-Retry:** Long-running steps (like Veo video generation) save their in-flight `job_id`. If a step takes longer than a single HTTP window (~270s) or hits a temporary outage, the orchestrator automatically retries the step and **re-attaches to the existing `job_id`** instead of starting a new generation.
* **Layer 3 – Checkpoint & Manual Resume (`NEEDS_ATTENTION`):**
  * Every time a step finishes, its output is **checkpointed**.
  * If a step fails with something only you can fix (e.g., `SAFETY_BLOCK`, `INVALID_INPUT`, or exhausted quota/retries), the run pauses in **`NEEDS_ATTENTION`**.
  * Open the run in **Execution History**, adjust the input in the **Resume** form, and click **Resume**. Already-completed steps are skipped automatically!

---

## 3. How Batch Execution Works

Need to run the same workflow 50 times with different prompts or parameters? **Batch Execution** lets you do it in one upload via a `.csv` file.

```text
   📄 inputs.csv
┌────────────────────────┐
│ Row 1: "Red sneaker"   │ ──► Run #101 [ QUEUED ] ──► [ RUNNING ] ──► [ COMPLETED ]
│ Row 2: "Blue jacket"   │ ──► Run #102 [ QUEUED ] ──► [ RUNNING ] ──► [ COMPLETED ]
│ Row 3: "Gold watch"    │ ──► Run #103 [ QUEUED ] ──► [ NEEDS_ATTENTION ] (Resume anytime)
└────────────────────────┘
```

### Step-by-Step
1. **Prepare a CSV:** Create a `.csv` file where the column headers match your workflow's **User Input** field names (e.g., `prompt`, `brand_name` — case and spaces are normalized automatically).
2. **Upload & Preview:** Open **Execution History → Batch Execute** and select your CSV. The modal validates that all required inputs are present and previews the first 5 rows.
3. **Submit Batch:** Clicking **Run Batch** creates a separate **Workflow Run** for each row (`POST /workflows/{id}/batch-execute`).
4. **Fair Dispatch & Independent Tracking:**
   * All rows are queued at once and dispatched smoothly as capacity opens up.
   * Each row runs independently—if Row 3 hits a safety block (`NEEDS_ATTENTION`), Rows 1 and 2 still finish normally, and you can resume Row 3 on its own.

---

## 4. How Multi-User Execution Works (Round-Robin Fair Queue)

To prevent one user's huge batch from blocking everyone else, the system uses a **Global Cap** (`MAX_RUNNING_WORKFLOWS`, default `20`) paired with **Round-Robin Scheduling across users**.

```text
👤 Alice (Batch of 50):  [ A1 ] [ A2 ] [ A3 ] [ A4 ] ...
👤 Bob   (Single run):   [ B1 ]
👤 Carol (Batch of 3):   [ C1 ] [ C2 ] [ C3 ]
                            │
                            ▼  (Round-Robin Dispatcher)
🚀 Execution Slots:      [ A1 ] ──► [ B1 ] ──► [ C1 ] ──► [ A2 ] ──► [ C2 ] ──► [ A3 ] ...
```

### How It stays Fair & Fast
* **Turn-Taking Across Users:** Whenever execution slots open up, the dispatcher picks **1 oldest queued run from each waiting user in turns** (starting with the user who was dispatched least recently).
* **No Head-of-Line Blocking:** If Alice queues 50 runs and Bob submits 1 run a second later, Bob doesn't wait behind all 50 of Alice's runs—Bob gets the very next turn!
* **No Idle Capacity (No Per-User Cap):** If Alice is the *only* active user, she can use all `20` concurrent slots at once. As soon as Bob or Carol submits a run, the next freed slots automatically rotate to them.

---

## 5. How the Loop Node Works

Need to run the same steps for every image in a folder or every word in a list? The **Loop** node repeats its body once per item—inside a single run.

```text
[ Loop ] ──current_item──► [ Generate Text ] ──► [ Generate Image ]
    ▲       (1 per iteration)                            │
    └──────────────────── loop_ending ◄──────────────────┘
```

### Step-by-Step
1. **Pick a Source (`mode`):**
   * **Media Gallery Folder (`folder`):** Choose a folder and an `item_type` (`image`, `video`, `audio`). Each matching item (generated or uploaded) becomes one iteration, oldest first. The folder is required in this mode.
     * The folder select shows the current folder (full path on hover) plus a **Choose folder…** action. It opens the Media Gallery in folder mode, previewing items of the selected `item_type`. Browse to a folder and click **Use this folder** (the root "All Media" can't be selected).
   * **Text Input (`text_input`):** Provide comma-separated text (`"cat, dog, bird"`), fixed or linked from an upstream text output. Each trimmed value becomes one iteration.
2. **Wire the Body:** Connect `current_item` to the first body step. Connect the last body step's **Loop Ending** port back to the Loop's `loop_ending` input.
   * The **Loop Ending** output port only appears on steps inside a Loop body (downstream of the Loop). A step outside any body keeps showing it only while its Loop Ending is still wired, so the stale wire can be removed.
   * `current_item` is a **single value**, like the media step outputs: a generated media item ID (`101`) or an uploaded asset reference (`{"sourceAssetId": 7, "previewUrl": ""}`) in folder mode, a string in text mode. The Loop's `items` output lists them (e.g. `[101, {"sourceAssetId": 7, "previewUrl": ""}, 103]`).
   * Wired directly to an input, the body step receives the item itself (`"input_images": 101`); wired as one entry of a multi-media input list, it receives a list (`"input_images": [101]`).
3. **Run:** Items are resolved once and snapshotted, so retries/resumes always loop over the same items. Each iteration is checkpointed independently—resuming skips completed iterations.

### Rules & Limits
* **Max 100 loops (`MAX_LOOP_ITEMS`):** Extra items are dropped (not failed); the sidebar shows `"Found X items, only the first 100 will be processed"`.
* **Empty source:** 0 items → loop body is skipped, the run does **not** fail.
* **Missing folder:** In the editor, a saved folder that no longer exists (or isn't accessible) shows as `Folder #<id>` with a warning icon; the id is kept until you choose another folder. At run time it pauses the run in `NEEDS_ATTENTION`.
* **No post-loop steps & no nested loops:** The loop-ending step terminates its branch, and a Loop cannot live inside another Loop's body.

---

## 6. How Step History Works (`history`)

Every step in a run (loop or not) exposes its data through a single **`history`** array—one entry per completed iteration.

```json
{
  "step_id": "gen_image",
  "state": "STATE_IN_PROGRESS",
  "total_iterations": 3,
  "history": [
    { "step_inputs": { "input_images": [101] }, "step_outputs": { "generated_image": [501] } },
    { "step_inputs": { "input_images": [102] }, "step_outputs": { "generated_image": [502] } }
  ]
}
```

* **Single Source of Truth:** `step_inputs` / `step_outputs` live **only** inside `history[]` (no top-level fields). Regular steps have 1 entry; not-yet-completed steps have `history: []`.
* **Progress:** Loop and loop-body steps include `total_iterations`, so the UI can show `2 / 3`.
* **History Sidebar:** Clicking a step opens a sidebar. With more than 1 entry, a left column lists `Iteration 1`, `Iteration 2`, ...; the right column shows collapsible **Inputs** (collapsed) and **Outputs** (expanded).
* **Node Card Preview:** Cards only preview the **latest** entry (`history.at(-1)`), and only when none of the step's outputs are linked.

