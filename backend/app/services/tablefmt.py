"""湖表格式管理业务规则：状态流转、字段校验与筛选口径都收在这里。

修复要点：
- 登记时完整保留分区字段、主键字段、排序字段与版本保留，不再只存三个基础字段；
- 状态只能按 草稿 -> 已创建 -> 已优化 -> 已废弃 顺序推进，草稿不允许跳过创建直接优化；
- 创建表前强校验分区字段、主键字段、版本保留，缺一项就拒绝，避免下游按错误字段建表；
- 创建表成功时生成同版本的表结构字段数据集，详情与下游字段目录共用同一份定义。
"""
from __future__ import annotations

from typing import Any

from app.services.fieldcheck import fieldcheck_service
from app.store import store

MODULE = "tablefmt"
# 登记时必须有的基础字段；结构字段允许登记为草稿，创建表前再强校验。
REQUIRED_FIELDS = ["配置编号", "表名称", "格式类型"]
# 结构字段：创建表（进入已创建）前必须齐全，保存时也要原样保留。
STRUCT_FIELDS = ["分区字段", "主键字段", "排序字段", "版本保留"]
CREATE_REQUIRED_FIELDS = ["分区字段", "主键字段", "版本保留"]
ALL_FIELDS = REQUIRED_FIELDS + STRUCT_FIELDS
STATUS_ORDER = ["草稿", "已创建", "已优化", "已废弃"]
# 动作 -> 允许执行该动作时配置必须处于的状态。
ACTION_RULES = {"创建表": "草稿", "优化表": "已创建", "废弃表": "已优化"}
NEGATIVE_ACTIONS = []


class TablefmtService:
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
                if keyword in str(row.get("配置编号", "")) or keyword in str(row.get("表名称", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            # 明细读取补齐数据集引用，保证详情页与下游字段目录指向同一版本。
            dataset = fieldcheck_service.current_dataset(str(entry.get("表名称", "")))
            entry = dict(entry)
            entry["当前数据集编号"] = dataset.get("数据集编号", "") if dataset else ""
        return entry

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        # 完整保留登记的结构字段，缺省也显式落为空串，杜绝“登记后字段丢失”。
        for field in ALL_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        entry["status"] = STATUS_ORDER[0]
        entry["配置状态"] = STATUS_ORDER[0]
        entry["当前数据集编号"] = ""
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """重新打开配置后保存：只允许在草稿态编辑，结构字段原样全量保留。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, ["记录不存在"]
        if entry.get("status") != STATUS_ORDER[0]:
            return None, [f"仅草稿状态可修改，当前状态为{entry.get('status')}"]
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or entry.get(field) or "").strip()]
        if missing:
            return None, missing
        for field in ALL_FIELDS:
            if field in values:
                entry[field] = str(values.get(field) or "").strip()
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"表格式配置 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于湖表格式管理可执行范围"
        required_status = ACTION_RULES[action]
        current_status = str(entry.get("status"))
        # 严格状态机：只能从指定前置状态推进，草稿不能跳过创建直接优化。
        if current_status != required_status:
            allowed = [name for name, pre in ACTION_RULES.items() if pre == current_status]
            hint = f"，当前可执行：{'、'.join(allowed)}" if allowed else ""
            return None, f"{action}要求配置处于{required_status}，当前为{current_status}{hint}"

        if action == "创建表":
            missing = [
                field
                for field in CREATE_REQUIRED_FIELDS
                if not str(entry.get(field) or "").strip()
            ]
            if missing:
                return None, f"创建表缺少结构字段：{'、'.join(missing)}，请补全后再创建，避免下游按错误字段建表"

        target = STATUS_ORDER[STATUS_ORDER.index(required_status) + 1]
        entry["status"] = target
        entry["配置状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS

        if action == "创建表":
            # 显式配置生成首版表结构字段数据集，下游字段目录沿用这一版本。
            dataset = fieldcheck_service.create_dataset_from_config(entry)
            entry["当前数据集编号"] = dataset["数据集编号"]
            fieldcheck_service.upsert_checklist(
                table=str(entry.get("表名称", "")),
                dataset=dataset,
                source="湖表格式管理",
                item="建表结构核对",
                result="通过",
                detail=(
                    f"已按显式配置建表：分区={dataset['分区字段'] or '—'}，"
                    f"主键={dataset['主键字段'] or '—'}，版本保留={dataset['版本保留'] or '—'}"
                ),
            )
        elif action == "优化表":
            fieldcheck_service.sync_business_result(
                source="湖表格式管理",
                table=str(entry.get("表名称", "")),
                item="表优化处理",
                detail=f"配置 {entry.get('配置编号')} 已完成表优化",
            )
        elif action == "废弃表":
            fieldcheck_service.sync_business_result(
                source="湖表格式管理",
                table=str(entry.get("表名称", "")),
                item="表废弃处理",
                detail=f"配置 {entry.get('配置编号')} 已废弃",
            )
        return entry, f"表格式配置已{action}"

    def refresh_fields(
        self,
        entry_id: int,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """刷新字段清单入口：冲突开新版本、无冲突补齐当前版本，结果回写核对清单。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"表格式配置 {entry_id} 不存在或已归档"
        if entry.get("status") == STATUS_ORDER[0]:
            return None, "草稿尚未创建表，没有可刷新的线上字段清单，请先执行创建表"
        dataset, message = fieldcheck_service.refresh_dataset(entry, values or {})
        if dataset is not None:
            entry["当前数据集编号"] = dataset["数据集编号"]
        return dataset, message
