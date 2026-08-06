# Upgrading an existing deployment

Steps for updating a Creative Studio deployment that is already running, with the checks needed
to avoid losing data.

Read the **Before you start** section even if you upgrade routinely — the app applies database
migrations automatically on startup, so how far behind your database is matters more than the
size of the code change.

---

## Before you start

### 1. Find out which migrations will run

The backend calls `run_pending_migrations()` during startup, so deploying a newer image applies
**every migration you are behind on**, not only the ones belonging to this change. Some of them
are destructive.

Against your database, using the new code:

```bash
cd backend
alembic current                              # where your database is
alembic heads                                # where the new code expects it
alembic history --verbose -r current:head    # everything that would apply
```

Read that list before going further. In particular, `cb3c4680571b` runs
`op.drop_table("system_settings")`. If it appears, deploying removes that table. Decide whether
that is acceptable rather than discovering it afterwards.

If `current` already equals `heads`, no migrations will run.

### 2. Back up the database

```bash
# Portable, survives instance deletion, restorable into a scratch instance
gcloud sql export sql <INSTANCE> gs://<BUCKET>/backup-$(date +%F).sql \
  --database=creative_studio

# Or an in-place snapshot
gcloud sql backups create --instance=<INSTANCE> --description="pre-upgrade"
```

Prefer the export. Cloud Run rollback is instant and lossless, but **database rollback is not** —
Alembic downgrades are far less exercised than upgrades, and a `drop_table` downgrade recreates
the table empty.

### 3. Rehearse, if the data matters

Restore the export into a temporary instance, point a staging Cloud Run revision at it, and let
the migrations run there first. This is the only way to see the real outcome before it is real.

### 4. Note the current revisions, so you can roll back

```bash
gcloud run revisions list --service=<BACKEND_SERVICE> --region=<REGION> --limit=3
gcloud run revisions list --service=<FRONTEND_SERVICE> --region=<REGION> --limit=3
```

---

## Deploying

### If Cloud Build triggers are configured

The usual case if the environment was set up with `bootstrap.sh`. Merge and push; the triggers
build and deploy.

```bash
git fetch <remote> <branch>
git merge <remote>/<branch>
git push origin main
```

### Manually

```bash
gcloud builds submit --config backend/cloudbuild.yaml \
  --substitutions=_REGION=<REGION>,_REPO_NAME=<ARTIFACT_REPO>,_SERVICE_NAME=<BACKEND_SERVICE>

gcloud builds submit --config frontend/cloudbuild.yaml \
  --substitutions=_TARGET_PROJECT_ID=<PROJECT>,_ANGULAR_BUILD_COMMAND=<build-command>,_FIREBASE_PROJECT_ID=<FIREBASE_PROJECT>
```

Defaults for these live at the bottom of each `cloudbuild.yaml`.

### Deploy both services

Frontend-only or backend-only upgrades will leave the two out of step. A backend-only deploy in
particular can leave the old UI offering options the API now rejects.

Your `frontend/src/environments/environment.prod.ts` is gitignored, so your Firebase and backend
configuration survives the upgrade — but the frontend must still be rebuilt for client-side
changes to take effect.

---

## After deploying

1. **Watch the backend start.** Migrations run before the app serves traffic:
   ```bash
   gcloud run services logs read <BACKEND_SERVICE> --region=<REGION> --limit=50
   ```
   Look for `Migrations applied successfully` followed by `Application startup complete`.
2. **Sign in** and confirm the gallery loads with thumbnails.
3. **Generate one video** on your most-used model.
4. **Run one saved workflow**, if you use them. See the compatibility note below.

---

## Rolling back

Code rollback is immediate:

```bash
gcloud run services update-traffic <SERVICE> --region=<REGION> \
  --to-revisions=<PREVIOUS_REVISION>=100
```

If migrations ran and you need to undo them, restore the backup taken in step 2. Do not rely on
`alembic downgrade` for anything destructive.

---

## Compatibility notes for the Gemini Omni changes

### Breaking: requests that used to be accepted are now rejected

