"""Task contracts and restart-based local module discovery."""

from app.tasks.base import Task, TaskContext, TaskParams, TaskResult
from app.tasks.registry import TaskRegistry, register_task

__all__ = [
    "Task",
    "TaskContext",
    "TaskParams",
    "TaskRegistry",
    "TaskResult",
    "register_task",
]
