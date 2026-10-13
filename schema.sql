-- ============================================================================
-- NOVA AI (Project: Venom AI) — Complete Database Schema & Migrations (Phase 9)
-- Developed by Himanshu
-- Enforces strict foreign-key integrity and user-level data isolation policies.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- 1. PROFILES TABLE (Users & Roles: 'admin' | 'user')
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user', 'admin')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 2. SESSIONS TABLE (Server-Side Authenticated Sessions)
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);

-- 3. USER_PREFERENCES TABLE (Saved Model, Theme, Language & System Prompt)
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id TEXT PRIMARY KEY,
    preferred_model TEXT NOT NULL DEFAULT 'nova-venom-core-v1',
    theme TEXT NOT NULL DEFAULT 'dark' CHECK(theme IN ('dark', 'light')),
    language_pref TEXT NOT NULL DEFAULT 'Hinglish',
    response_style TEXT NOT NULL DEFAULT 'balanced',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);

-- 4. CONFIGURED_MODELS TABLE (Multi-Model Registry & Capabilities)
CREATE TABLE IF NOT EXISTS configured_models (
    id TEXT PRIMARY KEY,
    model_id TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    env_key_name TEXT,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    is_free_tier INTEGER NOT NULL DEFAULT 1,
    max_input_tokens INTEGER NOT NULL DEFAULT 4096,
    max_output_tokens INTEGER NOT NULL DEFAULT 2048,
    updated_at TEXT NOT NULL
);

-- 5. CONVERSATIONS TABLE (Isolated per user_id)
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    model_id TEXT NOT NULL DEFAULT 'nova-venom-core-v1',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at DESC);

-- 6. MESSAGES TABLE (Linked to conversation_id and user_id)
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    model_used TEXT,
    provider_used TEXT,
    tokens_used INTEGER DEFAULT 0,
    sources_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at ASC);

-- 7. PROJECTS TABLE (Phase 4: AI Coding Studio Multi-File Projects)
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    primary_language TEXT DEFAULT 'python',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id, updated_at DESC);

-- 8. PROJECT_FILES TABLE (Files belonging to a Coding Studio Project)
CREATE TABLE IF NOT EXISTS project_files (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'plaintext',
    content TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);

-- 9. UPLOADED_FILES TABLE (Phase 5: Private User Documents & Images)
CREATE TABLE IF NOT EXISTS uploaded_files (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    extracted_text TEXT DEFAULT '',
    summary_text TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'processed',
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);

-- 10. USAGE_RECORDS TABLE (Phase 10 & 11: Cost Control, Quotas & Telemetry)
CREATE TABLE IF NOT EXISTS usage_records (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL,
    error_detail TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_usage_user_date ON usage_records(user_id, created_at DESC);

-- 11. SYSTEM_SETTINGS TABLE (Server-Side Quotas & Feature Availability)
CREATE TABLE IF NOT EXISTS system_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 12. AUDIT_LOGS TABLE (Phase 12: Security & Admin Audit Trail)
CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