Per-model limits are enforced where previously a single set of bounds applied to every model.
These now return HTTP 400 instead of being silently coerced or ignored:

| Request | Why |
|---|---|
| Veo with `duration_seconds` of 5 or 7 | Veo offers 4, 6 and 8 only |
| Gemini Omni with an end frame | Omni cannot do first+last frame interpolation |
| Gemini Omni with a source video for extension | Omni cannot extend video |
| Gemini Omni with an audio reference | The API rejects audio input outright |
| `gemini-omni-generate-preview` as the model | Not a real model; Vertex rejects it |

**Audit saved workflows before upgrading.** The workflow executor posts to the same endpoint and
sends `end_image_asset_id` whenever the step has one, so a saved workflow pairing Omni with an end
frame will begin failing. It was producing incorrect output before — that combination is
interpolation, which Omni does not support — but it now fails visibly instead of quietly.

### No data changes

- **No new migrations.** The new `EDIT_SOURCE` asset role is stored in a JSONB column, not a
  Postgres enum type.
- **Existing media items are untouched.** Nothing rewrites rows.
- **Clips generated before the upgrade remain editable.** They lack the stored interaction steps
  that newer clips carry, so editing them falls back to sending the clip by URI. This fallback
  exists specifically so older library items keep working.
- **Cloud Storage is untouched** by a code deploy.

### Where video and image inputs belong

The reference-video slot has been removed from **Ingredients to Video**. Reference videos under
three seconds were accepted by the schema but not processed correctly, and the supported way to
combine a video with images is an edit.

To composite a character into existing footage, use **Edit Video** and attach reference images
alongside the clip. That sends text, image and video together with `task=edit`, matching Google's
Vertex sample. Role tags work here too: `<IMAGE_REF_N>` is positional and counts the reference
images in the order they were attached, so `<IMAGE_REF_0>` is the first image added. Verified
against the live API with three references, in mirrored pairs that exchange the two indices:
the composited arrangement flipped with them every time.

### End an edit prompt with "Keep everything else the same"

Edit prompts that scope the change some other way are frequently rejected with

```
400 Unable to submit request because This model does not support video extension.
```

even though the request asks for `task=edit`. The trigger is the prompt wording, not the request
shape: across 116 live calls, ref-image count, tags versus plain names and the staging described
all made no difference, while the closing sentence decided the outcome. `"Keep the room and
lighting the same."` failed 13/13 on one prompt; the same request ending `"Keep everything else
the same."` succeeded 9/10. Paraphrases are measurably weaker, so prefer that exact sentence.
Appending `"This is an edit of the provided video, not an extension. Do not add any new footage."`
also worked (3/3) where the wording has to stay.

Whether the service literally reclassifies the request as an extension is unverified - that
reading comes from the error text. What is established is that the wording controls it. The
Edit Video snackbar now suggests the working phrasing.

Anyone who previously attached a reference video in Ingredients mode will find the slot gone.
Nothing breaks; the input was not being used properly in the first place.

### Source audio is removed before an edit

Omni refuses to edit a clip carrying speech when reference images are also supplied:

```
The model is currently unable to process speech edits.
```

Every Omni clip has a native audio track, so editing one of its own outputs would fail. The
backend now strips the audio from the source clip first, uploads the silent copy alongside the
original, and sends that. **Remove audio from the source clip** in Edit Video controls this and
defaults on; turn it off to keep the original audio when editing without references.

This writes one extra object per edit under `edit_sources/` in your media bucket. They are small
— the video stream is copied rather than re-encoded — but they accumulate, so a lifecycle rule on
that prefix is worth considering.

`ffmpeg` is required and is already installed in the backend image.

### Behaviour that changes without any action

- Selecting 9:16 now produces a portrait video. It previously returned 16:9 regardless.
- Duration now reaches the model. Clips will match the requested length, where previously the
  value was discarded.
- Gemini Omni can return multiple clips per request, up to 4. **Each is a separate billed
  generation**, so a user selecting x4 spends four times as much.
- Video is delivered to Cloud Storage by URI rather than inline, removing a size ceiling that
  affected longer clips.
