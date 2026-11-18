"""表结构字段数据集与字段核对清单领域规则。

这里集中管理三件事，避免字段定义在各模块里各存一份、互相对不上：

1. 表结构字段数据集（field_dataset）：同一张表的字段定义按版本留存，
   来源分「显式配置」（湖表格式登记）与「刷新字段清单」（线上刷新）两类，
   版本只能按 待确认 -> 已确认 -> 已发布 的顺序推进，发布后只归档不回退。
2. 当前字段定义：每张表只有一个 ``是否当前=True`` 的数据集，下游字段目录
   永远读这一份，杜绝同一张表出现两套互相冲突的当前定义。
3. 字段核对清单（field_checklist）：数据目录分区校验、其余业务链路的处理
   结果都按（表 + 数据集版本 + 来源模块 + 核对项）归集到同一条清单记录，
   表格式配置列表与字段详情两个入口看到的永远是同一批结果。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

DATASET_MODULE = "field_dataset"
CHECKLIST_MODULE = "field_checklist"

DATASET_STATUS_ORDER = ["待确认", "已确认", "已发布", "已归档"]
# 数据集版本只允许沿确认顺序推进，禁止跳步、禁止回退。
DATASET_ACTIONS = {"确认版本": "已确认", "发布版本": "已发布"}

CHECK_PENDING = "待核对"
CHECK_MATCH = "一致"
CHECK_MISMATCH = "不一致"
CHECK_PASS = "通过"
CHECK_ERROR = "异常"

CONFIG_SOURCE = "显式配置"
REFRESH_SOURCE = "刷新字段清单"

# 显式配置与刷新清单冲突时，用这几个角色做比对。
ROLE_PARTITION = "分区"
ROLE_PRIMARY = "主键"
ROLE_SORT = "排序"
ROLE_NORMAL = "普通"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def split_terms(value: Any) -> list[str]:
    """把 ``dt,region`` / ``dt，region`` / ``dt;region`` 统一拆成有序字段名列表。"""
    text = _clean(value)
    if not text:
        return []
    for separator in ("，", ";", "；", "|", " "):
        text = text.replace(separator, ",")
    return [term.strip() for term in text.split(",") if term.strip()]


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


def _next_code(rows: list[dict[str, Any]], prefix: str, code_field: str) -> str:
    max_seq = 0
    for row in rows:
        code = str(row.get(code_field, ""))
        if code.startswith(prefix):
            tail = code[len(prefix):]
            if tail.isdigit():
                max_seq = max(max_seq, int(tail))
    return f"{prefix}{max_seq + 1:04d}"


def build_field_list(
    *,
    partition: Any = None,
    primary: Any = None,
    sort: Any = None,
    extra: Any = None,
) -> list[dict[str, str]]:
    """按分区/主键/排序字段生成一份完整、去重且角色可追溯的字段清单。

    刷新接口没带字段时也用它兜底，保证数据集里永远是完整字段而不是半截清单。
    """
    roles: dict[str, str] = {}
    for name in split_terms(partition):
        roles.setdefault(name, ROLE_PARTITION)
    for name in split_terms(primary):
        roles.setdefault(name, ROLE_PRIMARY)
    for name in split_terms(sort):
        roles.setdefault(name, ROLE_SORT)
    for name in split_terms(extra):
        roles.setdefault(name, ROLE_NORMAL)
    return [
        {"字段名": name, "字段类型": "string", "字段角色": role}
        for name, role in roles.items()
    ]


def _snapshot(entry: dict[str, Any]) -> dict[str, str]:
    """从表格式配置里抽出结构字段，保证数据集与登记配置同源。"""
    return {
        "分区字段": _clean(entry.get("分区字段")),
        "主键字段": _clean(entry.get("主键字段")),
        "排序字段": _clean(entry.get("排序字段")),
        "版本保留": _clean(entry.get("版本保留")),
    }


class FieldcheckService:
    # ------------------------------------------------------------------ 数据集
    def list_datasets(
        self,
        *,
        table: str | None = None,
        status: str | None = None,
        current_only: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(DATASET_MODULE)
        if table:
            rows = [row for row in rows if row.get("表名称") == table]
        if status:
            rows = [row for row in rows if row.get("版本状态") == status]
        if current_only:
            rows = [row for row in rows if row.get("是否当前")]
        rows = sorted(rows, key=lambda row: (str(row.get("表名称", "")), int(row.get("版本号", 0))))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_dataset(self, dataset_id: int) -> dict[str, Any] | None:
        return store.find(DATASET_MODULE, dataset_id)

    def get_dataset_by_code(self, dataset_code: str) -> dict[str, Any] | None:
        for row in store.rows(DATASET_MODULE):
            if row.get("数据集编号") == dataset_code:
                return row
        return None

    def current_dataset(self, table: str) -> dict[str, Any] | None:
        """下游字段目录唯一允许读取的当前字段定义。"""
        for row in store.rows(DATASET_MODULE):
            if row.get("表名称") == table and row.get("是否当前"):
                return row
        return None

    def _datasets_of(self, table: str) -> list[dict[str, Any]]:
        return [
            row
            for row in store.rows(DATASET_MODULE)
            if row.get("表名称") == table
        ]

    def create_dataset_from_config(self, entry: dict[str, Any]) -> dict[str, Any]:
        """创建表成功后由显式配置生成首个表结构字段数据集（v1，待确认）。"""
        rows = store.rows(DATASET_MODULE)
        table = _clean(entry.get("表名称"))
        snapshot = _snapshot(entry)
        dataset = {
            "id": _next_id(rows),
            "数据集编号": _next_code(rows, "FD-", "数据集编号"),
            "表名称": table,
            "版本号": 1,
            "来源": CONFIG_SOURCE,
            "关联配置编号": _clean(entry.get("配置编号")),
            "字段清单": build_field_list(
                partition=snapshot["分区字段"],
                primary=snapshot["主键字段"],
                sort=snapshot["排序字段"],
            ),
            **snapshot,
            "版本状态": DATASET_STATUS_ORDER[0],
            "是否当前": True,
            "冲突说明": "",
            "创建时间": _now(),
            "status": DATASET_STATUS_ORDER[0],
            "pending": True,
            "abnormal": False,
        }
        rows.append(dataset)
        return dataset

    def refresh_dataset(
        self,
        entry: dict[str, Any],
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """刷新字段清单：冲突时开新版本，无冲突时原地补齐，保证只有一份当前定义。"""
        values = values or {}
        table = _clean(entry.get("表名称"))
        existing = self.current_dataset(table)
        if existing is None:
            return None, f"表 {table} 尚未创建，缺少可刷新的表结构字段数据集"

        # 完全没带线上字段时不做任何派生，避免凭空造出残留/重复版本。
        structural_keys = ("分区字段", "主键字段", "排序字段", "补充字段", "字段清单")
        if not any(_clean(values.get(key)) for key in structural_keys):
            return existing, "未提供线上字段清单，保持当前数据集版本不变"

        snapshot = _snapshot(entry)
        online_partition = _clean(values.get("分区字段")) or snapshot["分区字段"]
        online_primary = _clean(values.get("主键字段")) or snapshot["主键字段"]
        online_sort = _clean(values.get("排序字段")) or snapshot["排序字段"]
        refreshed_fields = values.get("字段清单")
        if isinstance(refreshed_fields, list) and refreshed_fields:
            field_list = [
                item if isinstance(item, dict) else {"字段名": _clean(item), "字段类型": "string", "字段角色": ROLE_NORMAL}
                for item in refreshed_fields
            ]
        else:
            field_list = build_field_list(
                partition=online_partition,
                primary=online_primary,
                sort=online_sort,
                extra=values.get("补充字段"),
            )

        conflict_terms: list[str] = []
        if online_partition and online_partition != existing.get("分区字段"):
            conflict_terms.append(
                f"分区字段：显式配置={existing.get('分区字段') or '—'}，刷新清单={online_partition}"
            )
        if online_primary and online_primary != existing.get("主键字段"):
            conflict_terms.append(
                f"主键字段：显式配置={existing.get('主键字段') or '—'}，刷新清单={online_primary}"
            )

        same_shape = (
            not conflict_terms
            and field_list == existing.get("字段清单")
            and online_sort == existing.get("排序字段")
        )
        if same_shape:
            # 内容完全一致时不造新版本，避免重复显示和残留变更。
            return existing, "刷新字段清单与当前数据集一致，无需生成新版本"

        rows = store.rows(DATASET_MODULE)
        if not conflict_terms and existing.get("版本状态") == DATASET_STATUS_ORDER[0]:
            # 当前版本还没确认且无冲突：原地补齐完整字段，不新增版本。
            existing["字段清单"] = field_list
            existing["排序字段"] = online_sort
            existing["冲突说明"] = ""
            existing["创建时间"] = _now()
            return existing, "已在当前版本补齐刷新后的完整字段清单"

        # 有冲突（或当前版本已确认/发布）：开新版本并接管“当前”身份，
        # 老版本保留可追溯，但同表永远只有一个是否当前=True。
        old_current = existing
        old_current["是否当前"] = False
        old_current["pending"] = old_current.get("版本状态") not in ("已发布", "已归档")
        version_no = max(int(row.get("版本号", 0)) for row in self._datasets_of(table)) + 1
        dataset = {
            "id": _next_id(rows),
            "数据集编号": _next_code(rows, "FD-", "数据集编号"),
            "表名称": table,
            "版本号": version_no,
            "来源": REFRESH_SOURCE,
            "关联配置编号": _clean(entry.get("配置编号")),
            "字段清单": field_list,
            "分区字段": online_partition,
            "主键字段": online_primary,
            "排序字段": online_sort,
            "版本保留": snapshot["版本保留"],
            "版本状态": DATASET_STATUS_ORDER[0],
            "是否当前": True,
            "冲突说明": "；".join(conflict_terms),
            "创建时间": _now(),
            "status": DATASET_STATUS_ORDER[0],
            "pending": True,
            "abnormal": bool(conflict_terms),
        }
        rows.append(dataset)
        if conflict_terms:
            self.upsert_checklist(
                table=table,
                dataset=dataset,
                source="湖表格式管理",
                item="版本冲突核对",
                result=CHECK_PENDING,
                detail="检测到显式配置与刷新字段清单版本冲突：" + "；".join(conflict_terms),
            )
            return dataset, "检测到版本冲突，已生成新数据集版本并等待确认：" + "；".join(conflict_terms)
        return dataset, f"已基于刷新字段清单生成 v{version_no} 数据集版本"

    def run_dataset_action(self, dataset_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        dataset = self.get_dataset(dataset_id)
        if dataset is None:
            return None, f"表结构字段数据集 {dataset_id} 不存在"
        if action not in DATASET_ACTIONS:
            return None, f"动作「{action}」不属于表结构字段数据集可执行范围"
        target = DATASET_ACTIONS[action]
        current_idx = DATASET_STATUS_ORDER.index(dataset["版本状态"])
        target_idx = DATASET_STATUS_ORDER.index(target)
        if target_idx <= current_idx:
            return None, f"数据集版本只能按确认顺序推进，{dataset['版本状态']} 不能执行{action}"
        if target_idx != current_idx + 1:
            return None, f"数据集版本不能跨级流转，需先完成「{DATASET_STATUS_ORDER[current_idx + 1]}」"
        dataset["版本状态"] = target
        dataset["status"] = target
        dataset["pending"] = target not in ("已发布", "已归档")
        dataset["abnormal"] = False
        if target == "已发布":
            # 一张表只保留一份当前可追溯定义：新发布版本接管，旧发布版归档。
            for row in self._datasets_of(str(dataset["表名称"])):
                if row["id"] != dataset["id"] and row.get("版本状态") == "已发布":
                    row["版本状态"] = "已归档"
                    row["status"] = "已归档"
                    row["pending"] = False
                    row["是否当前"] = False
        self.upsert_checklist(
            table=str(dataset["表名称"]),
            dataset=dataset,
            source="湖表格式管理",
            item="版本状态核对",
            result=CHECK_PASS,
            detail=f"数据集 {dataset['数据集编号']} 已推进至{target}",
        )
        return dataset, f"数据集 {dataset['数据集编号']} 已{action}"

    # ------------------------------------------------------------------ 核对清单
    def list_checklist(
        self,
        *,
        table: str | None = None,
        dataset_code: str | None = None,
        source: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(CHECKLIST_MODULE)
        if table:
            rows = [row for row in rows if row.get("表名称") == table]
        if dataset_code:
            rows = [row for row in rows if row.get("数据集编号") == dataset_code]
        if source:
            rows = [row for row in rows if row.get("来源模块") == source]
        rows = sorted(rows, key=lambda row: int(row.get("id", 0)))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def upsert_checklist(
        self,
        *,
        table: str,
        dataset: dict[str, Any] | None,
        source: str,
        item: str,
        result: str,
        detail: str,
        online_partition: str = "",
    ) -> dict[str, Any]:
        """按（表 + 数据集版本 + 来源模块 + 核对项）归集结果，重复处理只更新不新增。"""
        rows = store.rows(CHECKLIST_MODULE)
        dataset_code = str(dataset.get("数据集编号", "")) if dataset else ""
        version_no = int(dataset.get("版本号", 0)) if dataset else 0
        for row in rows:
            if (
                row.get("表名称") == table
                and row.get("数据集编号") == dataset_code
                and row.get("来源模块") == source
                and row.get("核对项") == item
            ):
                row["核对结果"] = result
                row["明细"] = detail
                row["线上分区"] = online_partition
                row["数据集分区"] = str(dataset.get("分区字段", "")) if dataset else ""
                row["处理时间"] = _now()
                row["status"] = result
                row["abnormal"] = result in (CHECK_MISMATCH, CHECK_ERROR)
                row["pending"] = result == CHECK_PENDING
                return row

        entry = {
            "id": _next_id(rows),
            "核对编号": _next_code(rows, "CHK-", "核对编号"),
            "表名称": table,
            "数据集编号": dataset_code,
            "版本号": version_no,
            "来源模块": source,
            "核对项": item,
            "线上分区": online_partition,
            "数据集分区": str(dataset.get("分区字段", "")) if dataset else "",
            "核对结果": result,
            "明细": detail,
            "处理时间": _now(),
            "status": result,
            "pending": result == CHECK_PENDING,
            "abnormal": result in (CHECK_MISMATCH, CHECK_ERROR),
        }
        rows.append(entry)
        return entry

    def verify_online_partition(
        self,
        *,
        table: str,
        source: str,
        online_partition: str,
        item: str = "线上表分区核对",
        allow_legacy: bool = False,
    ) -> tuple[dict[str, Any] | None, str]:
        """用当前数据集的分区信息校验线上表，结果同步到字段核对清单。"""
        dataset = self.current_dataset(table)
        if dataset is None:
            # 历史记录兼容：老链路可能没有数据集，先登记一条待核对而不是直接报错。
            entry = self.upsert_checklist(
                table=table,
                dataset=None,
                source=source,
                item=item,
                result=CHECK_PENDING if allow_legacy else CHECK_ERROR,
                detail=("历史记录未关联表结构字段数据集，已兼容登记，待补齐数据集后复核"
                        if allow_legacy else f"表 {table} 缺少当前表结构字段数据集，无法校验线上表"),
                online_partition=online_partition,
            )
            return entry, ("历史记录已兼容登记" if allow_legacy else f"表 {table} 缺少表结构字段数据集")
        expected = str(dataset.get("分区字段", ""))
        actual = _clean(online_partition) or expected
        if actual == expected:
            result, detail = CHECK_MATCH, f"线上表分区 {actual} 与数据集 {dataset['数据集编号']} 分区 {expected} 一致"
        else:
            result, detail = CHECK_MISMATCH, f"线上表分区 {actual} 与数据集 {dataset['数据集编号']} 分区 {expected} 不一致"
        entry = self.upsert_checklist(
            table=table,
            dataset=dataset,
            source=source,
            item=item,
            result=result,
            detail=detail,
            online_partition=actual,
        )
        return entry, detail

    def sync_business_result(
        self,
        *,
        source: str,
        table: str,
        item: str,
        detail: str,
        result: str = CHECK_PASS,
    ) -> dict[str, Any]:
        """其余业务链路处理完后把结果同步到核对清单，并挂到当前数据集版本上。"""
        dataset = self.current_dataset(_clean(table))
        return self.upsert_checklist(
            table=_clean(table),
            dataset=dataset,
            source=source,
            item=item,
            result=result,
            detail=detail,
        )

    def assert_version_usable_by_catalog(self, table: str, dataset_code: str) -> tuple[dict[str, Any] | None, str]:
        """目录模块版本边界校验：禁止回退到已归档/非当前的已发布版本。"""
        target = self.get_dataset_by_code(dataset_code)
        if target is None:
            return None, f"数据集版本 {dataset_code} 不存在"
        if target.get("表名称") != table:
            return None, f"数据集 {dataset_code} 不属于表 {table}"
        if target.get("版本状态") == "已归档" or not target.get("是否当前"):
            current = self.current_dataset(table)
            current_code = current.get("数据集编号") if current else "—"
            return None, (
                f"数据集 {dataset_code} 已不是当前版本（当前为 {current_code}），"
                "目录模块禁止回退已发布版本"
            )
        return target, "ok"


fieldcheck_service = FieldcheckService()
