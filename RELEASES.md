# Creative Studio Release Notes

## v26.11.12 - Gemini 4 Argon, Workflow Input Port Unlink Menu & Test Suite Stability

### ✨ What's New

* **Gemini 4 Argon in Workflows & Media Gallery:** Added Gemini 4 Argon (gemini-4-argon) to the Workflows **Text** step (supporting multimodal text generation with up to 10 reference images while keeping **Gemini 3.8 Flash** as the default model) and added a matching model filter in the Media Gallery.
* **Workflow Input Port Unlink Menu:** Connected input ports and custom prompt variable ports in the Workflow Editor now highlight on hover or keyboard focus and open an Unlink menu on click or keyboard press (Enter / Space).
  * **Single-Wire Disconnect on Multi-Item Inputs:** Disconnects individual upstream wires on multi-item inputs (**Input Images** and Loop **Linked Items**) without clearing remaining connected wires or gallery selections.
  * **Automatic Fixed-Mode Recovery & Undo / Redo:** Removing the last wire from a single-value text input (such as **Prompt**) automatically returns the field to Fixed mode and re-enables custom **Prompt Variables**, records an undo/redo snapshot, while keeping the **Unlink** menu disabled in read-only **Run** mode.

### 🐛 Bug Fixes & Improvements

* **Automated Test Suite Stability & CI Hygiene**: Aligned backend and frontend unit tests with **Nano Banana 2 Lite** (gemini-3.1-flash-lite-image) Video-to-Image support, added foreign-key-aware user teardown in end-to-end workspace boundary tests, skipped cross-directory frontend config checks when running inside standalone backend containers, and isolated Angular TestBed injector state across component specs.

## v26.11.10 - Izumi Marketing Agent, Gemini Omni 1.2 Flash & Workflows Overhaul

### 🚀 Overview

Welcome to our biggest Creative Studio release yet! This update brings end-to-end agentic campaign creation into production with the **Izumi Marketing Agent** and an upgraded **Workbench**, makes **Gemini Omni 1.2 Flash** the default video model with extended 15-second durations and multi-reference video editing, and delivers a comprehensive **Workflows Studio Overhaul** alongside **Drive-Style Folders** in the Media Gallery.

* **⚠️ Important Deployment & Migration Note (Breaking Change for Self-Hosted Forks):** This release introduces new database schemas, predefined workflow templates, and Secret Manager configurations (supporting Folders, Workflows, and Izumi). If you maintain a self-hosted fork and sync with main, **you must re-run the infrastructure and database migration (`bootstrap.sh`)** rather than only rebuilding the container—otherwise existing media in your GCS bucket and predefined workflow templates will not appear in the UI until the database migration completes.

### ✨ What's New

* **Izumi Marketing Agent & Workbench Upgrades:** Our end-to-end marketing agent is now live in Creative Studio to take you from an initial campaign brief to a finished multi-scene video ad! Open **Workbench** and click the **Star (✨) icon** in the toolbar to launch Izumi.
  * **Human-in-the-Loop (HITL) Approval Gates:** Interactive checkpoints across all 4 pipeline stages (*Strategy*, *Storyboard*, *Asset Generation*, and *Final Cut*) let you accept, modify, or regenerate deliverables at every step, complete with unified stage milestone cards and persistent chat history.
  * **Campaign Brief & Character Casting:** Added a collapsible **Campaign Brief** tab with progressive disclosure and storyline guidance, alongside a **Character Profile** panel that lets you define and persist character demographics (age, gender, personality, wardrobe) across storyboard prompts.
  * **Storyboard Reference Assets & Timeline Audio Controls:** Added a dedicated Reference Assets section with automated preview resolution, `scene_id` prompt persistence, and FFmpeg-backed **audio gain, volume normalization, and fade-in/fade-out controls** directly on the Workbench multi-track timeline.
  * **Local Izumi Development:** Added Docker Compose (LocalAdkClient) support so engineering teams can run and debug the Izumi agent locally alongside Vertex AI Agent Engine deployments.
* **Gemini Omni 1.2 Flash & 1.1 Flash Video Studio:** **Gemini Omni 1.2 Flash** (`gemini-omni-1.2-flash`) is now the default video model in Creative Studio, alongside **Gemini Omni 1.1 Flash** (`gemini-omni-1.1-flash`).
  * **Extended Durations (4s–15s):** Generate **Text-to-Video** clips and start-frame **Frames-to-Video** clips up to **15 seconds** (4s, 6s, 8s, 10s, 12s, 15s) on Gemini Omni 1.2 Flash (4s–10s on Omni 1.1 Flash and when using an end frame).
  * **Expanded Multi-Modal Reference Caps (Ingredients to Video):** Attach up to **10 reference images and 3 reference videos** on Gemini Omni 1.2 Flash (and up to **5 reference images and 3 reference videos** on Omni 1.1 Flash), with automatic excess-reference trimming and toast notifications when switching models.
  * **Seamless Video Extension (Extend Video):** Both Gemini Omni 1.2 Flash and 1.1 Flash now support **Extend Video** mode (4s–10s), automatically applying a seamless continuation fallback prompt when submitted without custom text.
  * **Gallery "Edit with Omni" & "Extend" Actions:** Open any Omni-generated video in the Media Gallery and click **Edit with Omni** (preloading the clip into Ingredients-to-Video for Turn 2 conversational edits, or automatically running as a Turn 1 multi-reference job when additional assets are attached) or **Extend** while preserving the clip's Omni model.
