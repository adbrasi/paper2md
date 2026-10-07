# paper2md

CLI Python para descobrir papers a partir de uma descrição, selecionar resultados e obter PDF e conteúdo completo usando Mistral Document AI. Este desenho substitui o escopo inicial limitado à conversão.

## Fluxo aprovado para revisão
Três comandos públicos: search, get e read. O agente consumidor faz a comparação científica; a ferramenta fornece fontes e conteúdo verificável. CLI primeiro; MCP e MySQL são integrações futuras, não dependências da versão inicial.

`paper2md search "métodos recentes de fine-tuning eficiente para diffusion, comparando LoRA e DoRA" --json`

`paper2md get s_ab12:1 s_ab12:3`

`paper2md read arxiv:2402.09353 --json`

search retorna search_id, consulta original, consulta técnica em inglês, instante da consulta, filtros, avisos e até dez resultados. Cada resultado tem ID qualificado pela busca, ID canônico, título, autores, publicação, atualização quando disponível, abstract, venue, fonte, DOI, URL e disponibilidade de PDF. Números soltos nunca se referem implicitamente à última busca: IDs como s_ab12:3 evitam colisões entre subagentes.

get aceita múltiplos IDs, URL ou PDF local. Obtém PDF, Markdown e manifest.json por paper; TXT e JSON são formatos adicionais. Falha de um paper não apaga os demais; manifest por lote registra sucesso, cache ou erro por ID, com exit code não zero para falhas. read fornece o Markdown completo e a procedência em JSON; se ainda não estiver convertido, usa o mesmo pipeline de get. Não truncar silenciosamente papers longos.

## Descoberta
Recomendação: OpenAlex como busca semântica principal e arXiv como complemento de trabalhos recentes. Alternativa mais barata em dependências: só arXiv, com menor cobertura e busca lexical. Alternativa mais pesada: índice próprio como arXiv at Home, descartada para este escopo compacto.

A Mistral transforma a descrição em uma consulta técnica em inglês e até três consultas arXiv, preservando termos explícitos do usuário. Ela não inventa referências nem corrige nomes ambíguos silenciosamente. Resultados sempre vêm das APIs. OpenAlex usa search.semantic com filtro de publicação; arXiv usa sua API oficial com consultas de título/abstract. Deduplicar por DOI, ID arXiv e título normalizado, preservando links e metadados dos provedores.

Janela padrão: últimos dois anos móveis, configurável por --since. Limite padrão: dez resultados. Prioridade de relevância dentro da janela; --sort recent ordena por data. Não relaxar a janela automaticamente. Exibir falta de resultados, ausência de abstract e falha parcial dos provedores. Sem percentuais artificiais de match, sem igualar citações a qualidade, sem prometer indexação em tempo real. Papers fundacionais antigos só entram se o usuário ampliar a janela ou fornecer o link diretamente.

Se OpenAlex estiver indisponível ou exigir orçamento/chave, retornar resultados arXiv com aviso de cobertura reduzida. OPENALEX_API_KEY é opcional e nunca aparece nos logs. SEARCH_MODEL configura o modelo de expansão Mistral. Expansão inválida/falha usa a consulta original com aviso, sem interromper acesso aos provedores.

## Persistência e agentes
SQLite local com buscas e metadados, arquivos em diretório configurável. Estado padrão no diretório de dados do usuário, sem servidor ou Docker. search_id persistente e transações evitam que buscas de agentes distintos sobrescrevam seleções. IDs canônicos preferem arxiv:<id>, doi:<doi> e openalex:<id>. DOI serve à identidade, não implica PDF acessível.

Cache OCR identificado pelo hash PDF, modelo, páginas e opção de annotations; repetir get reutiliza conversão compatível. Guardar versão do paper e instante da obtenção. Reconsultar fonte ao obter um paper quando necessário; read de conteúdo salvo deixa explícita a versão. Inicialmente serializar trabalho por paper para evitar chamadas OCR concorrentes duplicadas.

Saída --json versionada e estável em stdout; progresso em stderr. Núcleo expõe search_papers(query, since, limit), get_papers(ids, options) e read_paper(id), sem depender de argparse. Essa separação permite futuro adaptador MCP pequeno. MySQL pode substituir o armazenamento futuramente, sem entrar no fluxo atual.

