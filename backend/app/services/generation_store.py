"""写侧：快照仓 + 世代指针。

唯一允许产生新世代的入口是 commit_new_generation。流程在单个事务内完成：
内存重算 -> 快照自洽校验 -> 锁考室 -> 取下一代号 -> 写一整代快照 -> 拨指针 -> 提交。

任何一步失败都整体回滚：不留世代号（世代号在事务内、从已提交行派生）、
不留半张方案（只有整代 JSON 落库）、指针不前移。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import Hall, SeatGeneration, SeatGenerationPointer
from app.services.seat_engine import (
    find_violations,
    place_candidates,
    plan_to_dict,
)


class SnapshotIntegrityError(RuntimeError):
    """快照三处数字（已座/未排/违规）对不齐，整场失败。"""


def _snapshot_is_consistent(snapshot: dict) -> bool:
    stats = snapshot.get("stats") or {}
    assignments = snapshot.get("assignments") or []
    unplaced = snapshot.get("unplaced") or []
    violations = snapshot.get("violations") or []
    return (
        stats.get("seated") == len(assignments)
        and stats.get("unplaced") == len(unplaced)
        and stats.get("violations") == len(violations)
        and stats.get("capacity") == snapshot.get("rows", 0) * snapshot.get("cols", 0)
    )


def build_snapshot(hall: Hall, candidates: list[dict]) -> dict:
    """纯内存重算，产生一整代快照草稿。不落库、不触指针。"""
    assigns, unplaced = place_candidates(hall.rows, hall.cols, hall.min_manhattan, candidates)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    snapshot = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
    snapshot["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    if not _snapshot_is_consistent(snapshot):
        raise SnapshotIntegrityError("排座结果自洽校验失败：已座/未排/违规数字对不齐")
    return snapshot


def commit_new_generation(db: Session, hall: Hall, candidates: list[dict]) -> dict:
    """成功排座 = 落下可区分的一代快照并把当前指针拨到这一代，单事务原子完成。

    返回带 generation 的快照。失败抛异常并保证无世代行、指针不动。
    """
    snapshot = build_snapshot(hall, candidates)
    try:
        # 锁考室行，串行化同一考室的世代号分配，避免两代同号。
        locked = db.scalars(select(Hall).where(Hall.id == hall.id).with_for_update()).first()
        if locked is None:
            raise SnapshotIntegrityError(f"考室 {hall.id} 在提交时消失")

        latest_gen = db.scalar(
            select(func.max(SeatGeneration.generation)).where(SeatGeneration.hall_id == hall.id)
        )
        next_gen = (latest_gen or 0) + 1
        snapshot["generation"] = next_gen

        row = SeatGeneration(
            hall_id=hall.id,
            generation=next_gen,
            created_at=datetime.utcnow(),
            snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        )
        db.add(row)
        db.flush()  # 半张方案到此仍在事务内，提交失败会整体回滚

        pointer = db.get(SeatGenerationPointer, hall.id)
        if pointer is None:
            pointer = SeatGenerationPointer(hall_id=hall.id, generation=next_gen)
            db.add(pointer)
        else:
            pointer.generation = next_gen
            pointer.updated_at = datetime.utcnow()

        db.commit()
    except Exception:
        db.rollback()
        raise
    return snapshot
