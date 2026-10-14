"""Read-only access to versioned replay evidence packs."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def file_matches_sha256(path: Path, expected: str) -> bool:
    """Verify bytes while tolerating Git's LF/CRLF text checkout conversion."""

    data = path.read_bytes()
    candidates = [data]
    if path.suffix.lower() in {".csv", ".json"}:
        lf = data.replace(b"\r\n", b"\n")
        candidates.extend((lf, lf.replace(b"\n", b"\r\n")))
    return any(hashlib.sha256(item).hexdigest() == expected for item in candidates)


@dataclass(frozen=True, slots=True)
class ReplayEvidenceRepository:
    root: Path

    def stock_folder(self, stock_code: str) -> Path:
        if len(stock_code) != 6 or not stock_code.isdigit():
            raise ValueError("stock_code must contain exactly six digits")
        folder = self.root if stock_code == "601318" else self.root / stock_code
        if not (folder / "manifest.json").is_file():
            raise FileNotFoundError(f"evidence snapshot not found: {stock_code}")
        return folder

    def load_manifest(self, stock_code: str) -> tuple[Path, dict[str, Any]]:
        folder = self.stock_folder(stock_code)
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if str(manifest.get("code")) != stock_code:
            raise ValueError("manifest stock code does not match requested stock")
        return folder, manifest

    def verify(self, stock_code: str) -> dict[str, Any]:
        folder, manifest = self.load_manifest(stock_code)
        results = []
        for filename, expected in manifest.get("sha256", {}).items():
            path = folder / filename
            valid = path.is_file() and file_matches_sha256(path, expected)
            results.append({"file": filename, "sha256": expected, "valid": valid})
        return {
            "valid": bool(results) and all(item["valid"] for item in results),
            "files": results,
            "source": manifest.get("upstream", ""),
            "source_urls": tuple(manifest.get("source_urls", [])),
            "license_status": "review_required",
        }

    def visible_snapshot(self, stock_code: str, as_of: str) -> dict[str, Any]:
        folder, manifest = self.load_manifest(stock_code)
        verification = self.verify(stock_code)
        if not verification["valid"]:
            raise ValueError("evidence hash verification failed")

        price_file = manifest.get("price_file", "601318_unadjusted.csv")
        with (folder / price_file).open(encoding="utf-8-sig", newline="") as handle:
            prices = [row for row in csv.DictReader(handle) if row["日期"] <= as_of]
        documents = [
            item for item in manifest.get("documents", [])
            if item.get("published_date", "") <= as_of
        ]
        dividends = [
            item for item in manifest.get("dividends", [])
            if item.get("record_date", item.get("ex_date", "")) <= as_of
        ]
        return {
            "stock_code": stock_code,
            "stock_name": manifest.get("name", "中国平安" if stock_code == "601318" else ""),
            "as_of": as_of,
            "snapshot_id": f"{stock_code}-{as_of}",
            "prices": prices,
            "documents": documents,
            "dividends": dividends,
            "source": verification["source"],
            "license_status": verification["license_status"],
            "file_hashes": dict(manifest.get("sha256", {})),
        }

