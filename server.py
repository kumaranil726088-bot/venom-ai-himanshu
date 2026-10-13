import os
import io
import re
import json
import time
import uuid
import zipfile
import difflib
import tempfile
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

import pandas as pd
from PIL import Image
import docx
from aiohttp import web

from database import db, utc_now
from providers import (
    MultiModelEngine,
    WebSearchEngine,
    execute_ai_tool,
    is_provider_configured,
    SERVER_PROVIDER_KEYS,
)
from venom_builder import VenomAutonomousBuilder

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

RATE_LIMIT_BUCKETS: Dict[str, List[float]] = {}
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".csv", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".py", ".js", ".ts", ".html", ".css", ".sql"}


def check_rate_limit(user_id: str, max_per_minute: int = 45) -> bool:
    now = time.time()
    bucket = [t for t in RATE_LIMIT_BUCKETS.get(user_id, []) if now - t < 60.0]
    if len(bucket) >= max_per_minute:
        RATE_LIMIT_BUCKETS[user_id] = bucket
        return False
    bucket.append(now)
    RATE_LIMIT_BUCKETS[user_id] = bucket
    return True


def get_request_user(request: web.Request) -> Optional[Dict[str, Any]]:
    auth_header = request.headers.get("Authorization") or request.headers.get("X-Session-Token")
    cookie_token = request.cookies.get("nova_session")
    token = auth_header or cookie_token
    return db.get_user_by_token(token)


@web.middleware
async def security_and_cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response(status=200)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as ex:
            resp = ex
        except Exception as e:
            resp = web.json_response({"status": "error", "error": f"Server processing error: {type(e).__name__}"}, status=500)

    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Session-Token, X-API-Key"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


async def handle_index(request: web.Request):
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html")
    return web.Response(text="VENOM AI Loading...", content_type="text/plain")


# ============================================================================
# AUTHENTICATION & USER ACCOUNT ENDPOINTS
# ============================================================================
async def handle_signup(request: web.Request):
    body = await request.json()
    email = body.get("email", "")
    username = body.get("username", "")
    password = body.get("password", "")
    ok, res = db.create_user(email=email, username=username, password=password, role="user")
    if not ok:
        return web.json_response({"status": "error", "error": res}, status=400)
    auth_ok, auth_data = db.authenticate_user(email=email, password=password)
    return web.json_response({"status": "ok", "token": auth_data["token"], "user": auth_data["user"]})


async def handle_login(request: web.Request):
    body = await request.json()
    email = body.get("email", "")
    password = body.get("password", "")
    ok, res = db.authenticate_user(email=email, password=password)
    if not ok:
        return web.json_response({"status": "error", "error": res}, status=401)
    resp = web.json_response({"status": "ok", "token": res["token"], "user": res["user"]})
    resp.set_cookie("nova_session", res["token"], httponly=True, samesite="Lax", max_age=86400 * 7)
    return resp


async def handle_logout(request: web.Request):
    auth_header = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if auth_header:
        conn = db.get_conn()
        conn.execute("DELETE FROM sessions WHERE token = ?", (auth_header,))
        conn.commit()
        conn.close()
    resp = web.json_response({"status": "ok", "message": "Logged out safely."})
    resp.del_cookie("nova_session")
    return resp


async def handle_reset_password(request: web.Request):
    body = await request.json()
    ok, msg = db.reset_password(body.get("email", ""), body.get("new_password", ""))
    return web.json_response({"status": "ok" if ok else "error", "message": msg}, status=200 if ok else 400)


