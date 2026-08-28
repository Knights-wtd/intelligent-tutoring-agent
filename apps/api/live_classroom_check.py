"""Live black-box check of classroom permissions against the running compose stack."""

import random
import string

import httpx

BASE = "http://127.0.0.1:8000"
SUFFIX = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {label}")
    else:
        FAIL += 1
        print(f"[FAIL] {label}  <- {detail}")


def register(name: str) -> httpx.Client:
    c = httpx.Client(base_url=BASE)
    r = c.post(
        "/api/v1/auth/register",
        json={
            "email": f"{name}@example.com",
            "username": name,
            "password": "Correct horse battery staple 9",
        },
    )
    assert r.status_code == 201, f"register {name}: {r.status_code} {r.text}"
    return c


owner = register(f"e2elive_o_{SUFFIX}")
teacher = register(f"e2elive_t_{SUFFIX}")
student = register(f"e2elive_s_{SUFFIX}")
student2 = register(f"e2elive_s2_{SUFFIX}")
outsider = register(f"e2elive_x_{SUFFIX}")


def uid(client: httpx.Client) -> str:
    return client.get("/api/v1/auth/me").json()["user"]["id"]


owner_id = uid(owner)
teacher_id = uid(teacher)
student_id = uid(student)
student2_id = uid(student2)

# --- unauthenticated access ---
anon = httpx.Client(base_url=BASE)
r = anon.get("/api/v1/classrooms/00000000-0000-0000-0000-000000000000")
check("未认证读班级 -> 401/403", r.status_code in (401, 403), f"got {r.status_code}")

# --- create classroom ---
r = owner.post("/api/v1/classrooms", json={"name": "实测班级"})
check("Owner 创建班级 (201)", r.status_code == 201, r.text)
classroom = r.json()
cid = classroom["id"]
space_id = classroom["space"]["id"]
check("创建者角色为 owner", classroom["membership"]["role"] == "owner")

# --- join flow ---
check("Teacher 用初始邀请码加入", teacher.post("/api/v1/classrooms/join", json={"code": classroom["invite_code"]}).status_code == 200)
check("同一邀请码已被消费 -> 拒绝", outsider.post("/api/v1/classrooms/join", json={"code": classroom["invite_code"]}).status_code in (403, 409))

r = owner.patch(f"/api/v1/classrooms/{cid}/members/{teacher_id}", json={"role": "teacher"})
check("Owner 提升 Teacher", r.status_code == 200 and r.json()["role"] == "teacher", r.text)

r = teacher.post(f"/api/v1/classrooms/{cid}/invites", json={"expires_in_hours": 1, "max_uses": 5})
check("Teacher 创建多人邀请码 (201)", r.status_code == 201, r.text)
multi_code = r.json()["code"]

check("Student1 加入", student.post("/api/v1/classrooms/join", json={"code": multi_code}).status_code == 200)
check("Student2 加入", student2.post("/api/v1/classrooms/join", json={"code": multi_code}).status_code == 200)
check("Student 重复加入 -> 409", student.post("/api/v1/classrooms/join", json={"code": multi_code}).status_code == 409)

for name, c in [("Owner", owner), ("Teacher", teacher), ("Student", student)]:
    check(f"{name} 可查看班级", c.get(f"/api/v1/classrooms/{cid}").status_code == 200)

# --- student restrictions ---
check("Student 改他人角色 -> 403", student.patch(f"/api/v1/classrooms/{cid}/members/{student2_id}", json={"role": "teacher"}).status_code == 403)
check("Student 自我提权 -> 403", student.patch(f"/api/v1/classrooms/{cid}/members/{student_id}", json={"role": "teacher"}).status_code == 403)
check("Student 踢人 -> 403", student.patch(f"/api/v1/classrooms/{cid}/members/{student2_id}", json={"remove": True}).status_code == 403)
check("Student 建邀请码 -> 403", student.post(f"/api/v1/classrooms/{cid}/invites", json={"expires_in_hours": 1, "max_uses": 1}).status_code == 403)

