# Docs site deploy

Basecamp's documentation site is built from `mkdocs.yml` and `docs/` (both at the
repo root, owned by the content track) and served as a Podman container behind a
cloudflared tunnel at `basecamp.playground.tools`. Everything under `deploy/`
here is the deploy infrastructure; it never builds or owns docs content.

## Architecture

```
GitHub Actions (push to main: docs/**, mkdocs.yml, deploy/**)
        │  tailscale/github-action joins the runner to the tailnet
        ▼
SSH + rsync over Tailscale → sg-compute (the NixOS VPS)
        │  ships deploy/, docs/, mkdocs.yml → ~/.local/share/basecamp/
        ▼
podman build on the VPS (deploy/Dockerfile, context = remote root)
        │  mkdocs-material build --strict  →  nginx:alpine image basecamp-docs:latest
        ▼
systemctl --user restart basecamp-docs.service  (Podman -p 18001:80)
        ▼
cloudflared tunnel ingress → basecamp.playground.tools
```

The build context is the remote root (`~/.local/share/basecamp`, the parent of
`deploy/`) because `mkdocs.yml` and `docs/` are shipped there alongside `deploy/`.
`deploy/Dockerfile` therefore `COPY`s `mkdocs.yml` and `docs/` from the context
root, and `deploy/deploy.sh` builds with `BUILD_CONTEXT="$SCRIPT_DIR/.."`.

## Pieces

| File | Role |
|------|------|
| `Dockerfile` | Multi-stage: `mkdocs build --strict` → `nginx:alpine` serving `/docs/site`. |
| `basecamp-docs.service` | `systemd --user` unit running the Podman container on `18001:80`. |
| `deploy.sh` | VPS-side: builds the image, installs/enables/restarts the unit, verifies active. |
| `docs-deploy-service.sh` | GitHub Actions side: SSH over Tailscale, rsyncs `deploy/` + `docs/` + `mkdocs.yml`, runs remote `deploy.sh`. |

This mirrors the deploy conventions from the sibling infra repo `nest`:
`services/test-server/*` (Podman `systemd --user` unit + `deploy.sh`) and
`.github/scripts/deploy-service.sh` (SSH/rsync helper). Differences are scoped to
basecamp's layout: the service ships from `deploy/` (not `services/<name>/`) and
carries `docs/` + `mkdocs.yml` to the same remote root.

## Manual prerequisites

These are one-time, user-performed steps outside this repo. None of them are
automated by the workflow.

### GitHub repository secrets (basecamp repo)

- `TS_OAUTH_CLIENT_ID`
- `TS_OAUTH_SECRET`
- `SSH_HOST`
- `SSH_USER`
- `SSH_PRIVATE_KEY` — unencrypted private key for `SSH_USER` on sg-compute.

### VPS (sg-compute) prerequisites

- `loginctl enable-linger <SSH_USER>` so the `systemd --user` service survives
  logout (nest services depend on the same).
- Podman available on `~/.nix-profile/bin/podman` (provided by the nest Nix
  Home Manager setup for sg-compute).
- **Port 18001 must be free** before the first deploy. `18000` and `9090` are
  already taken by `brian.har.gg` and `test.playground.tools`; `18001` is the
  chosen port for this site. Verify with, e.g. `ss -ltnp | grep 18001`.

### Cloudflare tunnel DNS

CNAME `basecamp.playground.tools` → `613f6df4-92e4-402e-b6d1-9d13ec1f203f.cfargotunnel.com`.

Either add the CNAME in the Cloudflare dashboard, or run on a host with
`cloudflared` authenticated:

```bash
cloudflared tunnel route dns 613f6df4-92e4-402e-b6d1-9d13ec1f203f basecamp.playground.tools
```

### Nest cross-repo change (separate PR in `~/GitHub/nest`)

Add an ingress rule to `services/cloudflared/config.yml` **before** the catch-all
`- service: http_status:404`:

```yaml
  - hostname: basecamp.playground.tools
    service: http://localhost:18001
```

That PR's workflow will restart cloudflared on the VPS, picking up the new route.
