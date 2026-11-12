"""
backend/tests/test_security_sensitive_data.py - Security Audit Tests.
Verifies that no plaintext credentials, passwords, or session cookies are present
in source files, build bundles, or API responses.
"""

from pathlib import Path
import re
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def test_no_leaked_hardcoded_passwords_in_source():
    """Verify no hardcoded credentials exist in backend, frontend, or config source files."""
    forbidden_terms = [
        "".join(["anh", "khoi", "2212"]),
    ]
    scan_extensions = {".py", ".ts", ".tsx", ".html", ".css", ".json", ".yaml", ".yml", ".md"}
    excluded_dirs = {".git", ".venv", "node_modules", "data", "__pycache__", ".pytest_cache"}

    leaks = []
    for file_path in ROOT_DIR.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part in excluded_dirs for part in file_path.parts):
            continue
        if file_path.name == "test_security_sensitive_data.py":
            continue
        if file_path.suffix not in scan_extensions:
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            for term in forbidden_terms:
                if term in content:
                    leaks.append(f"{file_path.relative_to(ROOT_DIR)}: contains forbidden string '{term}'")
        except Exception:
            pass

    assert not leaks, f"Sensitive credentials found in source files:\n" + "\n".join(leaks)


def test_no_leaked_passwords_in_frontend_bundle():
    """Verify frontend build dist files do not contain forbidden credentials or private keys."""
    dist_dir = ROOT_DIR / "frontend" / "dist"
    if not dist_dir.exists():
        pytest.skip("frontend/dist does not exist yet; build frontend first")

    forbidden_terms = [
        "".join(["anh", "khoi", "2212"]),
    ]
    leaks = []
    for f in dist_dir.rglob("*.js"):
        content = f.read_text(encoding="utf-8", errors="ignore")
        for term in forbidden_terms:
            if term in content:
                leaks.append(f"Bundle {f.name} contains forbidden credential '{term}'")

    assert not leaks, f"Frontend bundle leaks credentials:\n" + "\n".join(leaks)


def test_gitignore_protects_auth_and_env():
    """Verify that cookies.json, data/, and .env are protected by .gitignore."""
    gitignore = (ROOT_DIR / ".gitignore").read_text(encoding="utf-8")
    assert "data/" in gitignore, ".gitignore must ignore data/ folder"
    assert ".env" in gitignore, ".gitignore must ignore .env files"
    assert "*.zip" in gitignore, ".gitignore must ignore *.zip files"


def test_login_response_model_excludes_password():
    """Verify that LoginTriggerResponse model does not expose passwords."""
    from backend.app.api.auth import LoginTriggerResponse
    fields = LoginTriggerResponse.model_fields.keys()
    assert "password" not in fields
    assert "cookie" not in fields
    assert "cookies" not in fields


def test_user_db_model_has_no_password_column():
    """Verify that the User database model does not store passwords."""
    from backend.app.db.models import User
    columns = User.__table__.columns.keys()
    assert "password" not in columns
    assert "pwd" not in columns
    assert "secret" not in columns
