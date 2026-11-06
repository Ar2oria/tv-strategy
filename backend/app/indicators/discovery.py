"""Restart-based discovery of local built-in and custom indicator modules."""

import importlib
import pkgutil
from types import ModuleType

from app.indicators.registry import RegistryError, default_registry
from app.indicators.registry import IndicatorRegistry

INDICATOR_PACKAGES = ("app.indicators.builtin", "app.indicators.custom")


class IndicatorDiscoveryError(RuntimeError):
    """A local indicator package could not be imported completely."""


def discover_indicators() -> IndicatorRegistry:
    """Import every local indicator module and return the populated registry.

    Python's module cache makes repeated calls idempotent. Registration conflicts
    deliberately propagate so startup fails instead of silently choosing a class.
    """
    importlib.invalidate_caches()
    for package_name in INDICATOR_PACKAGES:
        package = importlib.import_module(package_name)
        _import_package_modules(package)
    return default_registry


def _import_package_modules(package: ModuleType) -> None:
    paths = getattr(package, "__path__", None)
    if paths is None:
        raise IndicatorDiscoveryError(
            f"Indicator discovery target {package.__name__!r} is not a package"
        )
    prefix = f"{package.__name__}."
    module_names = sorted(
        module_info.name
        for module_info in pkgutil.walk_packages(paths, prefix=prefix)
    )
    for module_name in module_names:
        try:
            importlib.import_module(module_name)
        except RegistryError:
            raise
        except Exception as error:
            raise IndicatorDiscoveryError(
                f"Failed to import indicator module {module_name!r}: {error}"
            ) from error
