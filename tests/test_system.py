import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs

from fastapi.testclient import TestClient
from openpyxl import Workbook

from backend import database
from backend.answering import answer_question
from backend.auth import hash_password, verify_password
from app import app


class FoodiesSystemTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.database_path_patch = patch(
            "backend.database.DATABASE_PATH", root / "foodies.sqlite3"
        )
        self.sop_directory_patch = patch(
            "backend.sops.SOP_DIR", root / "sops" / "approved"
        )
        self.app_root_patch = patch("backend.sops.APP_ROOT", root)
        self.database_root_patch = patch("backend.database.APP_ROOT", root)
        self.upload_dir_patch = patch("backend.ingestion.UPLOAD_DIR", root / "uploads")
        self.database_path_patch.start()
        self.sop_directory = self.sop_directory_patch.start()
        self.app_root_patch.start()
        self.database_root_patch.start()
        self.upload_directory = self.upload_dir_patch.start()
        self.sop_directory.mkdir(parents=True)
        self.secret_patch = patch.dict(
            os.environ, {"FOODIES_JWT_SECRET": "test-secret-that-is-long-enough-123456"}
        )
        self.secret_patch.start()
        self.hash_password_patch = patch("app.hash_password", side_effect=lambda value: value)
        self.verify_password_patch = patch(
            "app.verify_password", side_effect=lambda provided, stored: provided == stored
        )
        self.email_config_patch = patch("app.is_email_configured", return_value=True)
        self.send_email_patch = patch("app.send_activation_email")
        self.hash_password_patch.start()
        self.verify_password_patch.start()
        self.email_config_patch.start()
        self.send_email_mock = self.send_email_patch.start()

        self._write_sop(
            "kitchen-v1.md",
            "SOP-KIT-001",
            "Cold Storage Checks",
            "Kitchen",
            "1.0",
            "Approved",
            "2024-01-01",
            "Staff must check refrigerator temperatures every two hours.",
        )
        self._write_sop(
            "kitchen-draft.md",
            "SOP-KIT-001",
            "Draft Cold Storage Checks",
            "Kitchen",
            "9.0",
            "Draft",
            "2025-01-01",
            "This draft must never appear in search results.",
        )
        self._write_sop(
            "kitchen-future.md",
            "SOP-KIT-001",
            "Future Cold Storage Checks",
            "Kitchen",
            "10.0",
            "Approved",
            "2999-01-01",
            "This future version is not effective yet.",
        )
        self._write_sop(
            "finance.md",
            "SOP-FIN-001",
            "Bill Disputes",
            "Finance",
            "1.0",
            "Approved",
            "2024-01-01",
            "Cashiers must review transaction details and the receipt.",
        )

        database.initialize_database()
        self.admin_id = database.create_user(
            email="admin@example.com",
            name="Foodies Admin",
            department="All",
            role="admin",
            password_hash="admin-password-123",
        )
        self.staff_id = database.create_user(
            email="kitchen@example.com",
            name="Kitchen Staff",
            department="Kitchen",
            role="staff",
            password_hash="kitchen-password-123",
        )
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.admin_token = self._login("admin@example.com", "admin-password-123")
        self.staff_token = self._login("kitchen@example.com", "kitchen-password-123")

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.send_email_patch.stop()
        self.email_config_patch.stop()
        self.verify_password_patch.stop()
        self.hash_password_patch.stop()
        self.secret_patch.stop()
        self.app_root_patch.stop()
        self.database_root_patch.stop()
        self.upload_dir_patch.stop()
        self.sop_directory_patch.stop()
        self.database_path_patch.stop()
        self.temp_directory.cleanup()

    def test_homepage_renders_and_api_requires_authentication(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        response = self.client.post(
            "/api/query", json={"question": "How often check temperatures?"}
        )
        self.assertEqual(response.status_code, 401)

    def test_internal_dot_local_email_can_authenticate(self):
        database.create_user(
            email="internal@foodies.local",
            name="Internal User",
            department="Kitchen",
            role="staff",
            password_hash="internal-password-123",
        )
        response = self.client.post(
            "/api/auth/login",
            json={"email": "internal@foodies.local", "password": "internal-password-123"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user"]["email"], "internal@foodies.local")

    def test_staff_query_is_scoped_and_cites_current_approved_version(self):
        response = self.client.post(
            "/api/query",
            headers=self._authorization(self.staff_token),
            json={"question": "How often check refrigerator temperatures?"},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertIn("every two hours", result["answer"])
        self.assertEqual(result["citations"][0]["sop_id"], "SOP-KIT-001")
        self.assertEqual(result["citations"][0]["version"], "1.0")
        self.assertEqual(result["citations"][0]["department"], "Kitchen")
        self.assertNotIn("Draft", result["answer"])
        self.assertNotIn("Future", result["answer"])

    def test_sop_library_lists_only_the_users_department(self):
        response = self.client.get(
            "/api/sops",
            headers=self._authorization(self.staff_token),
        )
        self.assertEqual(response.status_code, 200, response.text)
        sops = response.json()["sops"]
        self.assertTrue(sops)
        self.assertEqual({sop["department"] for sop in sops}, {"Kitchen"})
        self.assertTrue(all(sop["status"] == "Approved" for sop in sops))

    def test_staff_cannot_request_another_department(self):
        response = self.client.post(
            "/api/query",
            headers=self._authorization(self.staff_token),
            json={"question": "How to resolve a bill dispute?", "department": "Finance"},
        )
        self.assertEqual(response.status_code, 403)
        denied_log = self.client.get(
            "/api/admin/audit-logs", headers=self._authorization(self.admin_token)
        ).json()["audit_logs"][0]
        self.assertEqual(denied_log["question"], "How to resolve a bill dispute?")
        self.assertFalse(denied_log["success"])
        self.assertFalse(denied_log["missing_sop"])
        visible_departments = self.client.get(
            "/api/departments", headers=self._authorization(self.staff_token)
        )
        self.assertEqual(visible_departments.json()["departments"], ["Kitchen"])

    def test_missing_sop_is_reported_and_audited(self):
        response = self.client.post(
            "/api/query",
            headers=self._authorization(self.staff_token),
            json={"question": "What is the staff uniform color?"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["missing_sop"])
        self.assertEqual(response.json()["citations"], [])

        logs = self.client.get(
            "/api/admin/audit-logs", headers=self._authorization(self.admin_token)
        )
        self.assertEqual(logs.status_code, 200)
        self.assertEqual(len(logs.json()["audit_logs"]), 1)
        entry = logs.json()["audit_logs"][0]
        self.assertTrue(entry["missing_sop"])
        self.assertFalse(entry["success"])
        self.assertEqual(entry["user_id"], self.staff_id)
        self.assertEqual(entry["question"], "What is the staff uniform color?")

    def test_answer_provider_receives_only_retrieved_sources_and_citations_stay_server_owned(self):
        matches = [
            {
                "sop_id": "SOP-KIT-001",
                "title": "Cold Storage Checks",
                "department": "Kitchen",
                "version": "1.0",
                "section_heading": "Checks",
                "section_text": "Check temperatures every two hours.",
                "source_path": "data/sops/approved/kitchen-v1.md",
                "effective_date": "2024-01-01",
            }
        ]
        provider = Mock()
        provider.generate.return_value = "Generated grounded response."

        result = answer_question(
            "How often check temperatures?",
            "Kitchen",
            matches,
            provider=provider,
        )

        provider.generate.assert_called_once_with(
            "How often check temperatures?",
            matches,
        )
        self.assertEqual(result["answer"], "Generated grounded response.")
        self.assertEqual(result["citations"][0]["sop_id"], "SOP-KIT-001")
        self.assertFalse(result["missing_sop"])

    def test_missing_sop_does_not_call_answer_provider(self):
        provider = Mock()

        result = answer_question("Unknown policy?", "Kitchen", [], provider=provider)

        provider.generate.assert_not_called()
        self.assertTrue(result["missing_sop"])
        self.assertEqual(result["citations"], [])

    def test_admin_can_search_all_departments_but_staff_cannot_read_audit(self):
        admin_result = self.client.post(
            "/api/query",
            headers=self._authorization(self.admin_token),
            json={"question": "How should cashier review receipt?", "department": "Finance"},
        )
        self.assertEqual(admin_result.status_code, 200)
        self.assertEqual(admin_result.json()["citations"][0]["department"], "Finance")
        self.assertEqual(admin_result.json()["citations"][0]["section"], "Checks")

        staff_logs = self.client.get(
            "/api/admin/audit-logs", headers=self._authorization(self.staff_token)
        )
        self.assertEqual(staff_logs.status_code, 403)

    def test_admin_can_create_account_and_deactivated_user_loses_access(self):
        created = self.client.post(
            "/api/admin/users",
            headers=self._authorization(self.admin_token),
            json={
                "email": "frontdesk@example.com",
                "name": "Front Desk",
                "department": "Front of House",
                "role": "staff",
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json()["email_sent"])
        self.assertEqual(self.send_email_mock.call_args.kwargs["email"], "frontdesk@example.com")
        invited = database.get_user_by_id(created.json()["id"])
        self.assertFalse(invited["is_active"])
        self.assertTrue(invited["must_change_password"])

        disabled = self.client.patch(
            f"/api/admin/users/{created.json()['id']}/active",
            headers=self._authorization(self.admin_token),
            json={"is_active": False},
        )
        self.assertEqual(disabled.status_code, 200)

    def test_activation_uses_one_time_token_and_temporary_password(self):
        created = self.client.post(
            "/api/admin/users",
            headers=self._authorization(self.admin_token),
            json={
                "email": "new-staff@example.com",
                "name": "New Staff",
                "department": "Kitchen",
                "role": "staff",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        sent_email = self.send_email_mock.call_args.kwargs
        activation_token = parse_qs(urlsplit(sent_email["link"]).fragment)["token"][0]
        temporary_password = sent_email["temporary_password"]

        resent = self.client.post(
            f"/api/admin/users/{created.json()['id']}/activation",
            headers=self._authorization(self.admin_token),
        )
        self.assertEqual(resent.status_code, 200, resent.text)
        resent_email = self.send_email_mock.call_args.kwargs
        resent_token = parse_qs(urlsplit(resent_email["link"]).fragment)["token"][0]
        self.assertNotEqual(activation_token, resent_token)
        stale_activation = self.client.post(
            "/api/auth/activate",
            json={
                "token": activation_token,
                "temporary_password": temporary_password,
                "new_password": "permanent-password-654",
                "confirm_password": "permanent-password-654",
            },
        )
        self.assertEqual(stale_activation.status_code, 400)
        activation_token = resent_token
        temporary_password = resent_email["temporary_password"]

        unauthenticated_login = self.client.post(
            "/api/auth/login",
            json={"email": "new-staff@example.com", "password": temporary_password},
        )
        self.assertEqual(unauthenticated_login.status_code, 401)

        payload = {
            "token": activation_token,
            "temporary_password": temporary_password,
            "new_password": temporary_password,
            "confirm_password": temporary_password,
        }
        reused_password = self.client.post("/api/auth/activate", json=payload)
        self.assertEqual(reused_password.status_code, 422)

        payload = {
            "token": activation_token,
            "temporary_password": temporary_password,
            "new_password": "permanent-password-654",
            "confirm_password": "permanent-password-654",
        }
        activated = self.client.post("/api/auth/activate", json=payload)
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertTrue(activated.json()["activated"])

        activated_login = self.client.post(
            "/api/auth/login",
            json={
                "email": "new-staff@example.com",
                "password": "permanent-password-654",
            },
        )
        self.assertEqual(activated_login.status_code, 200, activated_login.text)
        temporary_login = self.client.post(
            "/api/auth/login",
            json={"email": "new-staff@example.com", "password": temporary_password},
        )
        self.assertEqual(temporary_login.status_code, 401)
        reused_link = self.client.post("/api/auth/activate", json=payload)
        self.assertEqual(reused_link.status_code, 400)

    def test_spreadsheet_preview_validates_rows_and_bulk_creation_invites_valid_users(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["name", "email", "department", "role"])
        sheet.append(["Bulk One", "bulk-one@example.com", "Kitchen", "staff"])
        sheet.append(["Missing Email", "", "Kitchen", "staff"])
        sheet.append(["Invalid Role", "bulk-two@example.com", "Finance", "supervisor"])
        file_content = BytesIO()
        workbook.save(file_content)
        preview = self.client.post(
            "/api/admin/users/preview",
            headers=self._authorization(self.admin_token),
            files={
                "file": (
                    "team.xlsx",
                    file_content.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["valid_count"], 1)
        rows = preview.json()["users"]
        self.assertTrue(rows[0]["valid"])
        self.assertIn("A valid email address is required.", rows[1]["errors"])
        self.assertIn("Role must be staff, manager, or admin.", rows[2]["errors"])

        created = self.client.post(
            "/api/admin/users/bulk",
            headers=self._authorization(self.admin_token),
            json={
                "users": [
                    {
                        "name": rows[0]["name"],
                        "email": rows[0]["email"],
                        "department": rows[0]["department"],
                        "role": rows[0]["role"],
                    }
                ]
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["created_count"], 1)
        self.assertEqual(created.json()["results"][0]["status"], "created")
        self.assertEqual(self.send_email_mock.call_count, 1)

    def test_admin_delete_requires_confirmation_authorization_and_retains_audit(self):
        record = database.get_user_by_id(self.staff_id)
        database.record_audit_log(
            user_id=self.staff_id,
            email=record["email"],
            department=record["department"],
            role=record["role"],
            question="Historical question",
            answer="Historical answer",
            retrieved_sops=[],
            citations=[],
            success=False,
            missing_sop=True,
        )
        denied = self.client.delete(
            f"/api/admin/users/{self.staff_id}",
            headers=self._authorization(self.staff_token),
        )
        self.assertEqual(denied.status_code, 403)
        self_delete = self.client.delete(
            f"/api/admin/users/{self.admin_id}",
            headers=self._authorization(self.admin_token),
        )
        self.assertEqual(self_delete.status_code, 400)
        deleted = self.client.delete(
            f"/api/admin/users/{self.staff_id}",
            headers=self._authorization(self.admin_token),
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertIsNone(database.get_user_by_id(self.staff_id))
        historical_logs = database.list_audit_logs(10)
        self.assertEqual(historical_logs[0]["email"], "kitchen@example.com")

    def test_admin_cannot_delete_last_active_administrator(self):
        with self.assertRaisesRegex(ValueError, "last active administrator"):
            database.delete_user(self.admin_id)

    def test_account_invitation_requires_email_configuration(self):
        with patch("app.is_email_configured", return_value=False):
            response = self.client.post(
                "/api/admin/users",
                headers=self._authorization(self.admin_token),
                json={
                    "email": "no-email@example.com",
                    "name": "No Email",
                    "department": "Kitchen",
                    "role": "staff",
                },
            )
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(database.get_user_by_email("no-email@example.com"))

    def test_admin_password_reset_requires_change_and_revokes_old_sessions(self):
        reset = self.client.post(
            f"/api/admin/users/{self.staff_id}/password-reset",
            headers=self._authorization(self.admin_token),
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertTrue(reset.json()["must_change_password"])
        temporary_password = reset.json()["temporary_password"]
        self.assertGreaterEqual(len(temporary_password), 12)

        old_session = self.client.get(
            "/api/auth/me", headers=self._authorization(self.staff_token)
        )
        self.assertEqual(old_session.status_code, 401)

        temporary_login = self.client.post(
            "/api/auth/login",
            json={
                "email": "kitchen@example.com",
                "password": temporary_password,
            },
        )
        self.assertEqual(temporary_login.status_code, 200, temporary_login.text)
        self.assertTrue(temporary_login.json()["user"]["must_change_password"])
        temporary_token = temporary_login.json()["access_token"]

        denied = self.client.get(
            "/api/departments", headers=self._authorization(temporary_token)
        )
        self.assertEqual(denied.status_code, 403)

        unchanged = self.client.post(
            "/api/auth/change-password",
            headers=self._authorization(temporary_token),
            json={
                "new_password": temporary_password,
                "confirm_password": temporary_password,
            },
        )
        self.assertEqual(unchanged.status_code, 400)

        second_reset = self.client.post(
            f"/api/admin/users/{self.staff_id}/password-reset",
            headers=self._authorization(self.admin_token),
        )
        self.assertEqual(second_reset.status_code, 200, second_reset.text)
        second_temporary_password = second_reset.json()["temporary_password"]
        stale_change = self.client.post(
            "/api/auth/change-password",
            headers=self._authorization(temporary_token),
            json={
                "new_password": "new-kitchen-password-456",
                "confirm_password": "new-kitchen-password-456",
            },
        )
        self.assertEqual(stale_change.status_code, 401)

        new_temporary_login = self.client.post(
            "/api/auth/login",
            json={
                "email": "kitchen@example.com",
                "password": second_temporary_password,
            },
        )
        self.assertEqual(new_temporary_login.status_code, 200, new_temporary_login.text)
        temporary_token = new_temporary_login.json()["access_token"]

        changed = self.client.post(
            "/api/auth/change-password",
            headers=self._authorization(temporary_token),
            json={
                "new_password": "new-kitchen-password-456",
                "confirm_password": "new-kitchen-password-456",
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertFalse(changed.json()["user"]["must_change_password"])

        new_token = changed.json()["access_token"]
        allowed = self.client.get(
            "/api/auth/me", headers=self._authorization(new_token)
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)

        old_password_login = self.client.post(
            "/api/auth/login",
            json={
                "email": "kitchen@example.com",
                "password": temporary_password,
            },
        )
        self.assertEqual(old_password_login.status_code, 401)

    def test_admin_cannot_reset_own_password(self):
        response = self.client.post(
            f"/api/admin/users/{self.admin_id}/password-reset",
            headers=self._authorization(self.admin_token),
        )
        self.assertEqual(response.status_code, 400)

    def test_uploaded_sop_requires_review_before_it_can_be_retrieved(self):
        response = self.client.post(
            "/api/admin/sops/upload",
            headers=self._authorization(self.admin_token),
            data={
                "sop_id": "SOP-KIT-NEW",
                "title": "Handwashing Procedure",
                "department": "Kitchen",
                "owner": "Head Chef",
                "version": "1.0",
                "effective_date": "2024-01-01",
            },
            files={
                "file": (
                    "handwashing.md",
                    b"# Handwashing Procedure\n\n## Handwashing\n\nWash hands with soap for 20 seconds.",
                    "text/markdown",
                )
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        version_id = response.json()["id"]
        self.assertEqual(response.json()["status"], "pending_review")
        preview = self.client.get(
            f"/api/admin/sops/{version_id}",
            headers=self._authorization(self.admin_token),
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["sop"]["status"], "pending_review")
        self.assertIn("20 seconds", preview.json()["sections"][0]["content"])
        self.assertNotIn("storage_path", preview.json()["sop"])
        staff_preview = self.client.get(
            f"/api/admin/sops/{version_id}",
            headers=self._authorization(self.staff_token),
        )
        self.assertEqual(staff_preview.status_code, 403)
        self.assertEqual(
            [event["action"] for event in self.client.get(
                f"/api/admin/sops/{version_id}/events",
                headers=self._authorization(self.admin_token),
            ).json()["events"]],
            ["upload"],
        )

        before_review = self.client.post(
            "/api/query",
            headers=self._authorization(self.staff_token),
            json={"question": "How long should I wash hands?"},
        )
        self.assertTrue(before_review.json()["missing_sop"])

        approval = self.client.post(
            f"/api/admin/sops/{version_id}/review",
            headers=self._authorization(self.admin_token),
            data={"action": "approve", "review_note": "Verified"},
        )
        self.assertEqual(approval.status_code, 200, approval.text)
        self.assertEqual(approval.json()["sop"]["status"], "approved")
        self.assertEqual(
            {event["action"] for event in approval.json()["events"]},
            {"upload", "approve"},
        )

        after_review = self.client.post(
            "/api/query",
            headers=self._authorization(self.staff_token),
            json={"question": "How long should I wash hands?"},
        )
        self.assertFalse(after_review.json()["missing_sop"])
        self.assertIn("20 seconds", after_review.json()["answer"])
        self.assertEqual(after_review.json()["citations"][0]["sop_id"], "SOP-KIT-NEW")
        library = self.client.get(
            "/api/sops",
            headers=self._authorization(self.staff_token),
        )
        self.assertIn(
            "SOP-KIT-NEW",
            {sop["sop_id"] for sop in library.json()["sops"]},
        )

    def test_password_hash_is_salted_and_verifies(self):
        with patch("backend.auth.PASSWORD_ITERATIONS", 100_000):
            first_hash = hash_password("correct-password")
            second_hash = hash_password("correct-password")
        self.assertNotEqual(first_hash, second_hash)
        self.assertTrue(verify_password("correct-password", first_hash))
        self.assertFalse(verify_password("incorrect-password", first_hash))

    def test_password_verification_rejects_malformed_or_unsupported_hashes(self):
        invalid_hashes = [
            "",
            "pbkdf2_sha256$99999$" + "00" * 16 + "$" + "00" * 32,
            "pbkdf2_sha256$2000001$" + "00" * 16 + "$" + "00" * 32,
            "pbkdf2_sha256$310000$00$" + "00" * 32,
            "pbkdf2_sha256$310000$" + "00" * 16 + "$00",
            "pbkdf2_sha256$310000$zz$" + "00" * 32,
            "pbkdf2_sha256$310000$" + "0 " * 16 + "$" + "00" * 32,
            "pbkdf2_sha256$+310000$" + "00" * 16 + "$" + "00" * 32,
            "pbkdf2_sha256$٣١٠٠٠٠$" + "00" * 16 + "$" + "00" * 32,
            "other$310000$" + "00" * 16 + "$" + "00" * 32,
            "pbkdf2_sha256$310000$" + "00" * 16 + "$" + "00" * 31,
            "pbkdf2_sha256$310000$" + "00" * 16 + "$" + "00" * 32 + "00" * 1000,
        ]
        for encoded_hash in invalid_hashes:
            with self.subTest(encoded_hash=encoded_hash):
                self.assertFalse(verify_password("password", encoded_hash))

    def _login(self, email, password):
        response = self.client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["access_token"]

    @staticmethod
    def _authorization(token):
        return {"Authorization": f"Bearer {token}"}

    def _write_sop(
        self, filename, sop_id, title, department, version, status, effective_date, content
    ):
        path = self.sop_directory / filename
        path.write_text(
            f"""---
id: {sop_id}
title: {title}
department: {department}
owner: Manager
status: {status}
version: {version}
effective_date: {effective_date}
approved_by: Manager
approved_date: 2024-01-01
---

# {title}

## Checks

{content}
""",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
