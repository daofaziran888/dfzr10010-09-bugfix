import json, urllib.request
BASE = "http://127.0.0.1:8000"
def call(method, path, payload=None, raw=False):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE+path, data=data, method=method,
        headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read().decode())

# 无 body 的刷新（FastAPI optional body）
s, b = call("POST", "/api/tablefmt/2/refresh")
print("refresh no-body:", s, b.get("ok"), "|", b.get("message"))

# current_only 每表仅一条
s, b = call("GET", "/api/fieldcheck/datasets?current_only=true")
tables = [x["表名称"] for x in b["items"]]
print("current_only count:", b["total"], "tables:", tables, "unique:", len(tables)==len(set(tables)))

# 状态序列元数据
s, b = call("GET", "/api/fieldcheck/statuses")
print("statuses:", b["status_order"])

# overview 纳入新模块
s, b = call("GET", "/api/overview")
names = [m["name"] for m in b["modules"]]
print("overview has new modules:", "field_dataset" in names and "field_checklist" in names)

# 不存在的记录
s, b = call("GET", "/api/tablefmt/9999")
print("missing entry ->", s)
s, b = call("POST", "/api/tablefmt/9999/actions", {"values":{"action":"创建表"}})
print("missing action ->", s, b.get("ok"))

# 非法动作
s, b = call("POST", "/api/tablefmt/1/actions", {"values":{"action":"删库"}})
print("illegal action ->", b.get("ok"), b.get("message"))

# 数据集不存在
s, b = call("GET", "/api/fieldcheck/datasets/9999")
print("missing dataset ->", s)
print("EDGE DONE")
