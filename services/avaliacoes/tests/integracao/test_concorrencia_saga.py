"""Saga de disputa sob concorrência real no Postgres (spec §4.3 e §5; revisão do PR #21).

- ``PATCH /v1/disputas/{id}`` e o worker concluem a mesma disputa ao mesmo tempo:
  o ``FOR UPDATE`` deve garantir uma única transição e um único ``disputa.resolvida``.
- Commit perdido: Pagamentos gravou o estorno, mas a disputa ficou em
  ``estorno_pendente``. A nova tentativa (mesma ``Idempotency-Key``) recebe o ``201``
  gravado e resolve a disputa sem estorno duplicado.
"""

import pytest

pytestmark = pytest.mark.integracao

URL_PAGAMENTOS = "http://pagamentos.teste"
ROTA_ESTORNOS = "/v1/pagamentos/pag-1/estornos"
