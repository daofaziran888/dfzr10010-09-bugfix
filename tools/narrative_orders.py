"""按用户描述的 lake.orders 完整链路验证。"""
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

# 1. 用户登记 lake.orders（种子草稿即此配置）：dt / order_id / updated_at / 30天
lst = call("GET", "/api/tablefmt?keyword=lake.orders")["items"]
e = next(x for x in lst if x["表名称"] == "lake.orders")
print("① 登记配置：", {k: e[k] for k in ("表名称","分区字段","主键字段","排序字段","版本保留","status")})
assert (e["分区字段"], e["主键字段"], e["排序字段"], e["版本保留"]) == ("dt","order_id","updated_at","30天")

# 2. 草稿不能跳过创建直接优化
r = call("POST", f"/api/tablefmt/{e['id']}/actions", {"values": {"action": "优化表"}})
print("② 草稿直接优化被拦截：", r["ok"], "|", r["message"]); assert not r["ok"]

# 3. 创建表 -> 生成数据集
r = call("POST", f"/api/tablefmt/{e['id']}/actions", {"values": {"action": "创建表"}})
print("③ 创建表：", r["ok"], "| 状态", r["entry"]["status"], "| 数据集", r["entry"]["当前数据集编号"]); assert r["ok"]
ds_code = r["entry"]["当前数据集编号"]

# 4. 配置详情 与 下游字段目录 分区/主键/版本保留一致
detail = call("GET", f"/api/tablefmt/{e['id']}")
d = call("GET", f"/api/tablefmt/{e['id']}/datasets")
cur = next(x for x in d["datasets"] if x["是否当前"])
print("④ 详情：分区", detail["分区字段"], "主键", detail["主键字段"], "保留", detail["版本保留"])
print("   目录：分区", cur["分区字段"], "主键", cur["主键字段"], "保留", cur["版本保留"], "编号", cur["数据集编号"])
assert (detail["分区字段"], detail["主键字段"], detail["版本保留"]) == (cur["分区字段"], cur["主键字段"], cur["版本保留"])
assert cur["数据集编号"] == ds_code

# 5. 下游目录登记同步作业并分区核对
r = call("POST", "/api/catalog", {"values": {
    "作业编号": "CATA-ORD-1", "源路径": "s3://lake/orders", "目标目录": "lake_catalog.db.orders",
    "表名称": "lake.orders", "数据集编号": ds_code, "线上分区": "dt"}})
print("⑤ 目录作业登记：", r["ok"], "|", r["message"]); assert r["ok"]
job = r["entry"]
r = call("POST", f"/api/catalog/{job['id']}/actions", {"values": {"action": "分区核对"}})
print("   分区核对：", r["ok"], "|", r["message"]); assert r["ok"] and "一致" in r["message"]

# 6. 两个入口都指向字段核对清单同一批结果
a = call("GET", f"/api/tablefmt/{e['id']}/datasets")["checklist"]
b = call("GET", "/api/fieldcheck/checklist?table=lake.orders")["items"]
print("⑥ 配置详情入口清单数", len(a), "| 字段数据集入口清单数", len(b), "| 同源", {x['id'] for x in a} == {x['id'] for x in b})
assert {x['id'] for x in a} == {x['id'] for x in b}

# 7. 现在可以优化（状态正确推进）
r = call("POST", f"/api/tablefmt/{e['id']}/actions", {"values": {"action": "优化表"}})
print("⑦ 创建后优化：", r["ok"], "| 状态", r["entry"]["status"]); assert r["ok"] and r["entry"]["status"] == "已优化"

# 8. 目录禁止回退：尝试把新作业绑到已归档版本（lake.payments 的 FD-0001）
r = call("POST", "/api/catalog", {"values": {
    "作业编号": "CATA-ORD-2", "源路径": "x", "目标目录": "y",
    "表名称": "lake.payments", "数据集编号": "FD-0001"}})
print("⑧ 目录回退已发布版本被拦截：", r["ok"], "|", r["message"]); assert not r["ok"]

print("\nNARRATIVE ALL PASS")
