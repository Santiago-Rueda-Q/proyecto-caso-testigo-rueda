from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from .database import get_db, Base, engine
from . import schemas, crud, models

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Task Manager API - Caso Testigo Rueda", version="1.0.0")

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/tasks", response_model=List[schemas.TaskOut])
def list_tasks(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return crud.get_tasks(db, skip=skip, limit=limit)

@app.get("/tasks/{task_id}", response_model=schemas.TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task

@app.post("/tasks", response_model=schemas.TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(task_in: schemas.TaskCreate, db: Session = Depends(get_db)):
    return crud.create_task(db, task_in)

@app.put("/tasks/{task_id}", response_model=schemas.TaskOut)
def update_task(task_id: int, task_in: schemas.TaskUpdate, db: Session = Depends(get_db)):
    db_task = crud.get_task(db, task_id)
    if not db_task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return crud.update_task(db, db_task, task_in)

@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    db_task = crud.get_task(db, task_id)
    if not db_task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    crud.soft_delete_task(db, db_task)
    return

@app.patch("/tasks/{task_id}/complete", response_model=schemas.TaskOut)
def complete_task(task_id: int, db: Session = Depends(get_db)):
    db_task = crud.get_task(db, task_id)
    if not db_task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return crud.complete_task(db, db_task)

@app.get("/tasks/status/{status}", response_model=List[schemas.TaskOut])
def tasks_by_status(status: str, db: Session = Depends(get_db)):
    if status not in ["pending", "in_progress", "done"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")
    return crud.get_tasks_by_status(db, status)

@app.get("/tasks/overdue", response_model=List[schemas.TaskOut])
def overdue_tasks(db: Session = Depends(get_db)):
    return crud.get_overdue_tasks(db)
