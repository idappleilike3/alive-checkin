import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path

from Crypto.Cipher import AES

import app as alive_app


class R2BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = Path(self.temp_dir.name) / "state.json"
        state = copy.deepcopy(alive_app.DEFAULT_STATE)
        state["users"]["U-private"] = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": "U-private",
            "display_name": "私密會員",
        }
        alive_app.save_state(self.data_file, state)

    def test_backup_is_encrypted_before_r2_upload_and_can_be_verified(self):
        uploads = []
        key = b"k" * 32

        def uploader(bucket, object_key, body, content_type, metadata, config):
            uploads.append((bucket, object_key, body, content_type, metadata))
            return {"etag": '"etag-1"'}

        result, code = alive_app.create_r2_encrypted_backup(
            {
                "DATA_FILE": str(self.data_file),
                "R2_BUCKET": "alive-backups",
                "R2_BACKUP_ENCRYPTION_KEY": base64.urlsafe_b64encode(key).decode(),
                "R2_UPLOADER": uploader,
            }
        )

        self.assertEqual(code, 201)
        self.assertEqual(len(uploads), 1)
        bucket, object_key, encrypted, content_type, metadata = uploads[0]
        self.assertEqual(bucket, "alive-backups")
        self.assertTrue(object_key.endswith(".json.aesgcm"))
        self.assertEqual(content_type, "application/octet-stream")
        self.assertNotIn(b"U-private", encrypted)
        envelope = json.loads(encrypted)
        cipher = AES.new(
            key,
            AES.MODE_GCM,
            nonce=base64.b64decode(envelope["nonce"]),
        )
        plaintext = cipher.decrypt_and_verify(
            base64.b64decode(envelope["ciphertext"]),
            base64.b64decode(envelope["tag"]),
        )
        snapshot = json.loads(plaintext)
        self.assertIn("U-private", snapshot["snapshot"]["users"])
        self.assertEqual(metadata["encryption"], "AES-256-GCM")
        self.assertEqual(result["backup"]["etag"], "etag-1")

    def test_backup_fails_closed_without_bucket_or_encryption_key(self):
        for config in (
            {"DATA_FILE": str(self.data_file), "R2_BACKUP_ENCRYPTION_KEY": "x" * 32},
            {"DATA_FILE": str(self.data_file), "R2_BUCKET": "alive-backups"},
        ):
            with self.subTest(config=config):
                result, code = alive_app.create_r2_encrypted_backup(config)
                self.assertEqual(code, 503)
                self.assertEqual(result["error"], "r2_backup_not_configured")


if __name__ == "__main__":
    unittest.main()
