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

---

## Container Setup on IXON

In the IXON Cloud portal, create a new container on the SecureEdge Pro:

| Field | Value |
|---|---|
| Image | `192.168.140.1:5000/helm:latest` |
| Restart policy | `unless-stopped` |
| Port | `8080:8080` |
| Volume 1 | `helm-config` → `/config` |
| Volume 2 | `helm-data` → `/data` |

> **Important:** Use named volumes only — bind mounts are not supported on IXON.

### Environment variables

| Variable | Description | Default |
|---|---|---|
| `APP_PORT` | HTTP port inside container | `8080` |
| `APP_CONFIG` | Path to config file | `/config/config.yaml` |
| `SMTP_PASSWORD` | SMTP password (if email alerts enabled) | *(empty)* |

---

## First-run config

On first start the app writes a default `config.yaml` to `/config/config.yaml`.
Connect to the container console or use IXON's terminal to edit it:

```yaml
issues_dir: /data/issues
docs_dir: /data/docs
db_path: /data/Helm.db
dashboard_file: /data/dashboard.yaml
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
- Ensure `/config/config.yaml` exists (auto-created on first run)

**Port conflict**
- Change the host port mapping, e.g. `8090:8080`

