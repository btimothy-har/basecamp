# syntax=docker/dockerfile:1
#
# Interactive sandbox for validating the basecamp Claude Code plugin end to end.
#
# Everything runs against the container's own $HOME, so the whole session
# lifecycle — SessionStart/SessionEnd hooks -> hub daemon -> transcript ingest —
# writes to an in-container SQLite DB at ~/.pi/basecamp/claude/daemon.db and
# never touches the host's basecamp data or Claude Code transcripts.
#
# Build from the REPO ROOT (the build context must see src/ and claude/):
#   podman build -f claude/docker/Dockerfile -t basecamp-claude-sandbox .
# Or use claude/docker/run.sh, which builds and drops you into a shell.

ARG NODE_VERSION=22
FROM node:${NODE_VERSION}-bookworm-slim

# uv (the Python toolchain + tool installer) straight from its published image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Runtime deps: git (project/worktree resolution + Claude Code itself),
# sqlite3 (the bc-inspect helper reads the daemon DB), procps/less for a usable
# interactive shell, curl/ca-certificates for TLS.
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		git \
		sqlite3 \
		curl \
		ca-certificates \
		procps \
		less \
	&& rm -rf /var/lib/apt/lists/*

# Claude Code CLI. Pin with --build-arg CLAUDE_CODE_VERSION=x.y.z; default latest.
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
	&& claude --version

# Run as the base image's built-in non-root user `node` (uid/gid 1000, home
# /home/node). Claude Code refuses bypassPermissions mode as root, and uv
# installs tools onto the user's ~/.local/bin. The user is fixed, not a build
# arg: the image reuses node rather than creating one (no useradd), so there is
# nothing to tune — hardcoding keeps every path (COPY targets, ENTRYPOINT) in
# agreement.

# basecamp source (allowlisted by .dockerignore) -> installed as a uv tool below.
# Kept UNDER $HOME (/home/node) to mirror a real checkout: `basecamp install`
# seeds a default project whose repo_root is stored $HOME-relative, so an
# install_dir outside $HOME would abort seeding. This is where a real host clones.
ENV BASECAMP_SRC=/home/node/src/basecamp
COPY --chown=node:node pyproject.toml uv.lock ${BASECAMP_SRC}/
COPY --chown=node:node src ${BASECAMP_SRC}/src
COPY --chown=node:node claude ${BASECAMP_SRC}/claude

# The plugin the sandbox validates (its root holds .claude-plugin/plugin.json).
ENV BASECAMP_PLUGIN_DIR=${BASECAMP_SRC}/claude

USER node
ENV HOME=/home/node
# uv's tool-bin dir first, so the plugin shims (basecamp-mcp / basecamp-hook)
# and the daemon (basecamp hub) all resolve the installed basecamp.
ENV PATH=/home/node/.local/bin:${PATH}

# Install basecamp: exposes `basecamp`, `basecamp-mcp`, `basecamp-hook`.
RUN uv tool install --python 3.12 "${BASECAMP_SRC}" \
	&& basecamp --help >/dev/null

# Claude Code config: seed a settings.json that bypasses permission prompts
# (throwaway sandbox, non-root) so the plugin's hooks, MCP server, and Bash run
# without interactive gating. `basecamp install` (below) leaves this key intact.
COPY --chown=node:node claude/docker/claude-settings.json /home/node/.claude/settings.json

# Wire the plugin exactly as a real host does: record this checkout as install_dir,
# then `basecamp install` drives the `claude` CLI (plugin marketplace add + plugin
# install) to register + enable the plugin, installs the home doctrine, scaffolds
# the context dir, and seeds the default config. `plugin install` writes
# ~/.claude/settings.json AND builds the ~/.claude/plugins cache the loader reads
# (settings.json alone does not load a plugin), so a bare `claude` then auto-loads
# it — no --plugin-dir. This is the authoritative check on registration.
RUN basecamp config set install_dir "${BASECAMP_SRC}" \
	&& basecamp install

# Cheap-changing scripts last, so editing them doesn't bust the uv-install layer.
# The entrypoint + inspection helper live in the user's PATH and are chmod'd as
# the unprivileged user.
COPY --chown=node:node claude/docker/entrypoint.sh /home/node/.local/bin/entrypoint.sh
COPY --chown=node:node claude/docker/bin/bc-inspect /home/node/.local/bin/bc-inspect
RUN chmod +x /home/node/.local/bin/entrypoint.sh /home/node/.local/bin/bc-inspect

# No plugin alias needed: `basecamp install` (above) enabled the plugin in
# ~/.claude/settings.json, so a bare `claude` auto-loads it.

# A realistic git repo to run sessions in (drives the transcript slug + project
# resolution); a throwaway, unrelated to the basecamp source under /opt.
RUN mkdir -p /home/node/workspace \
	&& cd /home/node/workspace \
	&& git init -q \
	&& git config user.email dev@example.com \
	&& git config user.name dev \
	&& printf '# sandbox workspace\n' > README.md \
	&& git add -A \
	&& git commit -qm init
WORKDIR /home/node/workspace

ENTRYPOINT ["/home/node/.local/bin/entrypoint.sh"]
