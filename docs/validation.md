# Validação da entrega

- Python 3.13, Windows; compatibilidade declarada Python >=3.11.
- 32 testes offline aprovados com unittest, incluindo fluxo CLI search/get/read JSON, seleções concorrentes, fallback de provedores, OpenReview attachment, cache, proteção contra sobrescrita, annotations padrão e detecção de páginas ausentes.
- Instalação editable e comandos --help/--version verificados. Wheel construído usando dependências já instaladas, sem acesso ao índice remoto.
- Revisão independente encontrou três problemas importantes; todos receberam testes de regressão que falharam antes das correções e passaram depois.
- Teste real das APIs **não realizado**: ambiente bloqueia sockets externos do Python com WinError 10013. A chave fornecida não foi usada, armazenada ou incluída nos artefatos. Não houve chamada paga de OCR.
- Funcionamento ao vivo de Mistral, OpenAlex, arXiv, OpenReview e IEEE precisa ser confirmado em ambiente com acesso à rede. A documentação oficial foi consultada; testes simulados não substituem essa integração.

## Teste real sugerido após instalar

Configure MISTRAL_API_KEY no ambiente e execute:

```bash
paper2md search "recent diffusion low-rank adaptation" --limit 5 --json
paper2md get arxiv:2402.09353 --pages 1 --json
```

O segundo comando converte somente uma página, com descrições de imagens por padrão. Inspecione paper.md, assets/ e manifest.json. Para documento completo, execute novamente sem --pages. Não há retentativa automática de OCR em caso de timeout.
