from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORED_PATHS = [ROOT / "README.md", ROOT / "wrangler.jsonc"]
AUTHORED_PATHS.extend(sorted((ROOT / "docs").rglob("*.md")))
AUTHORED_PATHS.extend(sorted((ROOT / "config").glob("*.json")))

# Hashes keep implementation-specific names out of Radar while preventing them
# from silently returning to authored product documentation/configuration.
FORBIDDEN_NAME_HASHES = {
    "c3d9531fd85f4bc8012d489c380d5e46411d1340a14814d761941fe1aead84fd",
    "e24ef8f938288781086e27a9433a4d0472a1dbaac31cfe54be2c3525fa30cb2e",
    "c26b0cf0b3ef6bd4a439d2ac21cb8bc4ffd8054564ff5a079dbde7696962f93d",
    "ea078945fe815cd10beeaff33e40b98c5f43bfd68d2c744827bc3f62ed73ef3b",
    "ca494d180ed93fde18ace7f335d565482f8b5525e9f9527302b31512ae3e97af",
    "76add31cd4fb36122b017a80f038929d3a4816ecea99f4ee2288c7499823d834",
    "246b1b4df5e6aa08f7e7df413d8b1bf7cf1c43e7615004ac2ed6da902f79d141",
    "844bfe9ebdceb4b9353c955bbcda4752d6e2f683163da9cd97230bcc9885ef9c",
    "3133837646a8a94a44dde986b561a41c4e95df717ad7ff45cc90cc96047031a4",
    "9e3feae7c6c2e0520f01acb34a6eb231c8a65712f885986bd0fa0f0d745a3260",
    "b1edffa20e28dd44129ed88b44d444fdfdf006019ef8fae25972bd283d3d4129",
}


class PublicProductBoundaryTests(unittest.TestCase):
    def test_authoritative_document_is_radar_only(self):
        self.assertTrue((ROOT / "docs" / "RADAR-PRODUCT.md").is_file())

    def test_authored_docs_and_config_do_not_name_private_architecture(self):
        violations: list[str] = []
        for path in AUTHORED_PATHS:
            text = path.read_text(encoding="utf-8").lower()
            words = re.findall(r"[a-z0-9]+", f"{path.relative_to(ROOT)} {text}")
            candidates = set(words)
            candidates.update(" ".join(words[index:index + 2]) for index in range(len(words) - 1))
            candidates.update(" ".join(words[index:index + 3]) for index in range(len(words) - 2))
            for candidate in candidates:
                digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
                if digest in FORBIDDEN_NAME_HASHES:
                    violations.append(f"{path.relative_to(ROOT)}: forbidden implementation name")

        self.assertEqual(violations, [])

    def test_production_config_remains_product_neutral(self):
        config = json.loads((ROOT / "config" / "production-migration.json").read_text())
        self.assertEqual(
            config["access"]["machine_authentication"],
            "provider-managed-programmatic-access",
        )


if __name__ == "__main__":
    unittest.main()