* **Workflows Studio Overhaul:** Build, reuse, and execute multi-step creative pipelines faster with a redesigned Workflows canvas and node library.
  * **Workflow Templates Library & In-Canvas Insertion:** Browse predefined **Workflow Templates** on `/workflows` to launch a ready-made pipeline in one click, or insert a template directly into an active workflow canvas via **Templates**.
  * **Unified Image Node & 2K/4K Image Upscale Step:** Consolidated all image generation and editing into a single **Image** node supporting **Auto (Dynamic)** aspect ratio and **1K / 2K / 4K** resolution, and added a dedicated **Image Upscale** step (2K and 4K powered by **Nano Banana 2**).
  * **Text Node @Variables & Google Search Grounding:** Added dynamic @variable prompt pills linked to upstream step outputs, an updated Gemini model list, and a per-step **Google Search** grounding checkbox.
  * **Video Node Omni 1.2 / 1.1 & Extend Parity:** Upgraded the workflow **Video** node to support **Gemini Omni 1.2 Flash** and **1.1 Flash**, **Extend Video** mode, video/image reference input ports, and model-aware durations (4s–15s).
  * **Loop Node, Output Folder Selector & Step Retry:** Added a **Loop** node for batch iteration over lists, a **Media Gallery Output Folder Selector** on Image/Audio/Video nodes, collapsible node cards with persisted canvas coordinates, and an **Execution History** modal with per-step **Retry**.
* **Drive-Style Folders & Expanded Media Capabilities:**
  * **Nested Folder Hierarchy & Bulk Operations:** Organize generated and uploaded assets with nested folders, drag-and-drop support, case-sensitive folder renaming, clickable breadcrumbs, and bulk move/copy across workspaces with smart conflict resolution (*Replace*, *Keep Both*, or *Merge*). Assets generated by the Izumi Marketing Agent are automatically routed into dedicated campaign output folders.
  * **Video-to-Image, 2K/4K Images & Lyria 3 Audio:** Extract and generate high-quality still frames from video assets (including direct **YouTube URL** support), generate **2K and 4K** images with **Nano Banana 2** and **Nano Banana Pro**, select **Lyria 3** in Audio Generation, and submit product feedback anytime via the floating **In-App Feedback** button.

### 📈 Improvements

* **Infrastructure, Automated Migrations & Documentation (`bootstrap.sh`):**
  * Added automated Cloud SQL backup, export/import migration, and restore tooling (--use-existing-backup, --skip-db-import, --skip-seeding) with headless CLI flags, progress polling, and placeholder containers to prevent Cloud Run crash-loops during initial setup.
  * Added **GitLab** repository support alongside GitHub for CI/CD Cloud Build triggers, upgraded the default Cloud Run backend allocation to **2 vCPU / 8 GiB RAM**, and published a comprehensive **Deployment Guide & Infrastructure Architecture Diagram** in docs/ and `infrastructure/README.md`.
* **Security & Model Resilience:**
  * Upgraded the backend pillow dependency to `>= 13.0.0` (resolving container vulnerability scan findings) and hardened repository security and automated code review checks.
  * Updated the default Izumi video generation model to production `veo-3.1-generate-001`, standardized global `MODEL_TARGET_LOCATION` routing, and implemented automatic prompt simplification and retry logic when **Lyria 3** audio prompts encounter safety filter blocks.

### 🐛 Bug Fixes

* Fixed **Gemini Omni** vertical (9:16) video aspect ratio handling across both Video Studio and Workflow Video nodes, and enforced pre-queue duration and reference cap validation (4s–15s, up to 10 reference images and 3 reference videos).
* Fixed Workflow Editor execution and canvas bugs: prevented running unsaved workflows before initial save, rendered text inputs cleanly instead of raw JSON in execution logs, validated maximum port connections, hid unused ports on the Unified Image node, and preserved user-input port connections across page refreshes.
* Enabled **Nano Banana 2 Lite** for Video-to-Image generation.
* Fixed Workbench video track layout math to account for transition overlaps when deleting or moving clips, prevented duration estimation errors from persisting as trim durations, and resolved UI state polling loops when switching between projects and timelines.
* Fixed chat session switching race conditions with concurrency guards, resolved image attachments via presigned URLs, fixed header flyout menu flickering, and patched an XSS vulnerability in chat link rendering.

## v26.08.19 - Private IP

