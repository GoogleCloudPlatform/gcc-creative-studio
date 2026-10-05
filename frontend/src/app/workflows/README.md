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

1. **Build:** Add steps (`user_input`, `generate_text`, `image`, `crop_image`, `generate_video`, `generate_audio`) and link their inputs/outputs in the **Workflow Editor**.
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

