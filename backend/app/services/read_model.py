"""读侧：世代读模型。

所有读取（排座图 / 违规列表 / 统计）都只从快照仓里的某一整代快照投影，
绝不使用现网最小距或现网名单重算。默认投影当前指针所指世代；按世代号
读取同样只回该代快照。

投影前强制校验快照内已座/未排/违规三份列表与 stats 的数字同源，对不齐即
抛 ReadModelInconsistent，由 API 把整场判为失败。
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import SeatGeneration, SeatGenerationPointer


class GenerationNotFoundError(LookupError):
    """指针不存在或该世代快照不存在（尚未成功排座）。"""


class ReadModelInconsistent(RuntimeError):
    """快照内三处数字对不齐，拒绝投影。"""


def _load_row(db: Session, hall_id: int, generation: int) -> SeatGeneration:
    row = db.scalars(
        select(SeatGeneration).where(
            SeatGeneration.hall_id == hall_id,
            SeatGeneration.generation == generation,
        )
    ).first()
    if row is None:
        raise GenerationNotFoundError(f"考室 {hall_id} 不存在世代 {generation}")
    return row


def _decode(row: SeatGeneration) -> dict:
    snapshot = json.loads(row.snapshot_json or "{}")
    assignments = snapshot.get("assignments") or []
    unplaced = snapshot.get("unplaced") or []
    violations = snapshot.get("violations") or []
    stats = snapshot.get("stats") or {}
    if not (
        stats.get("seated") == len(assignments)
        and stats.get("unplaced") == len(unplaced)
        and stats.get("violations") == len(violations)
        and stats.get("capacity") == snapshot.get("rows", 0) * snapshot.get("cols", 0)
        and snapshot.get("generation") == row.generation
    ):
        raise ReadModelInconsistent(
            f"考室 {row.hall_id} 世代 {row.generation} 快照已座/未排/违规数字对不上"
        )
    return snapshot


def current_generation_number(db: Session, hall_id: int) -> int:
    pointer = db.get(SeatGenerationPointer, hall_id)
    if pointer is None:
        raise GenerationNotFoundError(f"考室 {hall_id} 尚无排座世代指针")
    return pointer.generation


def get_current(db: Session, hall_id: int) -> dict:
    """投影指针所指世代（排座图/违规/统计共用这一份）。"""
    generation = current_generation_number(db, hall_id)
    return _decode(_load_row(db, hall_id, generation))


def get_by_generation(db: Session, hall_id: int, generation: int) -> dict:
    """按世代号读取：只回该代快照。纯读，不插新方案行、不动指针、不重算。"""
    return _decode(_load_row(db, hall_id, generation))


# --- 对同一份快照的三个只读投影，保证三处展示数字同源 ---

def project_map(snapshot: dict) -> dict:
    return {
        "generation": snapshot["generation"],
        "rows": snapshot["rows"],
        "cols": snapshot["cols"],
        "hall": snapshot.get("hall"),
        "assignments": snapshot["assignments"],
        # 与违规列表、统计同一套数字，便于三方对齐
        "seated": snapshot["stats"]["seated"],
        "unplaced_count": snapshot["stats"]["unplaced"],
        "violation_count": snapshot["stats"]["violations"],
    }


def project_violations(hall_id: int, snapshot: dict) -> dict:
    return {
        "hall_id": hall_id,
        "generation": snapshot["generation"],
        "violations": snapshot["violations"],
        "unplaced": snapshot["unplaced"],
    }


def project_stats(hall_id: int, snapshot: dict) -> dict:
    return {"hall_id": hall_id, **snapshot["stats"], "generation": snapshot["generation"]}