### ✨ What's New

* **Private IP** is now enabled in Creative Studio

## v26.06.05 - Gemini Omni

### ✨ What's New

* **Gemini Omni** is now available in Creative Studio!
  * Please note that a customer will only be able to use Gemini Omni if the following is true
    * They are in the EAP program for Gemini Omni
    * Creative Studio is deployed on the **GCP project they submitted to the EAP**
  * Because of the EAP, Gemini Omni is **off by default**, but can be toggled on in the Admin settings
* **Nano Banana 2** and **Nano Banana Pro** have been switched to the production endpoints from the preview ones

### 🐛 Bug Fixes

* Gallery filters are now preserved when navigating back from a selected image
* Fixed an issue where Virtual Try-On (VTO) generation would fail during deployment for external enterprise environments due to default organizational security constraints
* Fixed a bug where Gemini TTS was stuck on one voice, all voices should now work

## v26.04.08 - Media Gallery Update

### ✨ What's New

* **Media Gallery Update:** Based on feedback from customers we have added more features to the media gallery
  * New Look and Feel
  * Generated and uploaded content are now both available in the media gallery
  * Organized by Date
  * Added Delete functionality (finally)
  * Added multi-select so you can tag, copy, download, and delete in bulk
  * New tagging system to help organize

* **New Veo Models**
  * Veo 3.1 Lite and Veo 3.1 Fast have been added to the platform
* **Copy Functionality:**
  * You can now copy assets across the different workspaces you have access to
* **Workflows:**
  * Added a new workflows role that allows users to create and run workflows (rather than only Admins being able to run them)
* **Enhance Prompt Toggle:**
  * We no longer enhance the prompt by default, instead relying on the models built in rewriters. However, you can still toggle the enhance prompt button on if you preferred our rewriter
* **Select Media Interface**
  * New Look
  * We no longer enforce an aspect ratio on the uploaded images, however you can still choose to use this functionality by toggling “Crop before Upload”
  * Can now multi-select images before adding them
  * Can now Filter by tags and created date

### 🐛 Bug Fixes

*  Updated the Veo 3.1 model to use the production version

### 🕵️ Known Issues

* Brand Guidelines is not saving properly - we’re working on a fix, it seems to be a caching issue
  * **Workaround:** Empty the Cache and Hard Reload the page after upload completes successfully and the brand guidelines will be available
  * You need to have both “Brand Guidelines" and “Enhance Prompt” toggled for this to work - to be fixed in a future update

## v26.02.26 - Nano Banana 2

### ✨ What's New

* Nano Banana 2 has been released and integrated into the platform. Try it out now!

### 🐛 Bug Fixes

* Nano Banana Pro has been renamed to Nano Banana Pro (Preview)

## v26.02.20 - Workbench / Workflows

### 🚀 Overview

Welcome to the first major step toward Creative Studio 2.0! This release focuses on moving beyond generating isolated assets into full video assembly. We are introducing the Beta Workbench for editing, rolling out Workflows, adding the standalone Imagen 4 Upscaler, and delivering massive performance boosts to the Media Gallery.

### ✨ What's New

* **Beta Workbench:** The foundation of our production-grade video editor is here! This is a major milestone that allows you to start assembling and creating long-form video content directly in the studio. Easily add video and audio assets to your timeline, and layer multiple audio tracks to build out rich soundscapes with overlapping voiceovers and music. Once your project is complete, you can seamlessly download the finished video directly from the studio

  * **⚠️ Note:** In this beta release, your workbench progress is currently not saved if you navigate away from the page, so please complete your exports in a single session.
* **Workflows:** Introducing Workflows for the very first time! This powerful new tool lets you create custom, step-by-step production pipelines driven by user-inputted variables. You can also batch up to 20 requests at once (this limit will be increased significantly in the next release). To help you start automating your creative process right away, we are launching with the following nodes: Generate Text, Generate Image, Edit Image, Virtual Try-On, Generate Video, and Generate Audio.

  * **⚠️ Note:** You currently need Admin permissions to access this, we’re working on updating it so everyone can create workflows
* **Imagen 4 Upscaler:** Powered by a fully managed Vertex AI service, this new dedicated tool effortlessly upscales and unblurs your images. You can now rapidly create high-resolution, photorealistic visual content directly within your workspace, ensuring every asset is crisp, professional, and enterprise-ready

### 📈 Improvements

* **Media Gallery Caching & Thumbnails:** Managing hundreds of high-res assets shouldn't slow you down. By introducing lightweight thumbnails instead of directly loading full high-res media, alongside an aggressive new caching strategy, 2K and 4K images and videos now load significantly faster. This ensures a smooth, crash-free experience even on standard enterprise laptops.
* **Virtual Try-On:** Updated the VTO model to virtual-try-on-001.

### 🐛 Bug Fixes

* Updated Nano Banana (Gemini 2.5 Flash Image) to now support all aspect ratios.
