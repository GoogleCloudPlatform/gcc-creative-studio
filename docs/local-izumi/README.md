# Local Izumi `ads_x` agent — reference files

Upstream [genmedia-izumi-agent](https://github.com/GoogleCloudPlatform/genmedia-izumi-agent)
(`v0.2.1`) does **not** ship a `docker-compose.yml` for the `ads_x` demo. The
clone lives in the gitignored `genmedia-izumi-agent/` folder at the repo root, so
anything you add there is lost when you re-clone. This directory keeps the
tracked reference copies:

| File                 | Copy to                                                   |
| -------------------- | --------------------------------------------------------- |
| `docker-compose.yml` | `genmedia-izumi-agent/demos/backend/ads_x/docker-compose.yml` |
| `.env.example`       | `genmedia-izumi-agent/demos/backend/ads_x/.env.example`   |

```bash
# From the repo root, after cloning Izumi
cp docs/local-izumi/docker-compose.yml docs/local-izumi/.env.example genmedia-izumi-agent/demos/backend/ads_x/
cd genmedia-izumi-agent/demos/backend/ads_x
cp .env.example .env            # set GOOGLE_CLOUD_PROJECT (+ ASSET_SERVICE_GCS_BUCKET)
docker compose up --build
```

See [DEVELOPMENT.md → Running the Izumi Agent locally](../../DEVELOPMENT.md#-running-the-izumi-agent-locally-workbench-chat)
for the full walkthrough, including the plain `docker build` / `docker run`
fallback when Docker Compose is not available.

> [!NOTE]
> If you change the compose file inside `genmedia-izumi-agent/`, copy it back
> here so the change is reviewed and versioned with Creative Studio.
