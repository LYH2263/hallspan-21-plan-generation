from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services import seating_store

router = APIRouter(prefix="/seating", tags=["seating"])


@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    """排座一次:成功则落一代快照并拨指针;失败则什么都不留下。"""
    try:
        return seating_store.run_generation(db, hall_id)
    except seating_store.HallNotFoundError as e:
        raise HTTPException(404, str(e))
    except seating_store.SeatingFailedError as e:
        raise HTTPException(500, f"排座失败,未留下任何踪迹:{e}")


@router.get("/current")
def current(hall_id: int = 1, db: Session = Depends(get_db)):
    """排座图:只展示指针所指世代;从未排座则 404,绝不顺手排一把。"""
    try:
        data = seating_store.current_view(db, hall_id)
    except seating_store.ReadModelMisalignedError as e:
        raise HTTPException(500, str(e))
    if data is None:
        raise HTTPException(404, "该考室尚未排座")
    return data


@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    try:
        data = seating_store.current_violations(db, hall_id)
    except seating_store.ReadModelMisalignedError as e:
        raise HTTPException(500, str(e))
    if data is None:
        raise HTTPException(404, "该考室尚未排座")
    return {"hall_id": hall_id, **data}


@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    try:
        data = seating_store.current_stats(db, hall_id)
    except seating_store.ReadModelMisalignedError as e:
        raise HTTPException(500, str(e))
    if data is None:
        raise HTTPException(404, "该考室尚未排座")
    return {"hall_id": hall_id, **data}


@router.get("/generations")
def generations(hall_id: int = 1, db: Session = Depends(get_db)):
    return {"hall_id": hall_id, "generations": seating_store.list_generations(db, hall_id)}


@router.get("/generations/{generation}")
def generation(generation: int, hall_id: int = 1, db: Session = Depends(get_db)):
    """读旧世代:只回快照,不重算、不写行、不动指针。"""
    data = seating_store.generation_snapshot(db, hall_id, generation)
    if data is None:
        raise HTTPException(404, f"考室 {hall_id} 没有第 {generation} 代快照")
    return data
