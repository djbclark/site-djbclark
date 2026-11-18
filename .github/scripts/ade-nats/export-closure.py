"""Export CI-built paths unavailable in the hub baseline or public binary cache.

The hub copies signed public-cache paths, then imports this small custom NAR.
Neither operation builds on the deployment host. Inputs contain no credentials.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request


def store_path(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"/nix/store/[a-z0-9]{32}-[^\s/]+", value
    ):
        raise ValueError("invalid store path")
    return value


def public_cache(path):
    digest = Path(path).name.split("-", 1)[0]
    url = f"https://cache.nixos.org/{digest}.narinfo"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, method="HEAD"), timeout=20
            ) as response:
                if response.status == 200:
                    return True
                raise RuntimeError("unexpected cache status")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return False
            if attempt == 2:
                raise
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)
    raise RuntimeError("cache inspection did not finish")


def main():
    target_host = os.environ.get("TARGET_HOST", "vps-hub")
    if target_host not in {"vps-hub", "vps-primary"}:
        raise ValueError("unsupported deployment host")
    head = os.environ["PUBLISHED_MASTER"]
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("published source revision required")
    source = Path(os.environ["BUILD_SOURCE"])
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != head:
        raise ValueError("build source is not requested published revision")
    baseline = json.loads(
        gzip.decompress(base64.b64decode(os.environ["BASELINE_GZIP64"], validate=True))
    )
    baseline_system = store_path(baseline["system"])
    present = {store_path(value) for value in baseline["paths"]}
    if baseline_system not in present:
        raise ValueError("baseline does not include running system")
    system = store_path(str(Path(os.environ["RUNNER_TEMP"], "hub-system").resolve()))
    if f"-nixos-system-{target_host}-" not in Path(system).name:
        raise ValueError("built system does not match deployment host")
    closure = {
        store_path(value)
        for value in subprocess.check_output(
            ["nix-store", "--query", "--requisites", system], text=True
        ).splitlines()
    }
    missing = sorted(closure - present)
    with ThreadPoolExecutor(max_workers=12) as pool:
        available = list(pool.map(public_cache, missing))
    substitutes = [path for path, cached in zip(missing, available) if cached]
    custom = [path for path, cached in zip(missing, available) if not cached]
    output = Path(os.environ["RUNNER_TEMP"], "hub-closure")
    output.mkdir()
    archive = output / "custom.nar.gz"
    exported = 0
    with gzip.open(archive, "wb", compresslevel=6) as target:
        child = subprocess.Popen(
            ["nix-store", "--export", *custom], stdout=subprocess.PIPE
        )
        try:
            while chunk := child.stdout.read(1024 * 1024):
                exported += len(chunk)
                target.write(chunk)
            if child.wait() != 0:
                raise RuntimeError("NAR export failed")
        finally:
            child.stdout.close()
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=30)
    with archive.open("rb") as content:
        checksum = hashlib.file_digest(content, "sha256").hexdigest()
    manifest = {
        "schema": 1,
        "target_host": target_host,
        "source_head": head,
        "system": system,
        "baseline_system": baseline_system,
        "closure": sorted(closure),
        "substitutes": substitutes,
        "custom": custom,
        "archive_sha256": checksum,
        "nar_bytes": exported,
        "compressed_bytes": archive.stat().st_size,
        "authority": "build provenance only; deployment still requires reviewed published head",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    print(
        json.dumps(
            {
                "source_head": head,
                "closure_paths": len(closure),
                "substitutes": len(substitutes),
                "custom_paths": len(custom),
                "compressed_bytes": archive.stat().st_size,
                "system": system,
            }
        )
    )


if __name__ == "__main__":
    main()
