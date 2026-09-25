from dataclasses import dataclass

import httpx

from app.config import ConnectorSettings
from app.connectors.fixture import FixtureERPConnector, FixtureLogisticsConnector
from app.connectors.http import HttpERPConnector, HttpLogisticsConnector, ResilientHttpReader
from app.connectors.resilience import CircuitBreaker
from app.connectors.service import EnterpriseToolService


@dataclass
class ConnectorBundle:
    tools: EnterpriseToolService
    client: httpx.Client | None = None
    mode: str = "fixture"

    def close(self) -> None:
        if self.client is not None:
            self.client.close()


def create_connector_bundle(settings: ConnectorSettings | None = None, client: httpx.Client | None = None) -> ConnectorBundle:
    settings = settings or ConnectorSettings.from_env()
    if settings.mode == "fixture":
        return ConnectorBundle(
            EnterpriseToolService(FixtureERPConnector(), FixtureLogisticsConnector()),
            mode="fixture",
        )
    owned_client = client or httpx.Client(timeout=httpx.Timeout(
        connect=settings.connect_timeout, read=settings.read_timeout,
        write=settings.write_timeout, pool=settings.pool_timeout,
    ))
    erp_reader = ResilientHttpReader(
        owned_client, "erp", CircuitBreaker("erp", settings.breaker_threshold, settings.breaker_open_seconds), settings.attempts,
    )
    logistics_reader = ResilientHttpReader(
        owned_client, "logistics", CircuitBreaker("logistics", settings.breaker_threshold, settings.breaker_open_seconds), settings.attempts,
    )
    return ConnectorBundle(EnterpriseToolService(
        HttpERPConnector(settings.erp_base_url, erp_reader),
        HttpLogisticsConnector(settings.logistics_base_url, logistics_reader),
    ), owned_client, mode="http")
