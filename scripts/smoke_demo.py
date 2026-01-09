from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def fetch(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read()


def wait_for(url: str, timeout: int) -> bytes:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            status, body = fetch(url)
            if status == 200:
                return body
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test for make demo.")
    parser.add_argument("--catalog", default="http://localhost:8080")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    catalog_base = args.catalog.rstrip("/")

    wait_for(f"{catalog_base}/catalog", args.timeout)
    index_body = wait_for(f"{catalog_base}/api/index", args.timeout)
    index = json.loads(index_body.decode("utf-8"))
    items = index.get("items", [])
    if not items:
        raise RuntimeError("Catalog index has no items")

    scene_id = items[0].get("scene_id")
    if not scene_id:
        raise RuntimeError("Catalog item missing scene_id")

    scene_body = wait_for(f"{catalog_base}/api/scenes/{scene_id}", args.timeout)
    scene = json.loads(scene_body.decode("utf-8"))
    if scene.get("elements") is None:
        raise RuntimeError("Scene payload missing elements")

    status, _ = fetch(f"{catalog_base}/excalidraw/")
    if status != 200:
        raise RuntimeError("Excalidraw proxy not reachable")

    print("Smoke test passed.")


if __name__ == "__main__":
    main()
