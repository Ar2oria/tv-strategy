"""Restart-based discovery of built-in and custom Task modules."""

import importlib
import pkgutil
from types import ModuleType

from app.tasks.registry import TaskRegistry, TaskRegistryError, default_registry

TASK_PACKAGES = ("app.tasks.builtin", "app.tasks.custom")


class TaskDiscoveryError(RuntimeError):
    """A local Task package could not be imported completely."""


def discover_tasks() -> TaskRegistry:
    """Import every local Task module and return the populated registry.

    Module caching makes repeated discovery idempotent. Duplicate registrations
    deliberately fail startup instead of silently selecting one implementation.
    """
    importlib.invalidate_caches()
    for package_name in TASK_PACKAGES:
        package = importlib.import_module(package_name)
        _import_package_modules(package)
    return default_registry


def _import_package_modules(package: ModuleType) -> None:
    paths = getattr(package, "__path__", None)
    if paths is None:
        raise TaskDiscoveryError(
            f"Task discovery target {package.__name__!r} is not a package"
        )
    prefix = f"{package.__name__}."
    module_names = sorted(
        module_info.name for module_info in pkgutil.walk_packages(paths, prefix=prefix)
    )
    for module_name in module_names:
        try:
            importlib.import_module(module_name)
        except TaskRegistryError:
            raise
        except Exception as error:
            raise TaskDiscoveryError(
                f"Failed to import Task module {module_name!r}: {error}"
            ) from error
