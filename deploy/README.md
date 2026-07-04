# Deploying Janus on Alibaba Cloud ECS

1. **DNS**: point `janus.dogukanurker.com` (A record) at the ECS public IP.
2. **Provision** the ECS instance (Ubuntu 24.04) with `cloud-init.yml`, or run its commands manually.
3. **Clone & configure**:
   ```bash
   sudo mkdir -p /opt/janus && sudo chown $USER /opt/janus
   git clone https://github.com/dogukanurker/janus /opt/janus/repo
   cp /path/to/.env /opt/janus/.env
   cp /path/to/janus.private-key.pem /opt/janus/
   ```
4. **Run**:
   ```bash
   cd /opt/janus/repo
   docker compose -f deploy/docker-compose.prod.yml up -d --build
   ```
5. **Point the GitHub App** webhook URL at `https://janus.dogukanurker.com/webhook`.
6. **Smoke test**: open an issue on an installed repo, watch it get triaged; check `https://janus.dogukanurker.com/healthz` from off-network.

## Proof recording shot list (60-90s, separate from the demo video)
1. Alibaba console: ECS instance page, OSS bucket with `actions/` objects.
2. SSH: `docker compose ps` showing services up.
3. Live webhook round-trip: open issue, triage comment appears.
4. `src/janus/store/oss.py` on screen (the proof code file).
