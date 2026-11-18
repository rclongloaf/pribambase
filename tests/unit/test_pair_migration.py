from __future__ import annotations

import contextlib
import importlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
pair_dev = importlib.import_module("pair_dev")


class PairMigrationRecoveryTests(unittest.TestCase):
    def test_failed_blender_migration_restores_entire_source_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blend, sprite, manifest = root / "asset.blend", root / "art.aseprite", root / "asset.pribambase.json"
            blend.write_bytes(b"original geometry and animation")
            sprite.write_bytes(b"original artist channels")
            manifest.write_text(json.dumps({"schema_version": 4, "sources": {
                "blender": blend.name, "aseprite": sprite.name,
            }}))
            originals = {p: p.read_bytes() for p in (blend, sprite, manifest)}

            def fail_after_writes(*args, **kwargs):
                blend.write_bytes(b"partial new format")
                sprite.write_bytes(b"partial sprite")
                manifest.write_text('{"schema_version":5}')
                return 1

            with (
                patch.object(pair_dev, "PROJECT_ROOT", root),
                patch.object(pair_dev.blender_dev, "find_blender", return_value=Path("blender")),
                patch.object(pair_dev.aseprite_dev, "find_aseprite", return_value=Path("aseprite")),
                patch.object(pair_dev.blender_dev, "require_venv"),
                patch.object(pair_dev.blender_dev, "run_blender", side_effect=fail_after_writes),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                with self.assertRaisesRegex(pair_dev.blender_dev.DevError, "Blender migration failed"):
                    pair_dev.migrate(manifest)
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original)
            backups = list((root / "build" / "migrations").iterdir())
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "blender" / blend.name).read_bytes(), originals[blend])

    def test_missing_source_does_not_modify_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blend, manifest = root / "asset.blend", root / "asset.pribambase.json"
            blend.write_bytes(b"original")
            manifest.write_text(json.dumps({"schema_version": 4, "sources": {
                "blender": blend.name, "aseprite": "missing.aseprite",
            }}))
            with self.assertRaisesRegex(pair_dev.blender_dev.DevError, "Missing source"):
                pair_dev.migrate(manifest)
            self.assertEqual(blend.read_bytes(), b"original")
            self.assertFalse((root / "build").exists())


if __name__ == "__main__":
    unittest.main()
