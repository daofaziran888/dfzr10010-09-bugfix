"""表结构字段数据集与字段核对清单接口。

面向下游字段目录与各业务链路：
- 数据集按表、按状态、按“是否当前”检索，详情包含完整字段清单与版本边界；
- 版本只能按确认顺序推进（待确认 -> 已确认 -> 已发布），不允许跳步或回退；
- 字段核对清单是表格式配置列表与字段详情两个入口共用的同一批结果。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.fieldcheck import (
    DATASET_ACTIONS,
    DATASET_STATUS_ORDER,
    fieldcheck_service,
)

router = APIRouter(prefix="/api/fieldcheck", tags=["表结构字段数据集"])


@router.get("/datasets", response_model=PageResult[dict])
def list_datasets(
    table: str | None = Query(default=None, description="按表名称过滤"),
    status: str | None = Query(default=None, description="待确认、已确认、已发布、已归档"),
    current_only: bool = Query(default=False, description="只看每张表当前生效的字段定义"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = fieldcheck_service.list_datasets(
        table=table, status=status, current_only=current_only, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: int) -> dict:
    dataset = fieldcheck_service.get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"表结构字段数据集 {dataset_id} 不存在")
    checklist, _ = fieldcheck_service.list_checklist(
        dataset_code=str(dataset.get("数据集编号", "")), page=1, size=10000
    )
    return {"dataset": dataset, "checklist": checklist}


@router.post("/datasets/{dataset_id}/actions", response_model=ActionResult)
def run_dataset_action(dataset_id: int, payload: EntryPayload) -> ActionResult:
    action = str(payload.values.get("action") or "").strip()
    if action not in DATASET_ACTIONS:
        return ActionResult(
            ok=False,
            message=f"动作「{action}」不支持，可选：{'、'.join(DATASET_ACTIONS.keys())}",
        )
    dataset, message = fieldcheck_service.run_dataset_action(dataset_id, action)
    if dataset is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=dataset)


@router.get("/statuses")
def dataset_statuses() -> dict:
    return {"status_order": DATASET_STATUS_ORDER, "actions": DATASET_ACTIONS}


@router.get("/checklist", response_model=PageResult[dict])
def list_checklist(
    table: str | None = Query(default=None, description="按表名称过滤"),
    dataset_code: str | None = Query(default=None, description="按数据集编号过滤"),
    source: str | None = Query(default=None, description="按来源模块过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = fieldcheck_service.list_checklist(
        table=table, dataset_code=dataset_code, source=source, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)
