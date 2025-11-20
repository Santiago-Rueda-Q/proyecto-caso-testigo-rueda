from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
from . import models, schemas

def get_task(db: Session, task_id: int) -> Optional[models.Task]:
    return db.query(models.Task).filter(models.Task.id == task_id, models.Task.is_active == True).first()

def get_tasks(db: Session, skip: int = 0, limit: int = 50) -> List[models.Task]:
    return db.query(models.Task).filter(models.Task.is_active == True).offset(skip).limit(limit).all()

def get_tasks_by_status(db: Session, status: str) -> List[models.Task]:
    return db.query(models.Task).filter(models.Task.status == status, models.Task.is_active == True).all()

def get_overdue_tasks(db: Session):
    return (
        db.query(models.Task)
        .filter(models.Task.due_date != None, models.Task.due_date < datetime.utcnow(),
                models.Task.is_active == True, models.Task.status != "done")
        .all()
    )

def create_task(db: Session, task_in: schemas.TaskCreate):
    task = models.Task(**task_in.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

def update_task(db: Session, db_task: models.Task, task_in: schemas.TaskUpdate):
    data = task_in.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(db_task, field, value)
    db.commit()
    db.refresh(db_task)
    return db_task

def soft_delete_task(db: Session, db_task: models.Task):
    db_task.is_active = False
    db.commit()

def complete_task(db: Session, db_task: models.Task):
    db_task.status = "done"
    db.commit()
    db.refresh(db_task)
    return db_task
