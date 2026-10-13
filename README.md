# ⚡ NOVA AI (Project: Venom AI) — Complete A–Z Multi-Model AI Platform
**Developed by Himanshu**

A full-stack, mobile-responsive, multi-model AI platform featuring a Claude-style dark violet-blue interface, real relational database (`SQLite` with foreign-key cascade & strict row-level user isolation), session authentication with RBAC (`admin` / `user`), SSE streaming chat, isolated Python coding sandbox, multi-format document processor (`.pdf`, `.docx`, `.csv`, `.txt`, images), 14 specialized AI workflows, verified web search citations, and a protected Admin dashboard.

---

## 📊 Implementation Status Matrix (Final Build Rules Compliance)

| Phase | Feature / Subsystem | Status | Notes / Configuration Details |
| :--- | :--- | :--- | :--- |
| **Phase 1** | **Premium Dark Violet-Blue UI, Light/Dark Mode & Mobile Layout** | **Working** | Responsive sidebar, `"What can we build today?"` hero, Markdown tables, code copy buttons, skeleton loaders |
| **Phase 2** | **Built-in Local Engine (`nova-venom-core-v1`)** | **Working** | 100% functional out-of-the-box (`SymPy` math, code synthesis, document Q&A, Hindi/Hinglish/English) |
| **Phase 2** | **Anthropic Claude API (`claude-3-5-sonnet-latest`)** | **Needs Configuration** | Real HTTP adapter implemented (`providers.py`); requires server-side `ANTHROPIC_API_KEY` in `.env` or Admin Dashboard. Shows honest setup instructions when key is missing |
| **Phase 2** | **Google Gemini API (`gemini-2.5-flash`)** | **Needs Configuration** | Real HTTP adapter implemented (`providers.py`); requires server-side `GEMINI_API_KEY` |
| **Phase 2** | **OpenRouter API (`llama-3.3-70b-instruct:free`, `qwen-2.5-coder:free`)** | **Needs Configuration** | Real HTTP adapter implemented (`providers.py`); requires server-side `OPENROUTER_API_KEY` |
| **Phase 3** | **Advanced Chat System (SSE Streaming, History, Edit/Resend, Stop)** | **Working** | Auto-titles, search, rename, delete, clear, edit & resend, stop streaming (`AbortController`), regenerate |
| **Phase 4** | **AI Coding Studio (Multi-file, Diff View, ZIP Export, Isolated Sandbox)** | **Working** | Subprocess sandbox with `-I` isolation & strict 3.0s CPU timeout; unified diff refactoring; `.zip` download |
| **Phase 5** | **File & Document Assistant (PDF, DOCX, CSV, TXT, Images)** | **Working** | Validates size (`<= 10MB`) & extensions; parses via `python-docx`, `pandas`, `Pillow`; multi-doc comparison; private per-user scoping |
| **Phase 5** | **Deep Multimodal Pixel Image Vision Q&A** | **Needs Configuration** | Local image metadata/dimensions extraction is **Working**; deep pixel vision Q&A routes through vision-capable providers (`Claude 3.5 Sonnet` / `Gemini 2.5 Flash`) once their API key is set |
| **Phase 6** | **14 AI Tools Dashboard** | **Working** | All 14 workflows (`AI Writer`, `Coding Assistant`, `Code Debugger`, `PDF Assistant`, `Summarizer`, `Translator`, `Study Assistant`, `Data Analyst`, `Brainstorming`, `Project Planner`, `Image Understanding`, `Web Research`, `Email Drafting`, `Report Generator`) connected to `/api/tools/run` |
| **Phase 7** | **Web Search & Research (`/api/search`)** | **Working** | Retrieves real sources from Wikipedia Open Search API & DuckDuckGo Instant Answer API; separates retrieved source snippets from AI synthesis with numbered `[1](url)` links |
| **Phase 8** | **Login, Signup, Logout, Password Reset & User Isolation** | **Working** | PBKDF2-HMAC-SHA256 salted password hashes, session tokens, account deletion, strict `user_id` ownership checks (`HTTP 403` on cross-user access) |
| **Phase 9** | **Database Schema & Migrations (`schema.sql`)** | **Working** | All 8 core tables (`profiles`, `conversations`, `messages`, `projects`, `project_files`, `user_preferences`, `usage_records`, `configured_models`) + `sessions`, `uploaded_files`, `system_settings`, `audit_logs` |
| **Phase 10** | **Secure Backend REST & Streaming API (`server.py`)** | **Working** | Input validation, rate limiting (45 req/min), timeouts, safe error handling, server-only secrets |
| **Phase 11** | **Free Tier & Cost Control Quotas** | **Working** | Per-user daily request limits, max upload size (10MB), token tracking, quota exhaustion messaging |
| **Phase 11** | **Paid Subscription Billing (Stripe/Razorpay)** | **Not Implemented** | Kept optional per Phase 11 rules ("Paid plans optional rakho; payment integration tabhi add karo jab properly configured ho") |
| **Phase 12** | **Protected Admin Dashboard (`/api/admin/*`)** | **Working** | Mandatory server-side `role == 'admin'` verification (`HTTP 403` for normal users), usage metrics, audit logs, quota & provider key management |
| **Phase 13** | **Security, Privacy & Provider Data Retention Documentation** | **Working** | Documented below; HTML/Markdown sanitized; no secrets logged |

---

## 🔒 Provider Data-Retention & Privacy Policy Notice (Phase 13)

1. **Local Engine (`nova-venom-core-v1`)**: 100% of prompts, conversations, and uploaded files remain inside your private server database (`nova_venom.db`) and are never transmitted to any third party.
2. **Free-Tier External Providers (OpenRouter Free Models / Google Gemini Free Tier)**:
   - **Important Warning**: Free-tier external API providers may log or retain prompts and uploaded document snippets to train or improve their models. **Do NOT upload confidential, regulated, personal financial, or proprietary files when routing requests to free external API tiers.** Use paid zero-data-retention (ZDR) endpoints or the built-in `nova-venom-core-v1` local engine for confidential documents.

---

## 🚀 Setup, Database Migration & Deployment Instructions (Phase 14)

### 1. Environment Configuration
```bash
cd /home/user/nova_ai
cp .env.example .env
# Optional: Add your ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY in .env
```

### 2. Initialize Database & Run Migrations
The SQLite schema (`schema.sql`) is automatically applied on server startup, or you can run:
```bash
python3 -c "from database import db; print('Database initialized at:', db.db_path)"
```

### 3. Start the Production Server
```bash
python3 server.py
```
The server listens on `http://0.0.0.0:8000`.

### 4. Run the Automated End-to-End Test Suite
```bash
python3 test_suite.py
```
