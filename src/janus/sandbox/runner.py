from __future__ import annotations

import asyncio
import logging
import shlex
import uuid

import docker

logger = logging.getLogger(__name__)

IMAGE = "python:3.12"
WORKDIR = "/work"
REPO_DIR = f"{WORKDIR}/repo"
DEFAULT_TIMEOUT = 300


def _sync_exec(container, cmd: str, workdir: str) -> tuple[int, str]:
    result = container.exec_run(cmd, workdir=workdir, demux=False)
    return result.exit_code, (result.output or b"").decode(errors="replace")


class SandboxJob:
    def __init__(self, repo: str, token: str, base_branch: str):
        self.job_id = uuid.uuid4().hex[:12]
        self.repo = repo
        self.token = token
        self.base_branch = base_branch
        self._container = None

    async def __aenter__(self) -> SandboxJob:
        client = await asyncio.to_thread(docker.from_env)
        self._container = await asyncio.to_thread(
            lambda: client.containers.run(
                IMAGE,
                command="sleep infinity",
                detach=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                mem_limit="1g",
                name=f"janus-{self.job_id}",
                working_dir=WORKDIR,
            )
        )
        clone_url = f"https://x-access-token:{self.token}@github.com/{self.repo}.git"
        setup = (
            f"sh -c 'git clone --depth 50 --branch {shlex.quote(self.base_branch)}"
            f" {shlex.quote(clone_url)} {REPO_DIR}"
            f" && cd {REPO_DIR}"
            " && git config user.name janus"
            " && git config user.email janus@users.noreply.github.com'"
        )
        code, out = await self.run(setup, timeout=600, workdir=WORKDIR)
        if code != 0:
            raise RuntimeError(f"sandbox clone failed: {out[-2000:]}")
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._container is not None:
            await asyncio.to_thread(self._container.remove, force=True)

    async def run(
        self, cmd: str, timeout: int = DEFAULT_TIMEOUT, workdir: str = REPO_DIR
    ) -> tuple[int, str]:
        return await asyncio.wait_for(
            asyncio.to_thread(_sync_exec, self._container, cmd, workdir), timeout
        )

    async def read_file(self, path: str) -> str:
        code, out = await self.run(f"cat {shlex.quote(path)}")
        return out if code == 0 else f"(error reading {path}: {out[:200]})"

    async def write_file(self, path: str, content: str) -> str:
        quoted = shlex.quote(path)
        heredoc = (
            f"mkdir -p $(dirname {quoted}) && cat > {quoted} << 'JANUS_EOF'\n{content}\nJANUS_EOF"
        )
        code, out = await self.run(f"sh -c {shlex.quote(heredoc)}")
        return "ok" if code == 0 else f"(write failed: {out[:200]})"

    async def diff(self) -> str:
        _, tracked = await self.run("git diff")
        _, status = await self.run("git status --porcelain")
        return f"{tracked}\n\nstatus:\n{status}"

    async def changed_paths(self) -> list[str]:
        _, out = await self.run("git status --porcelain")
        return [line[3:].strip() for line in out.splitlines() if line.strip()]

    async def push_branch(self, branch: str, message: str) -> bool:
        author = "-c user.name='janus-maintainer[bot]' -c user.email='4214565+janus-maintainer[bot]@users.noreply.github.com'"
        cmd = (
            f"sh -c 'git checkout -b {shlex.quote(branch)} && git add -A"
            f" && git {author} commit -m {shlex.quote(message)}"
            f" && git push origin {shlex.quote(branch)}'"
        )
        code, out = await self.run(cmd)
        if code != 0:
            logger.error("push failed: %s", out[-1000:])
        return code == 0
