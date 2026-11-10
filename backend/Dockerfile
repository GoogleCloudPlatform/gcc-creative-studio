# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Update package lists and install ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Bake HT-Demucs 6-stem FP16 ONNX weights outside /app so Cloud Run Jobs have
# zero cold-start download, /tmp tmpfs RAM is untouched, and local ./backend:/app
# bind mounts do not shadow the model file.
ENV AUDIO_STEM_MODEL_PATH="/opt/creative-studio-models/htdemucs_6s_fp16weights.onnx"
RUN mkdir -p /opt/creative-studio-models && \
    python -c "import shutil, urllib.request; req = urllib.request.Request('https://huggingface.co/StemSplitio/htdemucs-6s-onnx/resolve/main/htdemucs_6s_fp16weights.onnx', headers={'User-Agent': 'google-cloud-creative-studio/1.0'}); resp = urllib.request.urlopen(req, timeout=300); out = open('/opt/creative-studio-models/htdemucs_6s_fp16weights.onnx', 'wb'); shutil.copyfileobj(resp, out); out.close(); resp.close()" && \
    test "$(wc -c < /opt/creative-studio-models/htdemucs_6s_fp16weights.onnx)" -ge 1000000

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT []

# Set default environment variables
ENV ENVIRONMENT="development"
ENV FRONTEND_URL="http://localhost:4200"

EXPOSE 8080

CMD ["gunicorn", "main:app", "--workers=4", "--worker-class=uvicorn.workers.UvicornWorker", "--timeout=36000", "--bind=0.0.0.0:8080"]
