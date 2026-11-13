# Helm — IXON SecureEdge Pro Deployment

## Prerequisites

- Docker with buildx plugin installed
- IXON SecureEdge Pro reachable at `192.168.140.1` (default gateway)
- Docker daemon configured to allow insecure registry at `192.168.140.1:5000`

### Configure insecure registry (Windows)

In Docker Desktop → Settings → Docker Engine, add:

```json
{
  "insecure-registries": ["192.168.140.1:5000"]
}
```

Restart Docker Desktop after saving.

---

## Build & Push (cross-compile ARM64)

### Windows

```cmd
build_and_push_edge.cmd
```

### Linux / macOS / WSL

```bash
chmod +x build_and_push_edge.sh
./build_and_push_edge.sh
```

Custom edge IP:

```bash
EDGE_IP=192.168.1.50 ./build_and_push_edge.sh
```

### Image name per version

Every build is pushed under its own image name, `helm_v<number of commits>`, e.g. `helm_v31`. The SecureEdge Pro does not pick up a new build pushed under the same name and tag, so the name changes with every version. The script prints the exact image to use when it is done:

```
[Build] Fertig. Im IXON-Portal einen Container mit diesem Image anlegen:
    192.168.140.1:5000/helm_v31:latest
```

With uncommitted local changes the name gets a `-dirty` suffix and the script warns; commit first for a proper version. `IMAGE_NAME=… ./build_and_push_edge.sh` overrides the name.

---

## Container Setup on IXON

In the IXON Cloud portal, create a new container on the SecureEdge Pro:

| Field | Value |
|---|---|
| Image | `192.168.140.1:5000/helm_v<N>:latest` (as printed by the build script) |
| Restart policy | `unless-stopped` |
| Port | `8080:8080` |
| Volume | `helm-data` → `/data` |

> **Important:** Use named volumes only — bind mounts are not supported on IXON.

### Environment variables

| Variable | Description | Default |
|---|---|---|
| `APP_PORT` | HTTP port inside container | `8080` |
| `APP_CONFIG` | Path to config file | `/data/config.yaml` |
| `SMTP_PASSWORD` | SMTP password (if email alerts enabled) | *(empty)* |

> Older setups that already use a `helm-config` volume on `/config` together with `APP_CONFIG=/config/config.yaml` keep working; keep both settings when you recreate the container.

---

## Updating to a new version

1. Run the build script; note the new image name it prints (e.g. `helm_v32`).
2. **Only when updating from a version before November 2026:** the report templates were stored inside the container. Without shell access they cannot be copied out; note them and create them again under **Settings → Report Templates** after the update (see README, "Update (Docker)").
3. In the IXON portal create a new container from the new image with the **same volume(s)** and port as the old one. Stop and delete the old container first if the port or name is taken.
4. Delete the old container and its image to free space on the gateway; every version is a separate image.

Issues, documents, database, dashboard and settings live on the `/data` volume and carry over.

---

## First-run config

On first start the app writes a default `config.yaml` to `/data/config.yaml` (on the volume).
Connect to the container console or use IXON's terminal to edit it:

```yaml
issues_dir: /data/issues
docs_dir: /data/docs
db_path: /data/Helm.db
dashboard_file: /data/dashboard.yaml
report_templates_file: /data/report_templates.yaml
host: 0.0.0.0
port: 8080

smtp:
  enabled: false
  host: mail.gmx.net
  port: 587
  tls: true
  username: user@example.com
  password: ""          # or set via SMTP_PASSWORD env var
  from_address: user@example.com
  to_addresses:
    - recipient@example.com
```

---

## Troubleshooting

**Build fails (qemu / ARM64)**
```bash
docker run --privileged --rm tonistiigi/binfmt --install all
```

**Cannot push to registry**
- Verify insecure-registries is configured and Docker was restarted
- Ping `192.168.140.1` from the build machine

**Container exits immediately**
- Check logs in IXON portal → Container → Logs
- Ensure `/data/config.yaml` exists (auto-created on first run)

**Port conflict**
- Change the host port mapping, e.g. `8090:8080`

