"""数据目录同步业务规则：状态流转、字段校验与筛选口径都收在这里。

目录模块（下游字段目录）与表结构字段数据集的联动规则：
- 先兼容历史记录：老同步作业没有关联数据集时不直接失败，登记一条待核对清单；
- 再核对版本边界：只允许使用当前数据集版本，禁止回退已发布/已归档版本；
- 用当前数据集的分区信息校验线上表，执行结果同步到字段核对清单；
- 作业状态只能按 草稿 -> 同步中 -> 已完成 -> 已暂停 顺序推进。
"""
from __future__ import annotations

from typing import Any

from app.services.fieldcheck import CHECK_ERROR, CHECK_MATCH, fieldcheck_service
from app.store import store

MODULE = "catalog"
REQUIRED_FIELDS = ["作业编号", "源路径", "目标目录"]
# 关联湖表名称：目录模块据此找到当前字段定义，没填时按历史记录兼容处理。
OPTIONAL_FIELDS = ["表名称", "同步模式", "增量字段", "过滤规则", "同步频率", "线上分区", "数据集编号"]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
STATUS_ORDER = ["草稿", "同步中", "已完成", "已暂停"]
ACTION_RULES = {"启动同步": "草稿", "暂停同步": "同步中", "归档作业": "已暂停"}
# 额外的数据集联动动作。
VERIFY_ACTION = "分区核对"
NEGATIVE_ACTIONS = []


class CatalogService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("作业编号", "")) or keyword in str(row.get("表名称", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            entry = dict(entry)
            table = str(entry.get("表名称", ""))
            if table:
                current = fieldcheck_service.current_dataset(table)
                entry["当前数据集编号"] = current.get("数据集编号", "") if current else ""
        return entry

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ALL_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        # 登记时若指定了数据集，先做版本边界校验，禁止挂到已回退的版本上。
        table = entry["表名称"]
        dataset_code = entry["数据集编号"]
        if table and dataset_code:
            _, message = fieldcheck_service.assert_version_usable_by_catalog(table, dataset_code)
            if message != "ok":
                return None, [message]
        entry["status"] = STATUS_ORDER[0]
        entry["作业状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"同步作业 {entry_id} 不存在或已归档"

        if action == VERIFY_ACTION:
            return self._verify_partition(entry)

        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据目录同步可执行范围"
        required_status = ACTION_RULES[action]
        current_status = str(entry.get("status"))
        if current_status != required_status:
            allowed = [name for name, pre in ACTION_RULES.items() if pre == current_status]
            hint = f"，当前可执行：{'、'.join(allowed)}" if allowed else ""
            return None, f"{action}要求作业处于{required_status}，当前为{current_status}{hint}"

        target = STATUS_ORDER[STATUS_ORDER.index(required_status) + 1]
        entry["status"] = target
        entry["作业状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS

        table = str(entry.get("表名称", ""))
        if action == "启动同步" and table:
            # 启动同步即对线上表做一次分区核对，结果进同一份字段核对清单。
            self._verify_partition(entry)
        if table:
            fieldcheck_service.sync_business_result(
                source="数据目录同步",
                table=table,
                item=f"同步作业{action}",
                detail=f"作业 {entry.get('作业编号')} 执行{action}，状态推进至{target}",
            )
        return entry, f"同步作业已{action}"

    def _verify_partition(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        table = str(entry.get("表名称", "")).strip()
        if not table:
            return None, "该同步作业未关联湖表（表名称为空），无法进行分区核对"

        # 版本边界：显式指定数据集时，禁止目录模块回退已发布版本。
        dataset_code = str(entry.get("数据集编号", "")).strip()
        if dataset_code:
            target, message = fieldcheck_service.assert_version_usable_by_catalog(table, dataset_code)
            if target is None:
                fieldcheck_service.upsert_checklist(
                    table=table,
                    dataset=None,
                    source="数据目录同步",
                    item="线上表分区核对",
                    result=CHECK_ERROR,
                    detail=message,
                )
                return None, message

        online_partition = str(entry.get("线上分区", "")).strip()
        # 历史记录兼容：没有当前数据集时不抛链路错误，先登记待核对。
        result, message = fieldcheck_service.verify_online_partition(
            table=table,
            source="数据目录同步",
            online_partition=online_partition,
            allow_legacy=True,
        )
        if result is not None and result.get("核对结果") == CHECK_MATCH:
            entry["abnormal"] = False
        elif result is not None:
            entry["abnormal"] = result.get("核对结果") not in ("待核对", CHECK_MATCH)
        return entry, message
