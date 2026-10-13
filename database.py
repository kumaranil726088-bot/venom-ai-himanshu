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
DB_PATH = os.path.join(BASE_DIR, "venom_ai.db")
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


# 100% HIMANSHU'S OWN VENOM AI MODELS — ALL WORKING OUT OF THE BOX (ZERO EXTERNAL KEYS NEEDED)
DEFAULT_MODELS = [
    {
        "id": "1_mdl_venom_pro",
        "model_id": "venom-pro-v1",
        "display_name": "⚡ VENOM AI Pro v1 (Flagship Coding & Builder Engine — by Himanshu)",
        "provider": "venom_engine",
        "capabilities": ["chat", "code", "website_builder", "telegram_bot", "math", "documents", "osint", "streaming", "hindi_hinglish"],
        "env_key_name": "",
        "is_enabled": 1,
        "is_free_tier": 1,
        "max_input_tokens": 16384,
        "max_output_tokens": 8192,
    },
    {
        "id": "2_mdl_venom_coder",
        "model_id": "venom-coder-x",
        "display_name": "💻 VENOM Coder-X (Autonomous Website, App & Telegram Bot Engine)",
        "provider": "venom_engine",
        "capabilities": ["code", "website_builder", "app_builder", "telegram_bot", "osint", "debugging", "streaming"],
        "env_key_name": "",
        "is_enabled": 1,
        "is_free_tier": 1,
        "max_input_tokens": 16384,
        "max_output_tokens": 8192,
    },
    {
        "id": "3_mdl_venom_turbo",
        "model_id": "venom-turbo-fast",
        "display_name": "🚀 VENOM Turbo Fast (Ultra-Fast <10ms Instant Reasoning & Math)",
        "provider": "venom_engine",
        "capabilities": ["chat", "fast_reasoning", "math", "code", "hindi_hinglish", "streaming"],
        "env_key_name": "",
        "is_enabled": 1,
        "is_free_tier": 1,
        "max_input_tokens": 8192,
        "max_output_tokens": 4096,
    },
    {
        "id": "4_mdl_venom_research",
        "model_id": "venom-research-web",
        "display_name": "🌐 VENOM Deep Research (Live Web Search & Knowledge Engine)",
        "provider": "venom_engine",
        "capabilities": ["web_search", "research", "citations", "chat", "streaming"],
        "env_key_name": "",
        "is_enabled": 1,
        "is_free_tier": 1,
        "max_input_tokens": 8192,
        "max_output_tokens": 4096,
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

        # Always keep configured_models strictly synced to Himanshu's own VENOM AI models
        cur.execute("DELETE FROM configured_models")
        for m in DEFAULT_MODELS:
            cur.execute(
                """
                INSERT INTO configured_models
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
            "daily_request_limit_per_user": "500",
            "max_upload_mb": "10",
            "max_input_chars": "16000",
            "sandbox_timeout_seconds": "3.0",
            "platform_owner": "Himanshu",
            "platform_name": "VENOM AI",
            "venom_custom_api_key": "venom_live_himanshu_official_api_v1",
        }
        for k, v in default_settings.items():
            cur.execute(
                "INSERT OR REPLACE INTO system_settings (setting_key, setting_value, updated_at) VALUES (?, ?, ?)",
                (k, v, now),
            )

        # Seed default Admin User (Himanshu) and Demo Standard User
        cur.execute("SELECT id FROM profiles WHERE email = 'himanshu@nova.ai'")
        if not cur.fetchone():
            admin_id = "usr_admin_himanshu"
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
                VALUES (?, 'venom-pro-v1', 'dark', 'Hinglish', 'balanced', ?)
                """,
                (admin_id, now),
            )
            proj_id = "proj_starter_venom"
            cur.execute(
                """
                INSERT INTO projects (id, user_id, name, description, primary_language, created_at, updated_at)
                VALUES (?, ?, 'Venom Core Starter App', 'Multi-file Python & Web starter workspace', 'python', ?, ?)
                """,
                (proj_id, admin_id, now, now),
            )
            starter_py = (
                "# VENOM AI — Isolated Sandbox Starter\n"
                "# Developed by Himanshu\n\n"
                "def calculate_growth(users: list[int]) -> dict:\n"
                "    total = sum(users)\n"
                "    avg = round(total / max(len(users), 1), 2)\n"
                "    return {'total_users': total, 'average_daily': avg, 'peak': max(users)}\n\n"
                "if __name__ == '__main__':\n"
                "    metrics = calculate_growth([120, 245, 310, 490, 680])\n"
                "    print('VENOM AI Analytics:', metrics)\n"
            )
            cur.execute(
                """
                INSERT INTO project_files (id, project_id, user_id, filename, language, content, size_bytes, created_at, updated_at)
                VALUES (?, ?, ?, 'main.py', 'python', ?, ?, ?, ?)
                """,
                ("pfile_starter_1", proj_id, admin_id, starter_py, len(starter_py), now, now),
            )

        cur.execute("SELECT id FROM profiles WHERE email = 'user@nova.ai'")
        if not cur.fetchone():
            std_id = "usr_standard_demo"
            cur.execute(
                """
                INSERT INTO profiles (id, email, username, password_hash, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'user', 1, ?, ?)
                """,
                (std_id, "user@nova.ai", "Aarav Sharma (Standard User)", hash_password("User@123"), now, now),
            )
            cur.execute(
                """
                INSERT INTO user_preferences (user_id, preferred_model, theme, language_pref, response_style, updated_at)
                VALUES (?, 'venom-pro-v1', 'dark', 'Hinglish', 'balanced', ?)
                """,
                (std_id, now),
            )

        # Ensure all existing users default to venom-pro-v1
        cur.execute("UPDATE user_preferences SET preferred_model = 'venom-pro-v1'")

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
            VALUES (?, 'venom-pro-v1', 'dark', 'Hinglish', 'balanced', ?)
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

        token = f"vnmsess_{secrets.token_urlsafe(32)}"
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
        daily_limit = int(row["setting_value"]) if row else 500

        today_prefix = datetime.utcnow().strftime("%Y-%m-%d")
        cur.execute(
            "SELECT COUNT(*) as cnt FROM usage_records WHERE user_id = ? AND created_at LIKE ?",
            (user_id, f"{today_prefix}%"),
        )
        used_today = cur.fetchone()["cnt"]
        conn.close()

        stats = {"used_today": used_today, "daily_limit": daily_limit, "remaining": max(0, daily_limit - used_today)}
        if used_today >= daily_limit:
            return False, f"Daily request limit reached ({used_today}/{daily_limit}).", stats
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
