FROM ubuntu:24.04

ARG RUNNER_VERSION=2.335.1
ARG DEBIAN_FRONTEND=noninteractive

# Core dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git jq sudo \
    software-properties-common build-essential \
    libsqlite3-dev libffi-dev zlib1g-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 3.12 + 3.14 via deadsnakes PPA
RUN add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-dev python3.12-venv \
    python3.14 python3.14-dev python3.14-venv \
    && rm -rf /var/lib/apt/lists/*

# Ensure pip is available inside venvs (ensurepip)
RUN python3.12 -m ensurepip --upgrade \
    && python3.14 -m ensurepip --upgrade \
    || true

# Create runner user (non-root)
RUN useradd -m -s /bin/bash runner \
    && echo "runner ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Install GitHub Actions runner
WORKDIR /home/runner/actions-runner
RUN curl -fsSL https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz \
    | tar xz \
    && chown -R runner:runner /home/runner

# Miniforge (provides mamba) for the ephemeral-conda CI workflow (ci.yml).
# Installed at /home/runner/miniforge3 so $HOME/miniforge3/condabin/mamba
# resolves for the non-root 'runner' user — matches ci.yml's search path.
RUN curl -fsSL "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh" -o /tmp/miniforge.sh \
    && bash /tmp/miniforge.sh -b -p /home/runner/miniforge3 \
    && rm -f /tmp/miniforge.sh \
    && chown -R runner:runner /home/runner/miniforge3 \
    && /home/runner/miniforge3/condabin/mamba --version

# Entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER runner
ENTRYPOINT ["/entrypoint.sh"]
