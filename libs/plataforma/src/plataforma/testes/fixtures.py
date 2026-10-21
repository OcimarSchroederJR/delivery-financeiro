"""Fixtures pytest com testcontainers. Importe-as no ``conftest.py``::

from plataforma.testes.fixtures import postgres_url, rabbitmq_url  # noqa: F401
"""

from collections.abc import Iterator

import pytest
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.rabbitmq import RabbitMqContainer

IMAGEM_POSTGRES = "postgres:16-alpine"
IMAGEM_RABBITMQ = "rabbitmq:4-management"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """URL ``postgresql+asyncpg://`` de um Postgres 16 descartável (um por sessão)."""
    with PostgresContainer(IMAGEM_POSTGRES, driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def rabbitmq_url() -> Iterator[str]:
    """URL ``amqp://`` de um RabbitMQ 4 descartável (um por sessão)."""
    with RabbitMqContainer(IMAGEM_RABBITMQ) as rabbit:
        host = rabbit.get_container_host_ip()
        porta = rabbit.get_exposed_port(rabbit.port)
        yield f"amqp://{rabbit.username}:{rabbit.password}@{host}:{porta}/"
