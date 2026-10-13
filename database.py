import os
import json
import uuid
import time
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "nova_venom.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def hash_password(password: str, salt: Optional[str] = None) -> str:
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, _ = stored_hash.split("$", 1)
        return secrets.compare_digest(hash_password(password, salt), stored_hash)
    except Exception:
        return False


DEFAULT_MODELS = [
    {
        "id": "mdl_nova_local",
        "model_id": "nova-venom-core-v1",
        "display_name": "NOVA / Venom Core v1 (Built-in Local Engine)",
        "provider": "nova_local",
        "capabilities": ["chat", "code", "math", "documents", "osint", "streaming", "hindi_hinglish"],
        "env_key_name": "",
        "is_enabled": 1,
        "is_free_tier": 1,
        "max_input_tokens": 8192,
        "max_output_tokens": 4096,
    },
    {
        "id": "mdl_claude_sonnet",
        "model_id": "claude-3-5-sonnet-latest",
        "display_name": "Anthropic Claude 3.5 Sonnet (Official API)",
        "provider": "anthropic",
        "capabilities": ["chat", "code", "vision", "analysis", "streaming"],
        "env_key_name": "ANTHROPIC_API_KEY",
        "is_enabled": 1,
        "is_free_tier": 0,
        "max_input_tokens": 8192,
        "max_output_tokens": 4096,
    },
    {
        "id": "mdl_gemini_flash",
        "model_id": "gemini-2.5-flash",
        "display_name": "Google Gemini 2.5 Flash (Official API)",
        "provider": "gemini",
        "capabilities": ["chat", "code", "vision", "fast_reasoning", "streaming"],
        "env_key_name": "GEMINI_API_KEY",
        "is_enabled": 1,
        "is_free_tier": 1,
        "max_input_tokens": 8192,
        "max_output_tokens": 4096,
    },
    {
        "id": "mdl_openrouter_llama",
        "model_id": "meta-llama/llama-3.3-70b-instruct:free",
        "display_name": "Llama 3.3 70B Instruct (via OpenRouter Free Tier)",
        "provider": "openrouter",
        "capabilities": ["chat", "code", "multilingual", "streaming"],
        "env_key_name": "OPENROUTER_API_KEY",
        "is_enabled": 1,
        "is_free_tier": 1,
        "max_input_tokens": 4096,
        "max_output_tokens": 2048,
    },
    {
        "id": "mdl_openrouter_qwen",
        "model_id": "qwen/qwen-2.5-coder-32b-instruct:free",
        "display_name": "Qwen 2.5 Coder 32B (via OpenRouter Free Tier)",
        "provider": "openrouter",
        "capabilities": ["code", "debugging", "chat", "streaming"],
        "env_key_name": "OPENROUTER_API_KEY",
        "is_enabled": 1,
        "is_free_tier": 1,
        "max_input_tokens": 4096,
        "max_output_tokens": 2048,
    },
]


class DatabaseManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        conn = self.get_conn()
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

        now = utc_now()
        cur = conn.cursor()

        # Seed default models
        for m in DEFAULT_MODELS:
            cur.execute(
                """
                INSERT OR IGNORE INTO configured_models
                (id, model_id, display_name, provider, capabilities_json, env_key_name, is_enabled, is_free_tier, max_input_tokens, max_output_tokens, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    m["id"],
                    m["model_id"],
                    m["display_name"],
                    m["provider"],
                    json.dumps(m["capabilities"]),
                    m["env_key_name"],
                    m["is_enabled"],
                    m["is_free_tier"],
                    m["max_input_tokens"],
                    m["max_output_tokens"],
                    now,
                ),
            )

        # Seed default system settings
        default_settings = {
            "daily_request_limit_per_user": "100",
            "max_upload_size_mb": "10",
            "max_input_tokens": "4096",
            "max_output_tokens": "2048",
            "allow_fallback_to_local": "false",
            "web_search_enabled": "true",
            "code_sandbox_enabled": "true",
        }
        for k, v in default_settings.items():
            cur.execute(
                "INSERT OR IGNORE INTO system_settings (setting_key, setting_value, updated_at) VALUES (?, ?, ?)",
                (k, v, now),
            )

        # Seed Admin User (Himanshu) & Normal User
        cur.execute("SELECT COUNT(*) as cnt FROM profiles")
        if cur.fetchone()["cnt"] == 0:
            admin_id = "usr_admin_himanshu"
            user_id = "usr_standard_demo"

            cur.execute(
                """
                INSERT INTO profiles (id, email, username, password_hash, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'admin', 1, ?, ?)
                """,
                (admin_id, "himanshu@nova.ai", "Himanshu (Founder & Admin)", hash_password("Himanshu@123"), now, now),
            )
            cur.execute(
                """
                INSERT INTO user_preferences (user_id, preferred_model, theme, language_pref, response_style, updated_at)
                VALUES (?, 'nova-venom-core-v1', 'dark', 'Hinglish', 'balanced', ?)
                """,
                (admin_id, now),
            )

            cur.execute(
                """
                INSERT INTO profiles (id, email, username, password_hash, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'user', 1, ?, ?)
                """,
                (user_id, "user@nova.ai", "Aarav Sharma (User)", hash_password("User@123"), now, now),
            )
            cur.execute(
                """
                INSERT INTO user_preferences (user_id, preferred_model, theme, language_pref, response_style, updated_at)
                VALUES (?, 'nova-venom-core-v1', 'dark', 'Hinglish', 'balanced', ?)
                """,
                (user_id, now),
            )

            # Seed sample multi-file project for Himanshu in Coding Studio
            proj_id = "proj_starter_venom"
            cur.execute(
                """
                INSERT INTO projects (id, user_id, name, description, primary_language, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'python', ?, ?)
                """,
                (
                    proj_id,
                    admin_id,
                    "NOVA-Venom Autonomous Agent Starter",
                    "Multi-file Python & Web starter project in AI Coding Studio",
                    now,
                    now,
                ),
            )
            starter_py = (
                "# NOVA AI (Project: Venom AI) — Isolated Sandbox Script\n"
                "# Developed by Himanshu\n\n"
                "def analyze_metrics(values):\n"
                "    total = sum(values)\n"
                "    mean = total / len(values)\n"
                "    return {'count': len(values), 'sum': total, 'mean': round(mean, 2), 'max': max(values)}\n\n"
                "data = [42, 88, 95, 67, 91, 104]\n"
                "print('📊 Computed Metrics:', analyze_metrics(data))\n"
            )
            starter_html = (
                "<!DOCTYPE html>\n<html>\n<head>\n<style>\n"
                "body { font-family: sans-serif; background: #090d16; color: #f8fafc; text-align: center; padding: 40px; }\n"
                ".card { background: #131c31; border: 1px solid #6366f1; border-radius: 14px; padding: 28px; max-width: 520px; margin: 0 auto; }\n"
                "button { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 700; cursor: pointer; margin-top: 14px; }\n"
                "</style>\n</head>\n<body>\n"
                "  <div class='card'>\n"
                "    <h2>⚡ NOVA AI Live Web Preview</h2>\n"
                "    <p style='color:#94a3b8;margin-top:8px;'>Safely rendered inside isolated Coding Studio Sandbox</p>\n"
                "    <button onclick=\"alert('Interactive Web Preview Working!')\">Test Interactive Button</button>\n"
                "  </div>\n"
                "</body>\n</html>"
            )
            cur.execute(
                """
                INSERT INTO project_files (id, project_id, user_id, filename, language, content, size_bytes, created_at, updated_at)
                VALUES (?, ?, ?, 'main.py', 'python', ?, ?, ?, ?)
                """,
                ("pfile_1", proj_id, admin_id, starter_py, len(starter_py), now, now),
            )
            cur.execute(
                """
                INSERT INTO project_files (id, project_id, user_id, filename, language, content, size_bytes, created_at, updated_at)
                VALUES (?, ?, ?, 'index.html', 'html', ?, ?, ?, ?)
                """,
                ("pfile_2", proj_id, admin_id, starter_html, len(starter_html), now, now),
            )

        conn.commit()
        conn.close()

    # ==================== AUTH & SESSIONS ====================
    def create_user(self, email: str, username: str, password: str, role: str = "user") -> Tuple[bool, Any]:
        email = email.strip().lower()
        username = username.strip()
        if not email or "@" not in email or len(password) < 6:
            return False, "Valid email and password (min 6 chars) are required."

        conn = self.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM profiles WHERE email = ?", (email,))
        if cur.fetchone():
            conn.close()
            return False, "An account with this email already exists."

        uid = f"usr_{uuid.uuid4().hex[:12]}"
        now = utc_now()
        cur.execute(
            """
            INSERT INTO profiles (id, email, username, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (uid, email, username or email.split("@")[0], hash_password(password), role, now, now),
        )
        cur.execute(
            """
            INSERT INTO user_preferences (user_id, preferred_model, theme, language_pref, response_style, updated_at)
            VALUES (?, 'nova-venom-core-v1', 'dark', 'Hinglish', 'balanced', ?)
            """,
            (uid, now),
        )
        self.log_audit(cur, uid, "user_signup", f"Registered user {email}")
        conn.commit()
        conn.close()
        return True, self.get_user_by_id(uid)

    def authenticate_user(self, email: str, password: str) -> Tuple[bool, Any]:
        conn = self.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM profiles WHERE email = ? AND is_active = 1", (email.strip().lower(),))
        row = cur.fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            conn.close()
            return False, "Invalid email or password."

        token = f"nvsess_{secrets.token_urlsafe(32)}"
        now = utc_now()
        expires = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
        cur.execute(
            "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, row["id"], expires, now),
        )
        self.log_audit(cur, row["id"], "user_login", f"User {email} logged in")
        conn.commit()
        conn.close()
        user_dict = self.get_user_by_id(row["id"])
        return True, {"token": token, "user": user_dict}

    def get_user_by_token(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        clean = token.replace("Bearer ", "").strip()
        conn = self.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id, expires_at FROM sessions WHERE token = ?", (clean,))
        srow = cur.fetchone()
        conn.close()
        if not srow:
            return None
        if srow["expires_at"] < utc_now():
            return None
        return self.get_user_by_id(srow["user_id"])

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        conn = self.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, email, username, role, is_active, created_at FROM profiles WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return None
        user_data = dict(row)
        cur.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,))
        pref = cur.fetchone()
        user_data["preferences"] = dict(pref) if pref else {}
        conn.close()
        return user_data

    def reset_password(self, email: str, new_password: str) -> Tuple[bool, str]:
        if len(new_password) < 6:
            return False, "New password must be at least 6 characters."
        conn = self.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM profiles WHERE email = ?", (email.strip().lower(),))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False, "No account found with that email address."
        cur.execute(
            "UPDATE profiles SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hash_password(new_password), utc_now(), row["id"]),
        )
        self.log_audit(cur, row["id"], "password_reset", f"Password reset for {email}")
        conn.commit()
        conn.close()
        return True, "Password updated successfully."

    def delete_user_account(self, user_id: str) -> bool:
        conn = self.get_conn()
        cur = conn.cursor()
        self.log_audit(cur, user_id, "account_deleted", f"User {user_id} deleted their account & all data")
        cur.execute("DELETE FROM profiles WHERE id = ?", (user_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def log_audit(self, cur: sqlite3.Cursor, user_id: Optional[str], action: str, detail: str):
        cur.execute(
            "INSERT INTO audit_logs (id, user_id, action, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (f"aud_{uuid.uuid4().hex[:10]}", user_id, action, detail[:300], utc_now()),
        )

    # ==================== QUOTAS & USAGE TRACKING ====================
    def check_user_quota(self, user_id: str) -> Tuple[bool, str, Dict[str, int]]:
        conn = self.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT setting_value FROM system_settings WHERE setting_key = 'daily_request_limit_per_user'")
        row = cur.fetchone()
        daily_limit = int(row["setting_value"]) if row else 100

        today_prefix = datetime.utcnow().strftime("%Y-%m-%d")
        cur.execute(
            "SELECT COUNT(*) as cnt FROM usage_records WHERE user_id = ? AND created_at LIKE ?",
            (user_id, f"{today_prefix}%"),
        )
        used_today = cur.fetchone()["cnt"]
        conn.close()

        stats = {"used_today": used_today, "daily_limit": daily_limit, "remaining": max(0, daily_limit - used_today)}
        if used_today >= daily_limit:
            return False, f"Free-tier daily request limit reached ({used_today}/{daily_limit}). Please contact Admin or wait until UTC midnight.", stats
        return True, "ok", stats

    def record_usage(
        self,
        user_id: str,
        model_id: str,
        provider: str,
        endpoint: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        status: str,
        error_detail: str = "",
    ):
        conn = self.get_conn()
        conn.execute(
            """
            INSERT INTO usage_records
            (id, user_id, model_id, provider, endpoint, input_tokens, output_tokens, latency_ms, status, error_detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"usg_{uuid.uuid4().hex[:12]}",
                user_id,
                model_id,
                provider,
                endpoint,
                input_tokens,
                output_tokens,
                round(latency_ms, 2),
                status,
                error_detail[:250],
                utc_now(),
            ),
        )
        conn.commit()
        conn.close()


db = DatabaseManager()
