from __future__ import annotations

import base64
import re
from typing import Any

import httpx

from janus.autonomy.gates import DiffSummary
from janus.github.auth import API, installation_token

IMAGE_URL_RE = re.compile(
    r"!\[[^\]]*\]\((https://[^)\s]+)\)|<img[^>]+src=[\"'](https://[^\"']+)[\"']"
)


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"github {status}: {message}")


class GitHubClient:
    def __init__(self, installation_id: int):
        self.installation_id = installation_id
        self._http = httpx.AsyncClient(base_url=API, timeout=30)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        token = await installation_token(self.installation_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            **kwargs.pop("headers", {}),
        }
        resp = await self._http.request(method, path, headers=headers, **kwargs)
        if resp.status_code == 403 and resp.headers.get("Retry-After"):
            import asyncio

            await asyncio.sleep(int(resp.headers["Retry-After"]))
            resp = await self._http.request(method, path, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise GitHubError(resp.status_code, resp.text[:500])
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    async def close(self) -> None:
        await self._http.aclose()

    async def get_file(self, repo: str, path: str, ref: str | None = None) -> str | None:
        params = {"ref": ref} if ref else {}
        try:
            data = await self._request("GET", f"/repos/{repo}/contents/{path}", params=params)
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise
        if isinstance(data, dict) and data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode()
        return None

    async def get_tree(self, repo: str, ref: str = "HEAD") -> list[str]:
        data = await self._request(
            "GET", f"/repos/{repo}/git/trees/{ref}", params={"recursive": "1"}
        )
        return [item["path"] for item in data.get("tree", []) if item["type"] == "blob"]

    async def get_repo(self, repo: str) -> dict[str, Any]:
        return await self._request("GET", f"/repos/{repo}")

    async def get_issue(self, repo: str, number: int) -> dict[str, Any]:
        return await self._request("GET", f"/repos/{repo}/issues/{number}")

    async def list_open_issues(self, repo: str, limit: int = 30) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", f"/repos/{repo}/issues", params={"state": "open", "per_page": limit}
        )
        return [i for i in data if "pull_request" not in i]

    async def get_labels(self, repo: str) -> list[str]:
        data = await self._request("GET", f"/repos/{repo}/labels", params={"per_page": 100})
        return [label["name"] for label in data]

    async def add_labels(self, repo: str, number: int, labels: list[str]) -> None:
        await self._request(
            "POST", f"/repos/{repo}/issues/{number}/labels", json={"labels": labels}
        )

    async def create_comment(self, repo: str, number: int, body: str) -> None:
        await self._request("POST", f"/repos/{repo}/issues/{number}/comments", json={"body": body})

    async def close_issue(self, repo: str, number: int, reason: str = "not_planned") -> None:
        await self._request(
            "PATCH",
            f"/repos/{repo}/issues/{number}",
            json={"state": "closed", "state_reason": reason},
        )

    async def get_pr(self, repo: str, number: int) -> dict[str, Any]:
        return await self._request("GET", f"/repos/{repo}/pulls/{number}")

    async def get_pr_diff_summary(self, repo: str, number: int) -> DiffSummary:
        files = await self._request(
            "GET", f"/repos/{repo}/pulls/{number}/files", params={"per_page": 100}
        )
        return DiffSummary(
            paths=[f["filename"] for f in files],
            additions=sum(f["additions"] for f in files),
            deletions=sum(f["deletions"] for f in files),
            files=len(files),
        )

    async def get_pr_diff_text(self, repo: str, number: int, max_chars: int = 40_000) -> str:
        files = await self._request(
            "GET", f"/repos/{repo}/pulls/{number}/files", params={"per_page": 100}
        )
        chunks = [f"--- {f['filename']}\n{f.get('patch', '(binary)')}" for f in files]
        return "\n\n".join(chunks)[:max_chars]

    async def create_review(self, repo: str, number: int, event: str, body: str) -> None:
        await self._request(
            "POST", f"/repos/{repo}/pulls/{number}/reviews", json={"event": event, "body": body}
        )

    async def close_pr(self, repo: str, number: int) -> None:
        await self._request("PATCH", f"/repos/{repo}/pulls/{number}", json={"state": "closed"})

    async def merge_pr(self, repo: str, number: int, method: str = "squash") -> None:
        await self._request(
            "PUT", f"/repos/{repo}/pulls/{number}/merge", json={"merge_method": method}
        )

    async def create_pr(
        self, repo: str, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/repos/{repo}/pulls",
            json={"head": head, "base": base, "title": title, "body": body},
        )

    async def get_check_status(self, repo: str, sha: str) -> bool:
        data = await self._request(
            "GET", f"/repos/{repo}/commits/{sha}/check-runs", params={"per_page": 100}
        )
        runs = data.get("check_runs", [])
        if not runs:
            return False
        return all(
            run["status"] == "completed"
            and run["conclusion"] in ("success", "neutral", "skipped")
            for run in runs
        )

    async def get_default_branch(self, repo: str) -> str:
        return (await self.get_repo(repo))["default_branch"]

    async def get_branch_sha(self, repo: str, branch: str) -> str:
        data = await self._request("GET", f"/repos/{repo}/git/ref/heads/{branch}")
        return data["object"]["sha"]

    async def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        await self._request(
            "POST", f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": from_sha}
        )

    async def commit_file(
        self, repo: str, branch: str, path: str, content: str, message: str
    ) -> None:
        existing_sha = None
        try:
            data = await self._request(
                "GET", f"/repos/{repo}/contents/{path}", params={"ref": branch}
            )
            existing_sha = data.get("sha")
        except GitHubError as exc:
            if exc.status != 404:
                raise
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if existing_sha:
            body["sha"] = existing_sha
        await self._request("PUT", f"/repos/{repo}/contents/{path}", json=body)

    async def download_attachment(self, url: str) -> bytes:
        token = await installation_token(self.installation_id)
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            return resp.content


def extract_image_urls(body: str | None) -> list[str]:
    if not body:
        return []
    return [a or b for a, b in IMAGE_URL_RE.findall(body)]
