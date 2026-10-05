"""排座的写路径与读路径。

写路径拆成三处,各司其职:
- SeatGeneration 快照仓:只增不改,每次成功排座落一代完整快照(自包含,渲染不依赖现网名单);
- SeatPointer    世代指针:每考室一行,只在成功事务里拨到最新一代;
- SeatReadModel  读模型:排座图/违规/统计共用的投影,与指针同代、同事务重建。

铁律:
- 失败的一次不留世代号、不留半张方案、指针不前移(单事务,异常即整体回滚);
- 读旧世代只回快照原文,与"用现网最小距或现网名单重算旧世代"互斥——本模块的
  快照读取路径绝不调用排座引擎,也绝不为了渲染旧世代去 join 现网考生/考室表;
- 按世代编号读取是纯读:不插入新方案行,也不改指针;
- 排座图、违规、统计只展示指针所指世代的同一套数字,读模型与指针错位即整场失败。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import Candidate, Hall, SeatGeneration, SeatPointer, SeatReadModel
from app.services.seat_engine import find_violations, place_candidates, plan_to_dict


class HallNotFoundError(Exception):
    """考室不存在。"""

class SeatingFailedError(Exception):
    """排座失败:本次不得留下任何世代痕迹。"""

class ReadModelMisalignedError(Exception):
    """读模型与世代指针对不齐:整场失败,不得凑合展示。"""


# ---------- 写路径 ----------

def _compute_result(db: Session, hall: Hall) -> tuple[dict, int]:
    """调引擎算方案,返回 (结果字典, 应排考生总数)。不落库。"""
    cands = [
        {"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
        for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall.id)).all()
    ]
    assigns, unplaced = place_candidates(hall.rows, hall.cols, hall.min_manhattan, cands)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    return result, len(cands)


def _assert_consistent(result: dict, roster_size: int) -> None:
    """落库前自校验:已座/未排/违规三套数字对不齐,整场失败。"""
    stats = result["stats"]
    seats = {(a["row"], a["col"]) for a in result["assignments"]}
    rows, cols = result["rows"], result["cols"]
    problems = []
    if stats["seated"] != len(result["assignments"]):
        problems.append("已座数与方案行数不符")
    if stats["unplaced"] != len(result["unplaced"]):
        problems.append("未排数与未排名单不符")
    if stats["violations"] != len(result["violations"]):
        problems.append("违规数与违规明细不符")
    if stats["capacity"] != rows * cols:
        problems.append("容量与网格不符")
    if stats["seated"] + stats["unplaced"] != roster_size:
        problems.append("已座+未排与名册总数不符")
    if len(seats) != len(result["assignments"]):
        problems.append("存在重复座位")
    if any(not (0 <= r < rows and 0 <= c < cols) for r, c in seats):
        problems.append("座位越界")
    if problems:
        raise SeatingFailedError("方案自校验失败:" + ";".join(problems))


def run_generation(db: Session, hall_id: int) -> dict:
    """成功一次:快照仓落一代 + 指针拨到该代 + 读模型重建,三者同一事务。

    任一步抛错 -> 整体回滚:不留世代号、不留半张方案、指针不前移。
    """
    hall = db.get(Hall, hall_id)
    if hall is None:
        raise HallNotFoundError(f"考室 {hall_id} 不存在")
    try:
        result, roster_size = _compute_result(db, hall)
        _assert_consistent(result, roster_size)
        now = datetime.utcnow()
        last = db.scalar(
            select(func.max(SeatGeneration.generation)).where(SeatGeneration.hall_id == hall_id)
        )
        generation = (last or 0) + 1
        # 1) 快照仓:落可区分的一代
        db.add(SeatGeneration(
            hall_id=hall_id, generation=generation, created_at=now,
            snapshot_json=json.dumps(result, ensure_ascii=False),
        ))
        # 2) 世代指针:拨到这一代
        pointer = db.get(SeatPointer, hall_id)
        if pointer is None:
            pointer = SeatPointer(hall_id=hall_id, generation=generation, updated_at=now)
            db.add(pointer)
        else:
            pointer.generation = generation
            pointer.updated_at = now
        # 3) 读模型:按同一份结果重建,与指针同代
        stats = result["stats"]
        rm = db.get(SeatReadModel, hall_id)
        if rm is None:
            rm = SeatReadModel(hall_id=hall_id)
            db.add(rm)
        rm.generation = generation
        rm.seated = stats["seated"]
        rm.unplaced = stats["unplaced"]
        rm.violations = stats["violations"]
        rm.capacity = stats["capacity"]
        rm.view_json = json.dumps(result, ensure_ascii=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"generation": generation, **result}


# ---------- 读路径 ----------

def _aligned_read_model(db: Session, hall_id: int) -> SeatReadModel | None:
    """读模型必须与指针同代;错位即整场失败。无指针(从未成功排座)返回 None。"""
    pointer = db.get(SeatPointer, hall_id)
    if pointer is None:
        return None
    rm = db.get(SeatReadModel, hall_id)
    if rm is None or rm.generation != pointer.generation:
        raise ReadModelMisalignedError(
            f"考室 {hall_id} 指针指向第 {pointer.generation} 代,读模型缺失或不在同一代"
        )
    return rm


def current_view(db: Session, hall_id: int) -> dict | None:
    """排座图数据:只展示指针所指世代。从未排座返回 None。"""
    rm = _aligned_read_model(db, hall_id)
    if rm is None:
        return None
    return {"generation": rm.generation, **json.loads(rm.view_json)}


def current_stats(db: Session, hall_id: int) -> dict | None:
    """统计:与排座图同一套已座/未排/违规数字。"""
    rm = _aligned_read_model(db, hall_id)
    if rm is None:
        return None
    return {
        "generation": rm.generation,
        "seated": rm.seated,
        "unplaced": rm.unplaced,
        "violations": rm.violations,
        "capacity": rm.capacity,
    }


def current_violations(db: Session, hall_id: int) -> dict | None:
    """违规列表:与排座图同一代的违规与未排。"""
    rm = _aligned_read_model(db, hall_id)
    if rm is None:
        return None
    view = json.loads(rm.view_json)
    return {
        "generation": rm.generation,
        "violations": view.get("violations", []),
        "unplaced": view.get("unplaced", []),
    }


def generation_snapshot(db: Session, hall_id: int, generation: int) -> dict | None:
    """按世代编号读旧世代:只回快照原文。

    纯读——不插入新方案行、不改指针;也绝不用现网最小距或现网名单重算,
    即使考室参数与名册此后已变。不存在返回 None。
    """
    row = db.scalar(
        select(SeatGeneration).where(
            SeatGeneration.hall_id == hall_id, SeatGeneration.generation == generation
        )
    )
    if row is None:
        return None
    return {
        "generation": row.generation,
        "created_at": row.created_at.isoformat(),
        **json.loads(row.snapshot_json),
    }


def list_generations(db: Session, hall_id: int) -> list[dict]:
    """快照仓里某考室的全部世代(只读)。"""
    rows = db.scalars(
        select(SeatGeneration).where(SeatGeneration.hall_id == hall_id)
        .order_by(SeatGeneration.generation)
    ).all()
    out = []
    for r in rows:
        stats = json.loads(r.snapshot_json).get("stats", {})
        out.append({"generation": r.generation, "created_at": r.created_at.isoformat(), **{
            k: stats.get(k) for k in ("seated", "unplaced", "violations", "capacity")
        }})
    return out
