"""Resume the official Tencent GGUF through ModelScope byte ranges."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
import time
from urllib.request import Request, urlopen

from .paths import DOWNLOADS, MODELS, configure_paths

NAME = "HY-MT1.5-1.8B-Q8_0.gguf"
SIZE = 1_908_528_288
SHA256 = "6789b06d0902f2f5312c0e1703d56ccbddfcfb6c653d22519b7c720f7db9a98e"
URL = f"https://modelscope.cn/models/Tencent-Hunyuan/HY-MT1.5-1.8B-GGUF/resolve/master/{NAME}"


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_part(start: int, end: int, path: Path) -> Path:
    expected = end - start + 1
    existing = path.stat().st_size if path.is_file() else 0
    if existing > expected:
        path.unlink()
        existing = 0
    failures = 0
    while existing < expected:
        first = start + existing
        last = min(end, first + 4 * 1024 * 1024 - 1)
        print(f"Downloading model bytes {first:,}–{last:,} to {path}", flush=True)
        try:
            request = Request(URL, headers={"Range": f"bytes={first}-{last}"})
            with urlopen(request, timeout=45) as response:
                content_range = response.headers.get("Content-Range", "")
                if response.status != 206 or not content_range.startswith(f"bytes {first}-{last}/"):
                    raise RuntimeError(f"Server returned the wrong byte range: {content_range}")
                remaining = last - first + 1
                with path.open("ab") as output:
                    while remaining:
                        block = response.read(min(1024 * 1024, remaining))
                        if not block:
                            raise RuntimeError(f"Incomplete model range: {first}-{last}")
                        output.write(block)
                        remaining -= len(block)
        except Exception as exc:
            updated = path.stat().st_size if path.exists() else 0
            failures = failures + 1 if updated == existing else 0
            existing = updated
            if failures >= 5:
                raise RuntimeError(f"Model range failed repeatedly: {first}-{last}") from exc
            time.sleep(min(5, failures + 1))
            continue
        existing = path.stat().st_size
        failures = 0
    print(f"Downloaded {path.name}", flush=True)
    return path

def main() -> None:
    configure_paths()
    model_dir = MODELS / "hy-mt"
    model_dir.mkdir(parents=True, exist_ok=True)
    destination = model_dir / NAME
    marker = destination.with_suffix(".verified")
    if destination.is_file() and destination.stat().st_size == SIZE:
        if _hash(destination) != SHA256:
            marker.unlink(missing_ok=True)
            raise RuntimeError("The existing HY-MT GGUF checksum is incorrect.")
        marker.write_text(SHA256, encoding="ascii")
        print(f"Model already verified: {destination}")
        return

    marker.unlink(missing_ok=True)
    prefix = destination.stat().st_size if destination.exists() else 0
    if prefix > SIZE:
        raise RuntimeError("The existing HY-MT GGUF is larger than expected.")
    parts_dir = DOWNLOADS / "hy_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    segments_dir = parts_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    chunk_size = (SIZE - prefix + 7) // 8
    ranges = []
    for start in range(prefix, SIZE, chunk_size):
        end = min(SIZE - 1, start + chunk_size - 1)
        ranges.append((start, end, parts_dir / f"{start}-{end}.part"))

    pending = []
    segments_by_part = []
    for start, end, part in ranges:
        have = part.stat().st_size if part.exists() else 0
        if have > end - start + 1:
            part.unlink()
            have = 0
        missing = end - start + 1 - have
        segments = []
        if missing:
            segment_size = (missing + 7) // 8
            for first in range(start + have, end + 1, segment_size):
                last = min(end, first + segment_size - 1)
                segment = (first, last, segments_dir / f"{first}-{last}.part")
                pending.append(segment)
                segments.append(segment)
        segments_by_part.append((part, end - start + 1, segments))

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_download_part, *item) for item in pending]
        for future in as_completed(futures):
            future.result()

    for part, expected, segments in segments_by_part:
        with part.open("ab") as output:
            for _first, _last, segment in segments:
                with segment.open("rb") as source:
                    for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
                        output.write(block)
        if part.stat().st_size != expected:
            raise RuntimeError(f"Wrong assembled model part size: {part.name}")

    with destination.open("ab") as output:
        for _start, _end, part in ranges:
            with part.open("rb") as source:
                for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
                    output.write(block)
    if destination.stat().st_size != SIZE or _hash(destination) != SHA256:
        raise RuntimeError("HY-MT GGUF checksum verification failed.")
    marker.write_text(SHA256, encoding="ascii")
    cleanup = {part for _start, _end, part in ranges}
    cleanup.update(segment for _first, _last, segment in pending)
    for path in cleanup:
        path.unlink(missing_ok=True)
    print(f"Verified model: {destination}")


if __name__ == "__main__":
    main()
