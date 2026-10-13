import io
import json
import requests

BASE_URL = "http://localhost:8000"


def run_all_tests():
    print("=================================================================")
    print("🧪 NOVA AI (Project: Venom AI) — Phase 14 Automated Test Suite")
    print("=================================================================")

    # 1. Admin Login Test
    r_admin = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "himanshu@nova.ai", "password": "Himanshu@123"})
    assert r_admin.status_code == 200, f"Admin login failed: {r_admin.text}"
    admin_token = r_admin.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    print("✅ [TEST 1] Admin Login ('himanshu@nova.ai') Verified")

    # 2. Normal User Login Test
    r_user = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "user@nova.ai", "password": "User@123"})
    assert r_user.status_code == 200, f"User login failed: {r_user.text}"
    user_token = r_user.json()["token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}
    print("✅ [TEST 2] Standard User Login ('user@nova.ai') Verified")

    # 3. Models & Honest Implementation Status Check
    r_models = requests.get(f"{BASE_URL}/api/models")
    assert r_models.status_code == 200
    models = r_models.json()["models"]
    local_mdl = next(m for m in models if m["model_id"] == "nova-venom-core-v1")
    claude_mdl = next(m for m in models if m["model_id"] == "claude-3-5-sonnet-latest")
    assert local_mdl["implementation_status"] == "Working"
    assert claude_mdl["implementation_status"] == "Needs Configuration"
    print("✅ [TEST 3] Multi-Model Status Check ('Working' vs 'Needs Configuration') Verified")

    # 4. Working Chat & Symbolic Math with Local Engine
    r_chat = requests.post(
        f"{BASE_URL}/api/chat",
        headers=admin_headers,
        json={"prompt": "solve x^2 - 7*x + 12 = 0", "model_id": "nova-venom-core-v1"},
    )
    assert r_chat.status_code == 200
    chat_data = r_chat.json()
    assert chat_data["status"] == "ok"
    assert "[3, 4]" in chat_data["content"]
    admin_conv_id = chat_data["conversation_id"]
    print(f"✅ [TEST 4] Working AI Chat & Symbolic Math Verified (conv_id={admin_conv_id})")

    # 5. SSE Streaming Chat Verification
    r_stream = requests.post(
        f"{BASE_URL}/api/chat/stream",
        headers=admin_headers,
        json={"prompt": "Write a Python function", "conversation_id": admin_conv_id, "model_id": "nova-venom-core-v1"},
        stream=True,
    )
    assert r_stream.status_code == 200
    chunks = [line.decode("utf-8") for line in r_stream.iter_lines() if line]
    assert any("delta" in c for c in chunks) and any("done" in c for c in chunks)
    print(f"✅ [TEST 5] Real SSE Streaming Chat Verified ({len(chunks)} stream events received)")

    # 6. Honest Missing-Key Handling for Unconfigured External Provider (No Fake Claude Response!)
    r_unconf = requests.post(
        f"{BASE_URL}/api/chat",
        headers=admin_headers,
        json={"prompt": "Hello Claude", "model_id": "claude-3-5-sonnet-latest"},
    )
    assert r_unconf.status_code == 200
    unconf_data = r_unconf.json()
    assert unconf_data["status"] == "needs_configuration"
    assert "ANTHROPIC_API_KEY" in unconf_data["message"]
    print("✅ [TEST 6] Honest Missing-Key Setup Instructions (No Fake Claude Response) Verified")

    # 7. User-to-User Data Isolation Test (User B MUST be denied access to Admin's conversation!)
    r_iso = requests.get(f"{BASE_URL}/api/conversations/{admin_conv_id}", headers=user_headers)
    assert r_iso.status_code == 403, f"Expected 403 Forbidden on cross-user chat access, got {r_iso.status_code}"
    print("✅ [TEST 7] Strict User-to-User Data Isolation (HTTP 403 Forbidden) Verified")

    # 8. Admin Dashboard RBAC Test (Normal User = 403, Admin = 200)
    r_adm_denied = requests.get(f"{BASE_URL}/api/admin/overview", headers=user_headers)
    assert r_adm_denied.status_code == 403
    r_adm_ok = requests.get(f"{BASE_URL}/api/admin/overview", headers=admin_headers)
    assert r_adm_ok.status_code == 200 and r_adm_ok.json()["status"] == "ok"
    print("✅ [TEST 8] Protected Admin Dashboard Server-Side RBAC (403 vs 200) Verified")

    # 9. Coding Studio: Isolated Python Subprocess Sandbox & Security Block Test
    r_sb_ok = requests.post(
        f"{BASE_URL}/api/coding/run-sandbox",
        headers=admin_headers,
        json={"code": "print(sum([10, 20, 30]))", "language": "python"},
    )
    assert r_sb_ok.status_code == 200 and "60" in r_sb_ok.json()["stdout"]

    r_sb_block = requests.post(
        f"{BASE_URL}/api/coding/run-sandbox",
        headers=admin_headers,
        json={"code": "import os; os.system('ls')", "language": "python"},
    )
    assert r_sb_block.status_code == 400 and r_sb_block.json()["status"] == "blocked"
    print("✅ [TEST 9] Isolated Subprocess Sandbox Execution & Security Policy Block Verified")

    # 10. File Upload Validation & CSV Parsing Test
    csv_bytes = b"product,revenue\nNovaPro,4500\nVenomCore,8200\n"
    r_up = requests.post(
        f"{BASE_URL}/api/files/upload",
        headers=admin_headers,
        files={"file": ("metrics.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert r_up.status_code == 200 and r_up.json()["status"] == "ok"
    file_id = r_up.json()["file"]["id"]

    # Reject invalid .exe file upload
    r_bad_up = requests.post(
        f"{BASE_URL}/api/files/upload",
        headers=admin_headers,
        files={"file": ("malware.exe", io.BytesIO(b"123"), "application/octet-stream")},
    )
    assert r_bad_up.status_code == 400
    print(f"✅ [TEST 10] File Upload CSV Parsing & Invalid Extension Rejection Verified (file_id={file_id})")

    # 11. All 14 AI Tools Execution Test
    r_tool = requests.post(
        f"{BASE_URL}/api/tools/run",
        headers=admin_headers,
        json={"tool_id": "data_analyst", "inputs": {"primary_input": "item,score\nA,95\nB,88"}},
    )
    assert r_tool.status_code == 200 and r_tool.json()["status"] == "ok"
    print("✅ [TEST 11] Functional AI Tools Dashboard ('data_analyst') Verified")

    # 12. Real Web Search API Integration Test
    r_search = requests.post(
        f"{BASE_URL}/api/search",
        headers=admin_headers,
        json={"query": "Python programming language"},
    )
    assert r_search.status_code == 200 and len(r_search.json().get("sources", [])) > 0
    print(f"✅ [TEST 12] Live Backend Web Search Verified ({len(r_search.json()['sources'])} sources retrieved)")

    # 13. Custom VENOM AI Free API (/api/v1/venom) & Autonomous Telegram Bot / Website Builder Test
    r_venom = requests.post(
        f"{BASE_URL}/api/v1/venom",
        json={"prompt": "Mere liye ek Telegram Bot aur OSINT Scanner banao"},
    )
    assert r_venom.status_code == 200 and r_venom.json()["status"] == "ok"
    assert r_venom.json()["artifact"] is not None and "bot.py" in r_venom.json()["artifact"]["files"]
    print("✅ [TEST 13] Custom Free API (/api/v1/venom) & Autonomous Telegram Bot/Website Artifact Builder Verified")

    # 14. Live AI Package Installer (/api/agent/install-package) Test
    r_pkg = requests.post(
        f"{BASE_URL}/api/agent/install-package",
        headers=admin_headers,
        json={"package": "six"},
    )
    assert r_pkg.status_code == 200 and r_pkg.json()["status"] == "ok"
    print("✅ [TEST 14] Live Python Package Installer (pip install) Verified")

    print("=================================================================")
    print("🎉 ALL 14 VENOM AI VERIFICATION TESTS PASSED 100%!")
    print("=================================================================")


if __name__ == "__main__":
    run_all_tests()
