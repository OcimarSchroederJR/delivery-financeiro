# Máquinas de estado

Estados do Pagamento (serviço Pagamentos) e da Disputa (serviço Avaliações), conforme `StatusPagamento` e `StatusDisputa` no código.

## Pagamento

Um pagamento nasce `aprovado` ou `recusado`. Só `aprovado` e `parcialmente_estornado` aceitam estorno. O pagamento vira `estornado` quando o estorno é igual ao saldo estornável.

```mermaid
stateDiagram-v2
    [*] --> aprovado: gateway aprova
    [*] --> recusado: gateway recusa
    aprovado --> parcialmente_estornado: estorno parcial
    aprovado --> estornado: estorno do saldo inteiro
    parcialmente_estornado --> parcialmente_estornado: novo estorno parcial
    parcialmente_estornado --> estornado: estorno do saldo restante
    recusado --> [*]
    estornado --> [*]
```

## Disputa

A disputa nasce `aberta`. O admin a julga improcedente ou procedente. A procedente passa por `estorno_pendente` até o estorno em Pagamentos ser concluído ou falhar de vez.

```mermaid
stateDiagram-v2
    [*] --> aberta: cliente abre a disputa
    aberta --> improcedente: admin julga improcedente
    aberta --> estorno_pendente: admin julga procedente
    estorno_pendente --> estorno_pendente: falha transitória, o worker repete
    estorno_pendente --> resolvida: estorno concluído
    estorno_pendente --> estorno_falhou: falha definitiva ou RESULTADO_INCERTO
    improcedente --> [*]
    resolvida --> [*]
    estorno_falhou --> [*]
```