## Uso
`paper2md get SOURCE... [-o DIRECTORY] [--format md|txt|json] [--no-describe-images] [--no-images] [--pages 1-3] [--model MODEL] [--force]`

Markdown por padrão; chave exclusivamente por MISTRAL_API_KEY. Modelo mistral-ocr-latest configurável. Saída em ./papers, com nome seguro baseado no identificador e hash para URLs genéricas. Sem --force, nunca sobrescrever. Progresso e erros em stderr.

## Fontes
Resolver abs/html/pdf arXiv preservando versões e IDs antigos; Hugging Face /papers pelo ID arXiv; OpenReview forum/pdf por ID e anexo público da API v2, com fallback v1. IEEE e páginas genéricas: procurar citation_pdf_url ou link inequívoco para PDF público. Se bloqueado, orientar fornecimento de PDF local. Não incluir autenticação IEEE ou acesso a paywall nesta versão. Aceitar PDFs diretos e arquivos locais.

## Componentes
Pacote src/paper2md com cli, sources, transport, mistral e export. argparse para CLI, httpx para HTTP, markdown-it-py para TXT e PyMuPDF para validar estrutura e contar páginas antes do OCR. REST direto evita acoplamento à versão do SDK. Pipeline: resolver, baixar, validar PDF/tamanho/páginas, enviar Base64 ao OCR, conferir presença de todas as páginas solicitadas e exportar em ordem. Limite local padrão de 50 MiB, sem substituir limites da API. Timeout e redirects limitados. Nunca registrar credenciais ou conteúdo de documentos.

## Figuras
include_image_base64 salva imagens em assets/ dentro do bundle do paper, com nomes gerados por página e posição, sem confiar nos IDs como caminhos. Reescrever referências no Markdown. Descrições ativadas por padrão via bbox_annotation_format com JSON schema de tipo e descrição em português; --no-describe-images desativa. Inserir descrição identificada como gerada por IA junto à figura e no TXT. Annotations são distintas da extração de imagens e podem ter custo adicional. JSON preserva resposta estruturada e metadados sem segredos.

## Saídas e falhas
Markdown mantém equações, títulos e tabelas retornados pelo OCR. TXT usa tokens Markdown para remover marcação preservando texto, código e URLs úteis. --pages usa índices humanos convertidos aos índices da API. Validar destinos antes de chamada paga. Exportar via temporários e mover resultados completos. Falhas de autenticação, timeout, PDF inválido, acesso bloqueado e respostas malformadas geram mensagem acionável e exit code não zero. Retry limitado para downloads; não repetir OCR automaticamente após timeout ambíguo, evitando cobrança duplicada.

## Verificação
Testes offline de resolvers, requests, falhas, seleção de páginas, exportação, assets e sobrescrita. Conferir instalação, --help e --version. Teste real autorizado limitado a uma página com figura, verificando OCR e annotations. Não declarar fontes verificadas online sem evidência específica. Entregar README em português, pyproject.toml, .env.example sem segredo e .gitignore.

## Fora do escopo
Web UI, índice vetorial próprio, crawling em massa, tradução do paper, comparação científica embutida, resumo, autenticação IEEE, servidor MCP, MySQL e publicação PyPI.

## Referências
- https://docs.mistral.ai/studio/document-processing/overview
- https://docs.mistral.ai/studio/document-processing/annotations
- https://docs.mistral.ai/api/endpoint/ocr
- https://help.openalex.org/api/semantic-search/
- https://help.openalex.org/api/authentication/
- https://github.com/mrapplexz/arxiv-at-home

## Testes adicionais do fluxo de pesquisa
Testar expansão de consulta válida/inválida, recorte por data, deduplicação entre fontes, arXiv indisponível, OpenAlex indisponível, IDs de duas buscas concorrentes, seleção persistente após reiniciar CLI, recuperação de cache compatível e incompatível, falha parcial em lote e retorno completo em read. Smoke test online com assunto de fine-tuning verifica metadados reais; OCR real limitado a uma página verifica annotations. Não inferir qualidade científica de sucesso técnico.

## Revisão
Escopo de uma CLI com pipeline único; sem placeholders. Extração de figuras e descrição estão separadas, e restrições de acesso estão explícitas.
