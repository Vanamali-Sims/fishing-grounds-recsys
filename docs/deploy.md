# Deploy

The serving image is one container: FastAPI plus the built Sea Anchor UI. Gold artefacts are **not** in git. At boot the process downloads a tarball from `ARTEFACT_URL` into `data/processed/` and then loads ALS.

This file is the setup. Nothing here deploys the app for you.

## Why Render, not the Student Pack clouds

As of September 2026:

- DigitalOcean’s GitHub Student Pack **$200 credit ended 31 July 2026**.
- Hugging Face **Docker Spaces need a paid plan**.
- Fly.io has **no free compute** for new accounts.

The remaining $0 path that runs this Dockerfile is **Render’s free web service**: 512 MB RAM, sleeps after ~15 minutes idle, ~1 minute cold start, 750 instance hours/month, no credit card. That is the target this repo is wired for.

Student Pack still helps around the edges:

| Benefit | Use here |
| --- | --- |
| GitHub Actions minutes | `.github/workflows/ci.yml` |
| Private repo | Host the artefact tarball as a Release; set `GITHUB_TOKEN` |
| Namecheap / .me / .tech domain | Custom domain on the Render service |
| Azure for Students ($100, separate programme) | Fallback if the free instance OOMs — Container Apps, 1 GB |

## Pack gold files

From the repo root, after the pipeline has written artefacts:

```bash
python scripts/pack_serve_artefacts.py
```

Writes `data/processed/serve_artefacts.tgz`. `cells.parquet` inside the archive is slimed to the ALS catalog plus WDPA-flagged cells so the file stays small.

Upload that tarball somewhere HTTPS:

1. **GitHub Release** on this repo (private is fine). Copy the asset URL.
2. Any object store with a stable URL.

Do not commit the tarball.

## Environment

| Name | Required | Purpose |
| --- | --- | --- |
| `ARTEFACT_URL` | yes for live ALS | HTTPS URL of `serve_artefacts.tgz` |
| `GITHUB_TOKEN` | if the URL is a private GitHub asset | `Bearer` download |
| `PORT` | set by Render | uvicorn bind |

Without `ARTEFACT_URL` the API still boots on C1 stubs. The map will show five fake vessels.

## Render (do this yourself when you want it live)

1. Push the branch that contains the Dockerfile (not done in this session).
2. [dashboard.render.com](https://dashboard.render.com) → New → Blueprint, or New Web Service → this repo → **Docker**.
3. Instance: **Free**. Health check: `/health`.
4. Set `ARTEFACT_URL` (and `GITHUB_TOKEN` if needed).
5. Deploy. First boot downloads the tarball, then warms the store. `/health` returns `{"ok": true, "live": true}` when gold loaded.

`render.yaml` is a blueprint you can apply later. `sync: false` env vars must be typed in the dashboard.

Cold start: first visitor after sleep waits for download + numpy load. After that, same-origin `/vessels`, `/forecast`, and the UI are one origin (`VITE_API_BASE=""` at image build).

## Local image check (optional, not a deploy)

```bash
docker build -t sea-anchor .
docker run --rm -p 8000:8000 -e ARTEFACT_URL=https://… sea-anchor
```

Or mount local gold and skip the URL:

```bash
docker run --rm -p 8000:8000 -v %cd%/data/processed:/app/data/processed sea-anchor
```

## If 512 MB is not enough

1. Confirm the tarball used slimed cells (`python scripts/pack_serve_artefacts.py`).
2. Move to Azure Container Apps on the student $100 credit, same Dockerfile, 1 GB.
3. Render Starter ($7/mo) if you want it always-on without Azure.

Do not put GFW gold in a public bucket if you can avoid it. The source data is CC BY-NC 4.0; a private Release plus a token is enough.
