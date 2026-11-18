"""端到端验证：字段保留、状态机、数据集版本、核对清单、目录版本边界（HTTP 版）。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"
ok = True


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode())


def check(name, cond, extra=""):
    global ok
    print(("PASS" if cond else "FAIL"), name, extra)
    if not cond:
        ok = False


r = call("POST", "/api/tablefmt", {"values": {
    "配置编号": "TABL-1001", "表名称": "lake.orders_e2e", "格式类型": "iceberg",
    "分区字段": "dt", "主键字段": "order_id", "排序字段": "updated_at", "版本保留": "30天"}})
check("登记成功", r["ok"], str(r))
entry = r["entry"]; eid = entry["id"]
check("分区字段保留", entry["分区字段"] == "dt")
check("主键字段保留", entry["主键字段"] == "order_id")
check("版本保留保留", entry["版本保留"] == "30天")
check("初始状态草稿", entry["status"] == "草稿")

r = call("POST", f"/api/tablefmt/{eid}/actions", {"values": {"action": "优化表"}})
check("草稿不能直接优化", not r["ok"], r["message"])
check("状态仍是草稿", call("GET", f"/api/tablefmt/{eid}")["status"] == "草稿")

r = call("POST", "/api/tablefmt", {"values": {
    "配置编号": "TABL-1002", "表名称": "lake.bad_e2e", "格式类型": "iceberg",
    "分区字段": "dt", "主键字段": "", "版本保留": "30天"}})
bad = r["entry"]
r2 = call("POST", f"/api/tablefmt/{bad['id']}/actions", {"values": {"action": "创建表"}})
check("缺主键拒绝建表", not r2["ok"], r2["message"])

r = call("POST", f"/api/tablefmt/{eid}/actions", {"values": {"action": "创建表"}})
check("创建表成功", r["ok"], str(r))
check("状态进入已创建", r["entry"]["status"] == "已创建")
ds_code = r["entry"]["当前数据集编号"]
check("生成数据集编号", bool(ds_code), ds_code)

detail = call("GET", f"/api/tablefmt/{eid}")
d = call("GET", f"/api/tablefmt/{eid}/datasets")
current = next(x for x in d["datasets"] if x["是否当前"])
check("详情与数据集分区一致", detail["分区字段"] == current["分区字段"] == "dt")
check("详情与数据集主键一致", detail["主键字段"] == current["主键字段"] == "order_id")
check("详情与数据集版本保留一致", detail["版本保留"] == current["版本保留"] == "30天")
check("同表只有一份当前", sum(1 for x in d["datasets"] if x["是否当前"]) == 1)
check("建表核对已入清单", any(x["核对项"] == "建表结构核对" for x in d["checklist"]))

r = call("POST", f"/api/tablefmt/{eid}/refresh", {"values": {"分区字段": "dt", "主键字段": "order_id"}})
check("无冲突刷新", r["ok"], r["message"])
check("无冲突不新增版本", r["entry"]["版本号"] == 1)

r = call("POST", f"/api/tablefmt/{eid}/refresh", {"values": {
    "分区字段": "dt,region", "主键字段": "order_id", "排序字段": "updated_at", "补充字段": "amount,status"}})
check("冲突刷新成功", r["ok"], r["message"])
v2 = r["entry"]
check("冲突生成v2", v2["版本号"] == 2 and v2["来源"] == "刷新字段清单")
check("v2有冲突说明", "分区字段" in v2["冲突说明"])
d = call("GET", f"/api/tablefmt/{eid}/datasets")
check("仍只有一份当前", sum(1 for x in d["datasets"] if x["是否当前"]) == 1)
check("当前是v2", next(x for x in d["datasets"] if x["是否当前"])["版本号"] == 2)
check("冲突核对进清单", any(x["核对项"] == "版本冲突核对" for x in d["checklist"]))
v2_id = v2["id"]

r = call("POST", f"/api/fieldcheck/datasets/{v2_id}/actions", {"values": {"action": "发布版本"}})
check("待确认不能跨级发布", not r["ok"], r["message"])
r = call("POST", f"/api/fieldcheck/datasets/{v2_id}/actions", {"values": {"action": "确认版本"}})
check("确认版本成功", r["ok"] and r["entry"]["版本状态"] == "已确认")
r = call("POST", f"/api/fieldcheck/datasets/{v2_id}/actions", {"values": {"action": "确认版本"}})
check("已确认不能重复确认(防回退)", not r["ok"], r["message"])
r = call("POST", f"/api/fieldcheck/datasets/{v2_id}/actions", {"values": {"action": "发布版本"}})
check("发布版本成功", r["ok"] and r["entry"]["版本状态"] == "已发布")

r = call("POST", "/api/catalog", {"values": {
    "作业编号": "CATA-9001", "源路径": "s3://x", "目标目录": "cat.legacy", "表名称": "lake.legacy_e2e"}})
legacy = r["entry"]
check("历史作业可登记", r["ok"])
r = call("POST", f"/api/catalog/{legacy['id']}/actions", {"values": {"action": "分区核对"}})
check("历史记录兼容不报错", r["ok"], r["message"])
cl = call("GET", "/api/fieldcheck/checklist?table=lake.legacy_e2e")
check("历史记录登记待核对", cl["total"] >= 1 and cl["items"][0]["核对结果"] == "待核对")

r = call("POST", "/api/catalog", {"values": {
    "作业编号": "CATA-9002", "源路径": "s3://x", "目标目录": "cat.pay",
    "表名称": "lake.payments", "数据集编号": "FD-0001"}})
check("禁止目录回退已归档版本", not r["ok"], r["message"])
r = call("POST", "/api/catalog", {"values": {
    "作业编号": "CATA-9003", "源路径": "s3://x", "目标目录": "cat.pay2",
    "表名称": "lake.payments", "数据集编号": "FD-0002", "线上分区": "dt,region"}})
pay = r["entry"]
check("当前版本可绑定", r["ok"])
r = call("POST", f"/api/catalog/{pay['id']}/actions", {"values": {"action": "分区核对"}})
check("线上分区核对一致", r["ok"] and "一致" in r["message"], r["message"])
r = call("POST", "/api/catalog", {"values": {
    "作业编号": "CATA-9004", "源路径": "s3://x", "目标目录": "cat.pay3",
    "表名称": "lake.payments", "数据集编号": "FD-0002", "线上分区": "dt"}})
pay3 = r["entry"]
r = call("POST", f"/api/catalog/{pay3['id']}/actions", {"values": {"action": "分区核对"}})
check("分区不一致被识别", r["ok"] and "不一致" in r["message"], r["message"])

via_table = call("GET", "/api/tablefmt/2/datasets")["checklist"]
via_list = call("GET", "/api/fieldcheck/checklist?table=lake.payments")["items"]
check("两入口清单同源", len(via_table) == len(via_list)
      and {x["id"] for x in via_table} == {x["id"] for x in via_list})

before = call("GET", "/api/fieldcheck/checklist?table=lake.payments")["total"]
call("POST", f"/api/catalog/{pay['id']}/actions", {"values": {"action": "分区核对"}})
after = call("GET", "/api/fieldcheck/checklist?table=lake.payments")["total"]
check("重复核对不产生重复记录", before == after, f"{before} -> {after}")

call("POST", "/api/iceberg/1/actions", {"values": {"action": "执行优化"}})
cl = call("GET", "/api/fieldcheck/checklist?table=" + urllib.parse.quote("表优化管理样例1"))
check("业务链路动作不报错(无匹配表则不写清单)", isinstance(cl, dict))

lst = call("GET", "/api/tablefmt")
draft = next(x for x in lst["items"] if x["status"] == "草稿")
r = call("PUT", f"/api/tablefmt/{draft['id']}", {"values": {
    "配置编号": draft["配置编号"], "表名称": draft["表名称"], "格式类型": draft["格式类型"],
    "分区字段": "dt,hh", "主键字段": draft["主键字段"], "排序字段": draft["排序字段"], "版本保留": "7天"}})
check("草稿可保存", r["ok"], str(r))
again = call("GET", f"/api/tablefmt/{draft['id']}")
check("保存后分区更新", again["分区字段"] == "dt,hh")
check("保存后版本保留更新", again["版本保留"] == "7天")
check("非草稿禁止修改", not call("PUT", f"/api/tablefmt/{eid}", {"values": {"版本保留": "1天"}})["ok"])

print("\nRESULT:", "ALL PASS" if ok else "HAS FAILURE")
raise SystemExit(0 if ok else 1)