# --- teacher restrictions ---
check("Teacher 改角色 -> 403", teacher.patch(f"/api/v1/classrooms/{cid}/members/{student_id}", json={"role": "teacher"}).status_code == 403)
check("Teacher 踢人 -> 403", teacher.patch(f"/api/v1/classrooms/{cid}/members/{student_id}", json={"remove": True}).status_code == 403)

# --- outsider ---
check("局外人读班级 -> 404", outsider.get(f"/api/v1/classrooms/{cid}").status_code == 404)
check("局外人改成员 -> 403", outsider.patch(f"/api/v1/classrooms/{cid}/members/{student_id}", json={"role": "teacher"}).status_code == 403)
check("局外人建邀请码 -> 403", outsider.post(f"/api/v1/classrooms/{cid}/invites", json={"expires_in_hours": 1, "max_uses": 1}).status_code == 403)
check("无效邀请码 -> 403", outsider.post("/api/v1/classrooms/join", json={"code": "definitely-not-a-code"}).status_code == 403)

# --- owner management ---
check("Owner 踢出 Student2 -> 204", owner.patch(f"/api/v1/classrooms/{cid}/members/{student2_id}", json={"remove": True}).status_code == 204)
check("被移出的 Student2 读班级 -> 404", student2.get(f"/api/v1/classrooms/{cid}").status_code == 404)
check("Owner 改 Owner 自己角色 -> 403", owner.patch(f"/api/v1/classrooms/{cid}/members/{owner_id}", json={"role": "teacher"}).status_code == 403)

# --- invite exhaustion ---
r = teacher.post(f"/api/v1/classrooms/{cid}/invites", json={"expires_in_hours": 1, "max_uses": 1})
one_code = r.json()["code"]
third = register(f"e2elive_s3_{SUFFIX}")
check("第三人用单次邀请码加入", third.post("/api/v1/classrooms/join", json={"code": one_code}).status_code == 200)
fourth = register(f"e2elive_s4_{SUFFIX}")
check("次数用尽后再加入 -> 403", fourth.post("/api/v1/classrooms/join", json={"code": one_code}).status_code == 403)

# --- knowledge base permissions in classroom space ---
r = teacher.post(f"/api/v1/spaces/{space_id}/knowledge-bases", json={"name": "实测资料库"})
check("Teacher 建班级知识库 (201)", r.status_code == 201, r.text)
kb_id = r.json()["id"]
check("Owner 建班级知识库 (201)", owner.post(f"/api/v1/spaces/{space_id}/knowledge-bases", json={"name": "Owner库"}).status_code == 201)
check("Student 建知识库 -> 403", student.post(f"/api/v1/spaces/{space_id}/knowledge-bases", json={"name": "偷建"}).status_code == 403)
check("Student 列出班级知识库", student.get(f"/api/v1/spaces/{space_id}/knowledge-bases").status_code == 200)
check("Student 读班级知识库", student.get(f"/api/v1/knowledge-bases/{kb_id}").status_code == 200)
check("局外人读知识库 -> 404", outsider.get(f"/api/v1/knowledge-bases/{kb_id}").status_code == 404)
check("被移出的 Student2 读知识库 -> 404", student2.get(f"/api/v1/knowledge-bases/{kb_id}").status_code == 404)

files = {
    "file": ("tiny.txt", b"classroom live check", "text/plain"),
}
r = student.post(
    f"/api/v1/knowledge-bases/{kb_id}/documents",
    files=files,
    headers={"Idempotency-Key": f"e2elive-{SUFFIX}"},
)
check("Student 上传文档 -> 401/403", r.status_code in (401, 403), f"got {r.status_code}: {r.text[:200]}")

print(f"\n===== 线上实测: {PASS} 通过 / {FAIL} 失败 (用户后缀 {SUFFIX}) =====")
raise SystemExit(1 if FAIL else 0)
