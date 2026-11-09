# ADR 0008: Validação de JWT via JWKS em cache e token de serviço interno

- **Status:** aceita

## Contexto

Quem emite os tokens de usuário é a Equipe 1 (Identidade). Nossos serviços precisam validar o token em toda requisição sem depender de uma chamada à Equipe 1 a cada vez, e continuar funcionando se ela ficar fora do ar. Além disso, os workers (por exemplo, a retentativa do estorno na saga de disputa) agem sem nenhum usuário por trás, então não há token de usuário para repassar.

## Decisão

- **Validação local por JWKS.** `VerificadorJwks` busca as chaves públicas no JWKS da Equipe 1 e as guarda em cache com TTL (padrão da classe: 300 s). Se a Equipe 1 estiver fora depois do primeiro carregamento, o verificador continua com a última chave conhecida. Se nunca obteve o JWKS, responde como dependência indisponível (503), não como token inválido. Um `kid` desconhecido força uma recarga, respeitando um intervalo mínimo entre tentativas.
- **Token de serviço interno.** `EmissorTokenServico` emite um JWT HS256 com `iss = financeiro-eq5` e papel `servico`, assinado por um segredo compartilhado só entre os três serviços (`TOKEN_SERVICO_SEGREDO`).
- **Verificador composto.** `VerificadorComposto` olha o `iss` sem validar assinatura apenas para escolher o verificador, e cada verificador então valida de verdade: o interno com o segredo, o externo com o JWKS.
- O papel `servico` só passa nas rotas que o declaram: hoje, criar e estornar pagamento (`exigir_papeis(..., Papel.SERVICO)`).
- O segredo padrão de desenvolvimento é recusado em produção na configuração.

## Alternativas consideradas

- **Introspecção por chamada à Equipe 1 a cada requisição:** dependência síncrona e latência em todo request; o JWKS foi mantido como o caminho principal.
- **Segredo HS256 compartilhado com a Equipe 1:** quem tem o segredo pode forjar tokens de qualquer usuário.
- **Worker usa o token do usuário original:** o token pode ter expirado quando a retentativa acontecer.
- **mTLS entre serviços:** mais seguro, mas exige PKI que não temos.

## Consequências

- A Equipe 1 pode estar fora e os usuários com token válido continuam sendo atendidos, desde que o JWKS tenha sido carregado uma vez.
- O segredo interno é um ponto sensível: quem o tem vira `servico`. Por isso fica em GitHub Secrets, no `.env` da VM, e não é versionado.
- Não há revogação imediata de token: vale o `exp`.

**Onde está no código:** `libs/plataforma/src/plataforma/auth.py` (`VerificadorJwks`, `EmissorTokenServico`, `VerificadorTokenServico`, `VerificadorComposto`, `criar_verificador`), `libs/plataforma/src/plataforma/api/auth.py` (`exigir_papeis`), `libs/plataforma/src/plataforma/config.py` (`SEGREDO_DE_DESENVOLVIMENTO`), `services/pagamentos/src/pagamentos/adaptadores/http/dependencias.py` (`QuemEstorna`), `services/avaliacoes/src/avaliacoes/aplicacao/saga.py` (token de serviço no worker).
