#!/usr/bin/env bash
set -euo pipefail

if [ "$(uname -s)" != "Linux" ]; then
  echo "ERROR: Run this script inside a remote Ubuntu + NVIDIA 24GB GPU SSH session (detected: $(uname -s))." >&2
  exit 1
fi

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "ERROR: nvidia-smi not found. Ensure NVIDIA GPU drivers are installed on this Linux host." >&2
  exit 1
fi

echo "=== 1. Verifying NVIDIA GPU Hardware ==="
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

echo "=== 2. Installing Docker Engine & NVIDIA Container Toolkit (if needed) ==="
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg git openssl

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

if ! dpkg -l | grep -q nvidia-container-toolkit; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  sudo apt-get update -y
  sudo apt-get install -y nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    sudo systemctl restart docker
  elif command -v service >/dev/null 2>&1; then
    sudo service docker restart || sudo service docker start
  else
    sudo pkill -x dockerd >/dev/null 2>&1 || true
    sudo nohup dockerd >/tmp/dockerd.log 2>&1 &
  fi
  for _ in $(seq 1 30); do sudo docker info >/dev/null 2>&1 && break || sleep 1; done
fi

echo "=== 3. Cloning CineForge-Agent (v0.2.0) ==="
if [ -d "$HOME/cineforge-agent/.git" ]; then
  cd "$HOME/cineforge-agent"
  git fetch --tags --force origin
  git checkout -f v0.2.0
else
  git clone --branch v0.2.0 --depth 1 https://github.com/Duttaak555/cineforge-agent.git "$HOME/cineforge-agent"
  cd "$HOME/cineforge-agent"
fi

echo "=== 4. Generating ES256 X.509 C2PA Signing Credentials & Production .env ==="
mkdir -p certs artifacts
if [ ! -f certs/c2pa_es256.key ]; then
  openssl ecparam -name prime256v1 -genkey -noout -out certs/c2pa_es256.key
  openssl req -new -x509 -sha256 -key certs/c2pa_es256.key -out certs/c2pa_es256.pem -days 365 -subj "/CN=CineForge-Agent Reference Verification/O=CineForge/C=IN"
fi
chmod 644 certs/c2pa_es256.key certs/c2pa_es256.pem

printf "MODE=production\nOLLAMA_URL=http://ollama:11434\nCOMFYUI_URL=http://comfyui:8188\nKOKORO_URL=http://kokoro:8880\nLIPSYNC_URL=http://musetalk:8000\nC2PA_CERT_PATH=/app/certs/c2pa_es256.pem\nC2PA_KEY_PATH=/app/certs/c2pa_es256.key\n" > .env

echo "=== 5. Starting Pinned GPU Stack & Pulling qwen2.5vl:7b ==="
sudo docker compose -f docker-compose.prod.yml up -d --build
sudo docker compose -f docker-compose.prod.yml exec -T ollama ollama pull qwen2.5vl:7b

echo "=== 6. Running Strict Production Gate (cineforge-doctor --strict) ==="
sudo docker compose -f docker-compose.prod.yml exec -T cineforge-orchestrator cineforge-doctor --strict

echo "=== 7. Executing Full End-to-End Live GPU Smoke Suite ==="
sudo docker compose -f docker-compose.prod.yml exec -T -e CINEFORGE_RUN_LIVE_SMOKE=1 -e CINEFORGE_VERIFICATION_REPORT=/app/artifacts/verification-v0.2.0-ref-linux-gpu.json cineforge-orchestrator pytest -v -m live_smoke

echo "=== 8. Verification Artifact Ready ==="
ls -lh artifacts/verification-v0.2.0-ref-linux-gpu.json
cat artifacts/verification-v0.2.0-ref-linux-gpu.json