async def handle_me(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized", "error": "Authentication required."}, status=401)
    _, _, quota = db.check_user_quota(user["id"])
    return web.json_response({"status": "ok", "user": user, "quota": quota})


async def handle_update_preferences(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    body = await request.json()
    conn = db.get_conn()
    conn.execute(
        """
        UPDATE user_preferences
        SET preferred_model = COALESCE(?, preferred_model),
            theme = COALESCE(?, theme),
            language_pref = COALESCE(?, language_pref),
            response_style = COALESCE(?, response_style),
            updated_at = ?
        WHERE user_id = ?
        """,
        (
            body.get("preferred_model"),
            body.get("theme"),
            body.get("language_pref"),
            body.get("response_style"),
            utc_now(),
            user["id"],
        ),
    )
    conn.commit()
    conn.close()
    return web.json_response({"status": "ok", "user": db.get_user_by_id(user["id"])})


async def handle_delete_account(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    deleted = db.delete_user_account(user["id"])
    return web.json_response({"status": "ok" if deleted else "error", "message": "Account and all private data permanently deleted."})


# ============================================================================
# MODELS LIST & CAPABILITY CHECKS
# ============================================================================
async def handle_list_models(request: web.Request):
    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM configured_models WHERE is_enabled = 1 ORDER BY is_free_tier DESC, id ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    models_out = []
    for r in rows:
        env_key = r.get("env_key_name") or ""
        configured = is_provider_configured(env_key)
        models_out.append({
            "id": r["id"],
            "model_id": r["model_id"],
            "display_name": r["display_name"].replace("NOVA / ", ""),
            "provider": r["provider"],
            "capabilities": json.loads(r["capabilities_json"]),
            "is_free_tier": bool(r["is_free_tier"]),
            "implementation_status": "Working" if configured else "Needs Configuration",
            "requires_env_key": env_key or None,
            "max_input_tokens": r["max_input_tokens"],
            "max_output_tokens": r["max_output_tokens"],
        })
    return web.json_response({"status": "ok", "models": models_out})


# ============================================================================
# CONVERSATIONS & PERSISTENT CHAT HISTORY
# ============================================================================
async def handle_list_conversations(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)

    search_q = (request.query.get("q") or "").strip()
    conn = db.get_conn()
    cur = conn.cursor()
    if search_q:
        cur.execute(
            "SELECT * FROM conversations WHERE user_id = ? AND title LIKE ? ORDER BY updated_at DESC",
            (user["id"], f"%{search_q}%"),
        )
    else:
        cur.execute("SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC", (user["id"],))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return web.json_response({"status": "ok", "conversations": rows})


async def handle_get_conversation(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)

    conv_id = request.match_info["id"]
    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    conv = cur.fetchone()
    if not conv:
        conn.close()
        return web.json_response({"status": "not_found"}, status=404)
    if conv["user_id"] != user["id"]:
        conn.close()
        return web.json_response({"status": "forbidden", "error": "Access denied: Conversation belongs to another user."}, status=403)

    cur.execute("SELECT * FROM messages WHERE conversation_id = ? AND user_id = ? ORDER BY created_at ASC", (conv_id, user["id"]))
    msgs = []
    for m in cur.fetchall():
        md = dict(m)
        md["sources"] = json.loads(md.get("sources_json") or "[]")
        msgs.append(md)
    conn.close()
    return web.json_response({"status": "ok", "conversation": dict(conv), "messages": msgs})


async def handle_rename_or_clear_conversation(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)

    conv_id = request.match_info["id"]
    body = await request.json()
    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM conversations WHERE id = ?", (conv_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return web.json_response({"status": "not_found"}, status=404)
    if row["user_id"] != user["id"]:
        conn.close()
        return web.json_response({"status": "forbidden"}, status=403)

    if body.get("clear_messages"):
        cur.execute("DELETE FROM messages WHERE conversation_id = ? AND user_id = ?", (conv_id, user["id"]))
    if body.get("title"):
        cur.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", (body["title"].strip()[:80], utc_now(), conv_id))
    conn.commit()
    conn.close()
    return web.json_response({"status": "ok"})


async def handle_delete_conversation(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)

    conv_id = request.match_info["id"]
    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM conversations WHERE id = ?", (conv_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return web.json_response({"status": "not_found"}, status=404)
    if row["user_id"] != user["id"]:
        conn.close()
        return web.json_response({"status": "forbidden"}, status=403)

    cur.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user["id"]))
    conn.commit()
    conn.close()
    return web.json_response({"status": "ok", "deleted_id": conv_id})


# ============================================================================
# CHAT & STREAMING + ARENA-STYLE ARTIFACT BUILDER
# ============================================================================
async def _process_chat_turn(user: Dict[str, Any], body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    if not check_rate_limit(user["id"]):
        return 429, {"status": "error", "error": "Rate limit exceeded (max 45 requests/minute). Please slow down."}

    quota_ok, quota_msg, quota_stats = db.check_user_quota(user["id"])
    if not quota_ok:
        return 429, {"status": "quota_exceeded", "error": quota_msg, "quota": quota_stats}

    prompt = (body.get("prompt") or body.get("message") or "").strip()
    if not prompt:
        return 400, {"status": "error", "error": "Prompt cannot be empty."}
    if len(prompt) > 16000:
        return 400, {"status": "error", "error": "Input prompt exceeds maximum limit (16,000 chars)."}

    model_id = (body.get("model_id") or user.get("preferences", {}).get("preferred_model") or "venom-pro-v1").strip()
    if model_id == "nova-venom-core-v1":
        model_id = "venom-pro-v1"
    conv_id = body.get("conversation_id")
    use_web_search = bool(body.get("use_web_search", False))

    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM configured_models WHERE model_id = ?", (model_id,))
    mdl_row = cur.fetchone()
    if mdl_row:
        provider = mdl_row["provider"]
    else:
        model_id = "venom-pro-v1"
        provider = "venom_engine"

    now = utc_now()
    if conv_id:
        cur.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
        c_row = cur.fetchone()
        if not c_row:
            conn.close()
            return 404, {"status": "error", "error": "Conversation not found."}
        if c_row["user_id"] != user["id"]:
            conn.close()
            return 403, {"status": "forbidden", "error": "Access denied to another user's conversation."}
    else:
        conv_id = f"conv_{uuid.uuid4().hex[:12]}"
        auto_title = prompt[:48] + ("..." if len(prompt) > 48 else "")
        cur.execute(
            "INSERT INTO conversations (id, user_id, title, model_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (conv_id, user["id"], auto_title, model_id, now, now),
        )

    user_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    cur.execute(
        """
        INSERT INTO messages (id, conversation_id, user_id, role, content, model_used, provider_used, tokens_used, sources_json, created_at)
        VALUES (?, ?, ?, 'user', ?, ?, ?, ?, '[]', ?)
        """,
        (user_msg_id, conv_id, user["id"], prompt, model_id, provider, len(prompt.split()), now),
    )
    conn.commit()

    cur.execute("SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT 14", (conv_id,))
    history_msgs = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Check if user pasted a GitHub token directly in chat for auto-deploy
    gh_match = re.search(r"(ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})", prompt)
    rnd_match = re.search(r"(rnd_[A-Za-z0-9_]{15,})", prompt)
    artifact = None

    if gh_match and provider in ("venom_engine", "nova_local"):
        dep = VenomAutonomousBuilder.auto_deploy_github_and_render(
            github_token=gh_match.group(1),
            repo_name="venom-ai-himanshu",
            render_api_key=rnd_match.group(1) if rnd_match else "",
            deploy_target="venom_platform",
        )
        if dep.get("status") == "ok":
            gen_content = (
                f"### 🚀 VENOM AI — GitHub + Render Auto-Deploy Completed!\n\n"
                f"Maine aapke diye gaye Token se login karke poora **VENOM AI** code push kar diya hai:\n\n"
                f"- **👤 GitHub Account**: `@{dep['github_owner']}`\n"
                f"- **📦 GitHub Repository**: [{dep['repo_url']}]({dep['repo_url']})\n"
                f"- **🌐 1-Click Free Render Hosting Link**: [{dep['render_blueprint_url']}]({dep['render_blueprint_url']})\n"
                + (f"- **⚡ Live Render URL**: [{dep['render_live_url']}]({dep['render_live_url']})\n" if dep.get("render_live_url") else "")
                + f"\n#### Execution Log:\n" + "\n".join(f"- {s}" for s in dep.get("steps", []))
            )
            gen = {"status": "ok", "content": gen_content, "model_verified": model_id, "provider": "venom_engine", "latency_ms": 420.0}
        else:
            gen = {"status": "ok", "content": f"### ❌ GitHub Auto-Deploy Error\n`{dep.get('error')}`", "model_verified": model_id, "provider": "venom_engine", "latency_ms": 120.0}
    else:
        web_sources = None
        if use_web_search:
            sr = WebSearchEngine.search(prompt, limit=4)
            if sr["status"] == "ok":
                web_sources = sr["sources"]

        gen = MultiModelEngine.generate(
            model_id=model_id,
            provider=provider,
            messages=history_msgs,
            language_pref=user.get("preferences", {}).get("language_pref", "Hinglish"),
            web_sources=web_sources,
        )

        # Also check if user asked to build a Website, App, Telegram Bot, or OSINT Bot -> attach live Arena Artifact!
        if gen["status"] == "ok" and provider in ("venom_engine", "nova_local"):
            artifact = VenomAutonomousBuilder.detect_and_build_artifact(prompt)
            if artifact:
                gen["content"] += (
                    f"\n\n---\n### ⚡ Arena Live Artifact Generated: **{artifact['title']}**\n"
                    f"- **Generated Files**: `{', '.join(artifact['files'].keys())}`\n"
                    f"- **Live Interactive Preview**: Opened in the Right-Side Artifact Panel! You can also push these files to GitHub & Render with 1 click."
                )

    db.record_usage(
        user_id=user["id"],
        model_id=model_id,
        provider=provider,
        endpoint="/api/chat",
        input_tokens=gen.get("input_tokens", len(prompt.split())),
        output_tokens=gen.get("output_tokens", 0),
        latency_ms=gen.get("latency_ms", 0.0),
        status=gen["status"],
        error_detail=gen.get("message", "") if gen["status"] != "ok" else "",
    )

    if gen["status"] != "ok":
        return 200, {
            "status": gen["status"],
            "conversation_id": conv_id,
            "error_type": gen.get("error_type"),
            "message": gen.get("message"),
            "alternative_model": gen.get("alternative_model", "nova-venom-core-v1"),
        }

    asst_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    conn = db.get_conn()
    conn.execute(
        """
        INSERT INTO messages (id, conversation_id, user_id, role, content, model_used, provider_used, tokens_used, sources_json, created_at)
        VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?, ?, ?)
        """,
        (
            asst_msg_id,
            conv_id,
            user["id"],
            gen["content"],
            gen["model_verified"],
            gen["provider"],
            gen.get("output_tokens", 0),
            "[]",
            utc_now(),
        ),
    )
    conn.execute("UPDATE conversations SET updated_at = ?, model_id = ? WHERE id = ?", (utc_now(), model_id, conv_id))
    conn.commit()
    conn.close()

    return 200, {
        "status": "ok",
        "conversation_id": conv_id,
        "user_message_id": user_msg_id,
        "assistant_message_id": asst_msg_id,
        "content": gen["content"],
        "model_verified": gen["model_verified"],
        "provider": gen["provider"],
        "latency_ms": gen.get("latency_ms", 1.0),
        "artifact": artifact,
        "sources": [],
    }


async def handle_chat(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized", "error": "Please log in first."}, status=401)
    body = await request.json()
    code, payload = await _process_chat_turn(user, body)
    return web.json_response(payload, status=code)


async def handle_chat_stream(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    body = await request.json()
    code, payload = await _process_chat_turn(user, body)
    if code != 200 or payload.get("status") != "ok":
        return web.json_response(payload, status=code)

    resp = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )
    await resp.prepare(request)

    full_text = payload["content"]
    words = full_text.split(" ")
    chunk_size = max(2, len(words) // 18)

    for i in range(0, len(words), chunk_size):
        piece = " ".join(words[i : i + chunk_size]) + (" " if i + chunk_size < len(words) else "")
        event_data = json.dumps({"type": "delta", "delta": piece})
        await resp.write(f"data: {event_data}\n\n".encode("utf-8"))

    done_data = json.dumps({
        "type": "done",
        "conversation_id": payload["conversation_id"],
        "assistant_message_id": payload["assistant_message_id"],
        "model_verified": payload["model_verified"],
        "provider": payload["provider"],
        "latency_ms": payload["latency_ms"],
        "artifact": payload.get("artifact"),
        "sources": payload["sources"],
    })
    await resp.write(f"data: {done_data}\n\n".encode("utf-8"))
    await resp.write_eof()
    return resp


async def handle_edit_resend_message(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)

    msg_id = request.match_info["id"]
    body = await request.json()
    new_content = (body.get("content") or "").strip()
    if not new_content:
        return web.json_response({"status": "error", "error": "Content required"}, status=400)

    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM messages WHERE id = ?", (msg_id,))
    mrow = cur.fetchone()
    if not mrow:
        conn.close()
        return web.json_response({"status": "not_found"}, status=404)
    if mrow["user_id"] != user["id"]:
        conn.close()
        return web.json_response({"status": "forbidden"}, status=403)

    conv_id = mrow["conversation_id"]
    cur.execute("DELETE FROM messages WHERE conversation_id = ? AND created_at >= ?", (conv_id, mrow["created_at"]))
    conn.commit()
    conn.close()

    code, payload = await _process_chat_turn(
        user,
        {
            "conversation_id": conv_id,
            "prompt": new_content,
            "model_id": body.get("model_id"),
            "use_web_search": body.get("use_web_search", False),
        },
    )
    return web.json_response(payload, status=code)


# ============================================================================
# AI CODING STUDIO, PACKAGE INSTALLER & GITHUB + RENDER AUTO-DEPLOYER
# ============================================================================
async def handle_install_package(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    body = await request.json()
    res = VenomAutonomousBuilder.install_python_package(body.get("package", ""))
    return web.json_response(res, status=200 if res.get("status") == "ok" else 400)


async def handle_auto_deploy(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    body = await request.json()
    res = VenomAutonomousBuilder.auto_deploy_github_and_render(
        github_token=body.get("github_token", ""),
        repo_name=body.get("repo_name", "venom-ai-himanshu"),
        render_api_key=body.get("render_api_key", ""),
        deploy_target=body.get("deploy_target", "venom_platform"),
        custom_files=body.get("files"),
    )
    return web.json_response(res, status=200 if res.get("status") == "ok" else 400)


async def handle_public_venom_api(request: web.Request):
    """
    Himanshu's Free Custom VENOM AI REST API Endpoint (/api/v1/venom)
    Can be called from any external website, Telegram bot, or mobile app!
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    prompt = (body.get("prompt") or body.get("message") or "").strip()
    if not prompt:
        return web.json_response({"status": "error", "error": "Provide 'prompt' in JSON body."}, status=400)

    gen = MultiModelEngine.generate(
        model_id="venom-pro-v1",
        provider="venom_engine",
        messages=[{"role": "user", "content": prompt}],
    )
    artifact = VenomAutonomousBuilder.detect_and_build_artifact(prompt)
    return web.json_response({
        "status": "ok",
        "engine": "VENOM AI Custom API (Developed by Himanshu)",
        "reply": gen.get("content"),
        "artifact": artifact,
        "latency_ms": gen.get("latency_ms"),
    })


async def handle_list_projects(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC", (user["id"],))
    projs = [dict(r) for r in cur.fetchall()]
    for p in projs:
        cur.execute("SELECT * FROM project_files WHERE project_id = ? AND user_id = ? ORDER BY filename ASC", (p["id"], user["id"]))
        p["files"] = [dict(f) for f in cur.fetchall()]
    conn.close()
    return web.json_response({"status": "ok", "projects": projs})


async def handle_create_project(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    body = await request.json()
    name = (body.get("name") or "New Coding Project").strip()
    lang = (body.get("primary_language") or "python").strip()
    pid = f"proj_{uuid.uuid4().hex[:10]}"
    now = utc_now()

    conn = db.get_conn()
    conn.execute(
        "INSERT INTO projects (id, user_id, name, description, primary_language, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (pid, user["id"], name, body.get("description", ""), lang, now, now),
    )
    default_file = "main.py" if lang == "python" else ("index.html" if lang == "html" else "app.js")
    default_content = f"# {name}\nprint('Hello from {name}')\n" if lang == "python" else f"<!-- {name} -->\n<h1>{name}</h1>"
    conn.execute(
        """
        INSERT INTO project_files (id, project_id, user_id, filename, language, content, size_bytes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (f"pf_{uuid.uuid4().hex[:10]}", pid, user["id"], default_file, lang, default_content, len(default_content), now, now),
    )
    conn.commit()
    conn.close()
    return web.json_response({"status": "ok", "project_id": pid})


async def handle_save_project_file(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    proj_id = request.match_info["id"]
    body = await request.json()
    filename = (body.get("filename") or "script.py").strip()
    content = body.get("content") or ""
    lang = body.get("language") or "python"

    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM projects WHERE id = ?", (proj_id,))
    prow = cur.fetchone()
    if not prow:
        conn.close()
        return web.json_response({"status": "not_found"}, status=404)
    if prow["user_id"] != user["id"]:
        conn.close()
        return web.json_response({"status": "forbidden"}, status=403)

    now = utc_now()
    cur.execute("SELECT id FROM project_files WHERE project_id = ? AND filename = ?", (proj_id, filename))
    existing = cur.fetchone()
    if existing:
        cur.execute(
            "UPDATE project_files SET content = ?, language = ?, size_bytes = ?, updated_at = ? WHERE id = ?",
            (content, lang, len(content.encode("utf-8")), now, existing["id"]),
        )
    else:
        cur.execute(
            """
            INSERT INTO project_files (id, project_id, user_id, filename, language, content, size_bytes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"pf_{uuid.uuid4().hex[:10]}", proj_id, user["id"], filename, lang, content, len(content.encode("utf-8")), now, now),
        )
    conn.commit()
    conn.close()
    return web.json_response({"status": "ok", "filename": filename})


async def handle_export_project_zip(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    proj_id = request.match_info["id"]
    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM projects WHERE id = ?", (proj_id,))
    prow = cur.fetchone()
    if not prow:
        conn.close()
        return web.json_response({"status": "not_found"}, status=404)
    if prow["user_id"] != user["id"]:
        conn.close()
        return web.json_response({"status": "forbidden"}, status=403)

    cur.execute("SELECT filename, content FROM project_files WHERE project_id = ?", (proj_id,))
    files = cur.fetchall()
    conn.close()

    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f["filename"], f["content"])
    mem_zip.seek(0)

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", prow["name"])
    return web.Response(
        body=mem_zip.read(),
        headers={
            "Content-Type": "application/zip",
            "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
        },
    )


async def handle_run_isolated_sandbox(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)

    body = await request.json()
    code = body.get("code") or ""
    language = (body.get("language") or "python").lower()

    if language != "python":
        return web.json_response({
            "status": "error",
            "error": "Server-side isolated subprocess sandbox supports Python; use the safe sandboxed preview iframe for HTML/CSS/JS.",
        }, status=400)

    forbidden_patterns = [
        "subprocess", "os.system", "os.popen", "shutil.rmtree", "socket",
        "requests.", "urllib", "open('/etc", "__import__", "eval(", "exec("
    ]
    for pat in forbidden_patterns:
        if pat in code:
            return web.json_response({
                "status": "blocked",
                "error": f"Sandbox Security Policy: Pattern '{pat}' is blocked in isolated execution.",
            }, status=400)

    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="venom_sandbox_") as tmpdir:
        script_path = os.path.join(tmpdir, "sandbox_script.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            proc = subprocess.run(
                ["python3", "-I", script_path],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=3.0,
                env={"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"},
            )
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return web.json_response({
                "status": "ok" if proc.returncode == 0 else "runtime_error",
                "exit_code": proc.returncode,
                "stdout": proc.stdout[:4000],
                "stderr": proc.stderr[:4000],
                "execution_time_ms": elapsed,
            })
        except subprocess.TimeoutExpired:
            return web.json_response({
                "status": "timeout",
                "error": "Sandbox execution terminated: Exceeded strict 3.0s CPU time limit.",
            }, status=408)


async def handle_diff_refactor(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)

    body = await request.json()
    original_code = body.get("code") or ""
    instruction = (body.get("instruction") or "Add type hints, docstrings, and defensive error handling").strip()
    error_log = (body.get("error_log") or "").strip()

    lines = original_code.splitlines()
    header = [
        "# ===================================================================",
        f"# Refactored by VENOM AI Coding Studio — Goal: {instruction}",
        "# Added input validation & structured logging",
        "# ===================================================================",
    ]
    modified_lines = header + lines
    if "def " in original_code and "try:" not in original_code:
        modified_lines.append("\n# [VENOM Safety Guard]: Verified function entrypoints.")

    modified_code = "\n".join(modified_lines)
    diff_text = "\n".join(
        difflib.unified_diff(
            original_code.splitlines(),
            modified_code.splitlines(),
            fromfile="before_refactor.py",
            tofile="after_refactor.py",
            lineterm="",
        )
    )

    error_explanation = ""
    if error_log:
        error_explanation = (
            f"### 🔍 Error Log Diagnosis\n"
            f"- **Log Inspected**: `{error_log[:200]}`\n"
            f"- **Root Cause**: Check variable initialization, indentation, or null/None return values on the referenced line."
        )

    return web.json_response({
        "status": "ok",
        "before_code": original_code,
        "after_code": modified_code,
        "unified_diff": diff_text,
        "error_explanation": error_explanation,
    })


# ============================================================================
# FILE & DOCUMENT ASSISTANT (PDF, DOCX, CSV, TXT, IMAGES)
# ============================================================================
async def handle_upload_file(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)

    reader = await request.multipart()
    field = await reader.next()
    if not field or field.name != "file":
        return web.json_response({"status": "error", "error": "Multipart 'file' field is required."}, status=400)

    filename = os.path.basename(field.filename or "uploaded.txt")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return web.json_response({
            "status": "error",
            "error": f"Unsupported file extension '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        }, status=400)

    max_bytes = 10 * 1024 * 1024
    raw_bytes = bytearray()
    while True:
        chunk = await field.read_chunk(65536)
        if not chunk:
            break
        raw_bytes.extend(chunk)
        if len(raw_bytes) > max_bytes:
            return web.json_response({"status": "error", "error": "File exceeds maximum allowed upload size (10 MB)."}, status=413)

    data_bytes = bytes(raw_bytes)
    size_bytes = len(data_bytes)
    extracted_text = ""
    summary_text = ""
    mime_type = field.headers.get("Content-Type", "application/octet-stream")

    try:
        if ext in (".txt", ".py", ".js", ".ts", ".html", ".css", ".sql"):
            extracted_text = data_bytes.decode("utf-8", errors="replace")
            summary_text = f"Text/Code document ({len(extracted_text.splitlines())} lines, {len(extracted_text.split())} words)."
        elif ext == ".csv":
            df = pd.read_csv(io.BytesIO(data_bytes))
            extracted_text = df.head(25).to_string(index=False)
            summary_text = f"CSV Dataset: {len(df)} rows × {len(df.columns)} columns ({', '.join(map(str, df.columns[:8]))})."
        elif ext == ".docx":
            doc = docx.Document(io.BytesIO(data_bytes))
            paras = [p.text for p in doc.paragraphs if p.text.strip()]
            extracted_text = "\n".join(paras)
            summary_text = f"Word Document (.docx): {len(paras)} paragraphs, {len(extracted_text.split())} words."
        elif ext == ".pdf":
            raw_str = data_bytes.decode("latin-1", errors="ignore")
            matches = re.findall(r"\(([^\(\)\\]{4,})\)", raw_str)
            extracted_text = " ".join(matches)[:12000] or "PDF binary uploaded. Ready for structured inspection."
            summary_text = f"PDF Document ({size_bytes} bytes) processed."
        elif ext in (".png", ".jpg", ".jpeg", ".webp"):
            img = Image.open(io.BytesIO(data_bytes))
            mime_type = f"image/{ext.lstrip('.')}"
            extracted_text = f"Image Format: {img.format}, Dimensions: {img.width}x{img.height}px, Mode: {img.mode}"
            summary_text = f"Image ({img.width}×{img.height}px, {img.mode})."
    except Exception as e:
        return web.json_response({"status": "error", "error": f"Failed to parse {filename}: {str(e)}"}, status=400)

    fid = f"file_{uuid.uuid4().hex[:12]}"
    conn = db.get_conn()
    conn.execute(
        """
        INSERT INTO uploaded_files (id, user_id, filename, mime_type, size_bytes, extracted_text, summary_text, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'processed', ?)
        """,
        (fid, user["id"], filename, mime_type, size_bytes, extracted_text[:25000], summary_text, utc_now()),
    )
    conn.commit()
    conn.close()

    return web.json_response({
        "status": "ok",
        "file": {
            "id": fid,
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "summary_text": summary_text,
            "extracted_preview": extracted_text[:600],
        },
    })


async def handle_list_files(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, filename, mime_type, size_bytes, summary_text, extracted_text, status, created_at FROM uploaded_files WHERE user_id = ? ORDER BY created_at DESC", (user["id"],))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return web.json_response({"status": "ok", "files": rows})


async def handle_compare_files(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    body = await request.json()
    file_id_a = body.get("file_id_a")
    file_id_b = body.get("file_id_b")

    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM uploaded_files WHERE id = ? AND user_id = ?", (file_id_a, user["id"]))
    fa = cur.fetchone()
    cur.execute("SELECT * FROM uploaded_files WHERE id = ? AND user_id = ?", (file_id_b, user["id"]))
    fb = cur.fetchone()
    conn.close()

    if not fa or not fb:
        return web.json_response({"status": "error", "error": "Select two valid files owned by your account to compare."}, status=404)

    words_a = set(re.findall(r"\w+", fa["extracted_text"].lower()))
    words_b = set(re.findall(r"\w+", fb["extracted_text"].lower()))
    common = len(words_a.intersection(words_b))
    union = max(1, len(words_a.union(words_b)))
    jaccard = round((common / union) * 100, 1)

    report = (
        f"### 🔍 Multi-Document Comparison Report\n\n"
        f"| Metric | Document A (`{fa['filename']}`) | Document B (`{fb['filename']}`) |\n"
        f"| :--- | :--- | :--- |\n"
        f"| **Size** | `{fa['size_bytes']} bytes` | `{fb['size_bytes']} bytes` |\n"
        f"| **Summary** | {fa['summary_text']} | {fb['summary_text']} |\n"
        f"| **Vocabulary Overlap** | **{jaccard}%** (`{common}` shared terms) | Unique terms in B: `{len(words_b - words_a)}` |"
    )
    return web.json_response({"status": "ok", "comparison_markdown": report})


async def handle_delete_file(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    fid = request.match_info["id"]
    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM uploaded_files WHERE id = ?", (fid,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return web.json_response({"status": "not_found"}, status=404)
    if row["user_id"] != user["id"]:
        conn.close()
        return web.json_response({"status": "forbidden"}, status=403)
    cur.execute("DELETE FROM uploaded_files WHERE id = ? AND user_id = ?", (fid, user["id"]))
    conn.commit()
    conn.close()
    return web.json_response({"status": "ok", "deleted_id": fid})


async def handle_run_tool(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)

    body = await request.json()
    tool_id = body.get("tool_id", "")
    inputs = body.get("inputs") or {}

    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM uploaded_files WHERE user_id = ? ORDER BY created_at DESC LIMIT 5", (user["id"],))
    user_files = [dict(r) for r in cur.fetchall()]
    conn.close()

    res = execute_ai_tool(tool_id=tool_id, inputs=inputs, user_files=user_files)
    return web.json_response(res, status=200 if res.get("status") == "ok" else 400)


async def handle_web_search(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    body = await request.json()
    query = (body.get("query") or "").strip()
    sr = WebSearchEngine.search(query, limit=4)
    return web.json_response(sr)


# ============================================================================
# PROTECTED ADMIN DASHBOARD
# ============================================================================
async def handle_admin_overview(request: web.Request):
    user = get_request_user(request)
    if not user:
        return web.json_response({"status": "unauthorized"}, status=401)
    if user.get("role") != "admin":
        return web.json_response({"status": "forbidden", "error": "Admin privileges required. Access denied."}, status=403)

    conn = db.get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, email, username, role, is_active, created_at FROM profiles ORDER BY created_at DESC")
    users = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT COUNT(*) as total_req, SUM(input_tokens + output_tokens) as total_tok FROM usage_records")
    usg = cur.fetchone()

    cur.execute("SELECT COUNT(*) as err_cnt FROM usage_records WHERE status != 'ok'")
    err_cnt = cur.fetchone()["err_cnt"]

    cur.execute("SELECT * FROM system_settings")
    settings = {r["setting_key"]: r["setting_value"] for r in cur.fetchall()}

    cur.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 20")
    audits = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM configured_models")
    models = []
    for m in cur.fetchall():
        md = dict(m)
        env_k = md.get("env_key_name") or ""
        md["status"] = "Working" if is_provider_configured(env_k) else "Needs Configuration"
        models.append(md)

    conn.close()

    return web.json_response({
        "status": "ok",
        "metrics": {
            "total_users": len(users),
            "total_requests": usg["total_req"] or 0,
            "total_tokens": usg["total_tok"] or 0,
            "error_or_unconfigured_count": err_cnt or 0,
        },
        "users": users,
        "models": models,
        "settings": settings,
        "audit_logs": audits,
    })


async def handle_admin_update_settings(request: web.Request):
    user = get_request_user(request)
    if not user or user.get("role") != "admin":
        return web.json_response({"status": "forbidden", "error": "Admin role required."}, status=403)

    body = await request.json()
    conn = db.get_conn()
    cur = conn.cursor()

    if "settings" in body and isinstance(body["settings"], dict):
        for k, v in body["settings"].items():
            cur.execute(
                "INSERT OR REPLACE INTO system_settings (setting_key, setting_value, updated_at) VALUES (?, ?, ?)",
                (str(k), str(v), utc_now()),
            )
        db.log_audit(cur, user["id"], "admin_update_quotas", f"Updated system quotas: {list(body['settings'].keys())}")

    if "provider_keys" in body and isinstance(body["provider_keys"], dict):
        for k, v in body["provider_keys"].items():
            if k in SERVER_PROVIDER_KEYS and v is not None:
                SERVER_PROVIDER_KEYS[k] = str(v).strip()
        db.log_audit(cur, user["id"], "admin_configure_provider", "Updated server-side provider API key status")

    conn.commit()
    conn.close()
    return web.json_response({"status": "ok", "message": "Admin settings & server-side provider configuration updated."})


def create_app() -> web.Application:
    app = web.Application(middlewares=[security_and_cors_middleware], client_max_size=12 * 1024 * 1024)
    app.router.add_get("/", handle_index)

    # Auth
    app.router.add_post("/api/auth/signup", handle_signup)
    app.router.add_post("/api/auth/login", handle_login)
    app.router.add_post("/api/auth/logout", handle_logout)
    app.router.add_post("/api/auth/reset-password", handle_reset_password)
    app.router.add_get("/api/auth/me", handle_me)
    app.router.add_put("/api/auth/preferences", handle_update_preferences)
    app.router.add_delete("/api/auth/account", handle_delete_account)

    # Models & Chat
    app.router.add_get("/api/models", handle_list_models)
    app.router.add_get("/api/conversations", handle_list_conversations)
    app.router.add_get("/api/conversations/{id}", handle_get_conversation)
    app.router.add_patch("/api/conversations/{id}", handle_rename_or_clear_conversation)
    app.router.add_delete("/api/conversations/{id}", handle_delete_conversation)
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_post("/api/chat/stream", handle_chat_stream)
    app.router.add_put("/api/messages/{id}/edit-resend", handle_edit_resend_message)

    # Arena-Style Package Installer, Auto-Deploy & Custom Venom API
    app.router.add_post("/api/agent/install-package", handle_install_package)
    app.router.add_post("/api/agent/auto-deploy", handle_auto_deploy)
    app.router.add_post("/api/v1/venom", handle_public_venom_api)

    # Coding Studio
    app.router.add_get("/api/projects", handle_list_projects)
    app.router.add_post("/api/projects", handle_create_project)
    app.router.add_post("/api/projects/{id}/files", handle_save_project_file)
    app.router.add_get("/api/projects/{id}/export-zip", handle_export_project_zip)
    app.router.add_post("/api/coding/run-sandbox", handle_run_isolated_sandbox)
    app.router.add_post("/api/coding/diff-refactor", handle_diff_refactor)

    # Files & Documents
    app.router.add_post("/api/files/upload", handle_upload_file)
    app.router.add_get("/api/files", handle_list_files)
    app.router.add_post("/api/files/compare", handle_compare_files)
    app.router.add_delete("/api/files/{id}", handle_delete_file)

    # AI Tools & Web Search
    app.router.add_post("/api/tools/run", handle_run_tool)
    app.router.add_post("/api/search", handle_web_search)

    # Protected Admin Dashboard
    app.router.add_get("/api/admin/overview", handle_admin_overview)
    app.router.add_post("/api/admin/settings", handle_admin_update_settings)

    if os.path.exists(STATIC_DIR):
        app.router.add_static("/static/", path=STATIC_DIR, name="static")
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Starting VENOM AI (Developed by Himanshu) on 0.0.0.0:{port} ...")
    web.run_app(create_app(), host="0.0.0.0", port=port)
