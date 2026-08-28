"""Full-chain live verification: tutor chat + candidate generation + confirm + graph."""

import random
import string
import time

import httpx

BASE = "http://127.0.0.1:8000"
SUFFIX = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {label}", flush=True)
    else:
        FAIL += 1
        print(f"[FAIL] {label}  <- {detail}", flush=True)


c = httpx.Client(base_url=BASE, timeout=120)
r = c.post(
    "/api/v1/auth/register",
    json={
        "email": f"chain_{SUFFIX}@example.com",
        "username": f"chain_{SUFFIX}",
        "password": "Correct horse battery staple 9",
    },
)
assert r.status_code == 201, r.text

# 1. tutor status
status = c.get("/api/v1/tutor/status").json()
check("tutor status configured=true", status.get("configured") is True, str(status))

# 2. KB + upload
space_id = c.get("/api/v1/auth/me").json()["personal_space"]["id"]
kb = c.post(f"/api/v1/spaces/{space_id}/knowledge-bases", json={"name": "全链路验证库"}).json()
kb_id = kb["id"]

marker = f"链路验证标记{SUFFIX}"
content = (
    "# 第3章 移动无线传播\n\n"
    "## 3.1 路径损耗\n\n"
    f"路径损耗（{marker}）描述电磁波在自由空间传播时功率的衰减，"
    "常用对数模型表示为 P_r(d)=P_t-L(d)。\n\n"
    "## 3.2 相干带宽\n\n"
    "相干带宽与多径时延扩展成反比，是衡量频率选择性的重要参数。"
    "路径损耗在链路预算中被反复使用。\n"
)
r = c.post(
    f"/api/v1/knowledge-bases/{kb_id}/documents",
    files={"file": ("wireless.md", content.encode("utf-8"), "text/markdown")},
    headers={"Idempotency-Key": f"chain-{SUFFIX}"},
)
check("上传文档 (201)", r.status_code == 201, r.text[:300])
version_id = r.json()["document_version_id"]

# 3. wait until searchable (search hit = parse + index done)
deadline = time.time() + 90
ready = False
while time.time() < deadline:
    r = c.post(f"/api/v1/knowledge-bases/{kb_id}/search", json={"query": marker, "limit": 3})
    if r.status_code == 200 and r.json().get("results"):
        ready = True
        break
    time.sleep(4)
check("检索命中(文档可搜索)", ready, r.text[:200])

# 4. AI tutor chat (real Faro call)
r = c.post(
    f"/api/v1/knowledge-bases/{kb_id}/tutor/conversations",
    json={"prompt": "根据资料，什么是路径损耗？请用一句话回答。"},
)
check("AI 家教对话 (201)", r.status_code == 201, f"{r.status_code} {r.text[:300]}")
if r.status_code == 201:
    messages = r.json().get("messages", [])
    answer = messages[-1]["content"] if messages else ""
    citations = messages[-1].get("citations", []) if messages else []
    print(f"       回答: {answer[:140]}")
    print(f"       引用数: {len(citations)}")

# 5. candidate generation (real Faro markdown pipeline)
r = c.post(
    f"/api/v1/knowledge-bases/{kb_id}/candidate-batches",
    json={"document_version_id": version_id},
    headers={"Idempotency-Key": f"cand-{SUFFIX}"},
)
check("发起候选生成 (202)", r.status_code == 202, f"{r.status_code} {r.text[:300]}")
batch_id = r.json()["id"]

# 6. poll batch state (real LLM calls take a while)
deadline = time.time() + 300
b = {}
state = None
while time.time() < deadline:
    b = c.get(f"/api/v1/knowledge-bases/{kb_id}/candidate-batches/{batch_id}").json()
    state = b.get("state")
    if state in ("needs_review", "failed"):
        break
    time.sleep(8)
check(
    f"候选进入待审核 (state={state})",
    state == "needs_review",
    f"failure_code={b.get('failure_code')}",
)
if state == "needs_review":
    notes = b.get("notes", [])
    links = b.get("links", [])
    print(f"       候选笔记 {len(notes)} 条, 链接 {len(links)} 条")
    for n in notes[:6]:
        print(f"       - [{n['kind']}] {n['title']}")

    # 7. confirm all
    r = c.post(
        f"/api/v1/knowledge-bases/{kb_id}/candidate-batches/{batch_id}/confirm",
        json={
            "accepted_note_ids": [n["id"] for n in notes],
            "accepted_link_ids": [l["id"] for l in links],
        },
    )
    check("确认候选批次 (200)", r.status_code == 200, f"{r.status_code} {r.text[:300]}")

# 8. graph should now have nodes
g = c.get(f"/api/v1/knowledge-bases/{kb_id}/graph").json()
check(
    f"链路图有内容 (nodes={len(g.get('nodes', []))}, edges={len(g.get('edges', []))})",
    len(g.get("nodes", [])) > 0,
    str(g)[:200],
)
for node in g.get("nodes", [])[:5]:
    print(f"       图节点: [{node['kind']}] {node['title']}")

print(f"\n===== 全链路: {PASS} 通过 / {FAIL} 失败 (后缀 {SUFFIX}) =====")
raise SystemExit(1 if FAIL else 0)
