"""Runtime dependencies exposed to Tasks without importing market modules."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.providers.registry import ProviderRegistry
    from app.repositories.bars import BarRepository
    from app.repositories.instruments import InstrumentRepository
    from app.services.bar_sync_service import BarSyncService


@dataclass(frozen=True, slots=True)
class RuntimeResources:
    """Repositories and optional market services used by concrete Tasks."""

    instrument_repository: "InstrumentRepository"
    bar_repository: "BarRepository"
    provider_registry: "ProviderRegistry | None" = None
    bar_sync_service: "BarSyncService | None" = None

    @property
    def instruments(self) -> "InstrumentRepository":
        """Short alias used by market synchronization Tasks."""
        return self.instrument_repository

    @property
    def bars(self) -> "BarRepository":
        return self.bar_repository

    @property
    def providers(self) -> "ProviderRegistry | None":
        return self.provider_registry

    @property
    def bar_sync(self) -> "BarSyncService | None":
        return self.bar_sync_service
