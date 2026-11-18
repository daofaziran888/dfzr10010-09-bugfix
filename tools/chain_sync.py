"""验证其余业务链路动作正常，并把处理结果同步到字段核对清单。"""
import json, urllib.request
BASE = "http://127.0.0.1:8000"

def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())

# 先给 lake.events 准备一条可触发各模块的链路；lake.events 已有当前数据集 FD-0004
# 元数据服务：用表名称 lake.events 的记录不存在则登记
r = call("POST", "/api/metadata", {"values": {"表编号": "META-EVT", "表名称": "lake.events", "字段清单": "dt,event_id"}})
mid = r["entry"]["id"]
# 元数据状态机 草稿 -> 注册表
r = call("POST", f"/api/metadata/{mid}/actions", {"values": {"action": "注册表"}})
print("metadata 注册表:", r["ok"], r.get("message"))
assert r["ok"]

# 表优化 iceberg：登记目标 lake.events 并执行
r = call("POST", "/api/iceberg", {"values": {"任务编号": "ICEB-EVT", "表名称": "lake.events", "优化类型": "小文件合并"}})
iid = r["entry"]["id"]
r = call("POST", f"/api/iceberg/{iid}/actions", {"values": {"action": "执行优化"}})
print("iceberg 执行优化:", r["ok"], r.get("message"))
assert r["ok"]

# 表快照 snapshot
r = call("POST", "/api/snapshot", {"values": {"快照编号": "SNAP-EVT", "表名称": "lake.events", "快照时间": "2026-11-18"}})
sid = r["entry"]["id"]
r = call("POST", f"/api/snapshot/{sid}/actions", {"values": {"action": "创建快照"}})
print("snapshot 创建快照:", r["ok"], r.get("message"))
assert r["ok"]

# 数据回滚 rollback
r = call("POST", "/api/rollback", {"values": {"记录编号": "ROLL-EVT", "表名称": "lake.events", "回滚版本": "v3"}})
rid = r["entry"]["id"]
r = call("POST", f"/api/rollback/{rid}/actions", {"values": {"action": "执行回滚"}})
print("rollback 执行回滚:", r["ok"], r.get("message"))
assert r["ok"]

# 小文件合并 compact（目标表名）
r = call("POST", "/api/compact", {"values": {"任务编号": "COMP-EVT", "目标表名": "lake.events", "文件范围": "2026-11"}})
cid = r["entry"]["id"]
r = call("POST", f"/api/compact/{cid}/actions", {"values": {"action": "执行合并"}})
print("compact 执行合并:", r["ok"], r.get("message"))
assert r["ok"]

# 校验这些来源都进了同一份核对清单
cl = call("GET", "/api/fieldcheck/checklist?table=lake.events")["items"]
sources = sorted({x["来源模块"] for x in cl})
print("lake.events 核对清单来源模块:", sources)
for expect in ("元数据服务", "表优化管理", "表快照管理", "数据回滚恢复", "小文件合并"):
    assert expect in sources, f"缺少 {expect}"
    row = next(x for x in cl if x["来源模块"] == expect)
    assert row["数据集编号"] == "FD-0004", f"{expect} 未挂当前数据集版本"
print("每条结果都挂在当前数据集 FD-0004 上：OK")
print("\nCHAIN SYNC ALL PASS")
