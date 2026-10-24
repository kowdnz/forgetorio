# STATUS — Factorio Modpack Launcher 0.1.1

Atualizado em 2026-10-24. “Validado no jogo” = executado com o Factorio real desta máquina; “teste automatizado” = pytest com mocks.

## Funcionalidades

| Área | Estado | Como foi verificado |
|---|---|---|
| Detecção do Factorio (Steam em qualquer disco, standalone, manual) + versão via `--version` | Funcional | Real: achou 2.1.23 (C:) e 2.0.77 (E:); testes de caminhos |
| CRUD de perfis (criar, renomear, duplicar, excluir c/ confirmação), UUID, manifesto próprio | Funcional | Testes + UI offscreen |
| Mods independentes por perfil (`mods/`, `mod-list.json`) | Funcional | Testes; real: perfil carregou os mods certos |
| Instalar ZIP local (validação de info.json, path traversal, ZIP malformado), habilitar/desabilitar, remover | Funcional | Testes |
| Importar mods da pasta atual do Factorio (somente cópia; origem intocada) | Funcional | Teste + real (42 mods, 0 erros) |
| Mod em desenvolvimento (importar pasta, abrir pasta, último erro do log) | Funcional (básico) | Teste de importação; leitura de log só manual |
| JOGAR com `--mod-directory`/`--config`; Steam via `-applaunch 427520`; bloqueia 2ª instância | Funcional | Testes de argumentos e acompanhamento do processo (mock); real via `--create` para a instalação independente (ver abaixo) |
| Saves exclusivos/compartilhados + troca de modo + aviso | Funcional | Testes do config.ini; **real**: ver abaixo |
| **Busca por tags** (`POST /api/search`): barra lateral (incluir / excluir), comandos `$trains`, `$trains $logistics` (todas), `-$combat`, `cargo $trains`, autocomplete ao digitar `$`, aliases PT/EN → 18 ids oficiais | Funcional (requer login) | **Real**, pela UI, com token: contagens e conteúdo conferidos (ver abaixo) + 39 testes |
| Explorar Mods no estilo do navegador do Factorio: filtros laterais (categorias com contagem, compatibilidade, instalados), lista paginada com ícones, ordenação, painel de detalhes (descrição, autor, links do Portal/homepage/código, versão do Factorio, dependências coloridas, registro de mudanças) | Funcional | Real (captura de tela com ícones do Portal) + testes |
| Mod Portal: catálogo (cache 24 h), busca local, detalhes/releases, miniaturas em cache, cache offline | Funcional | Real: 20 163 mods, detalhes e releases; testes com mock |
| Saves compartilhados mostram também a **Steam Cloud** (inventário do `remotecache.vdf` local, somente leitura; marca “só na nuvem”) | Funcional | Real: leitura dos seus saves em Steam/userdata + testes |
| Resolvedor de dependências (obrigatórias/transitivas, `!`, `?`, `(?)`, `~`, versões, DLC, versão do jogo) | Funcional | Real (Krastorio2 Spaced Out) + testes; pede confirmação e não instala parcial |
| Download: `.part` → SHA-1 → validação do ZIP → cache global → cópia ao perfil | Implementado | **Só testes com mock** (ver limitações) |
| Credenciais: Windows Credential Manager (keyring), importação de `player-data.json` só por clique | Implementado | Testes com keyring falso |
| Atualizar mods, fixar versões (lockfile no manifesto), backup antes de atualizar | Funcional | Testes de resolvedor/backup; fluxo de UI sem teste real de download |
| Backup/restauração de perfil (mods, config, saves opcionais), exportar/importar lista de mods | Funcional | Testes |
| Downloads: fila, progresso, erro, retry, cancelar | Funcional | Testes + UI offscreen |
| `.exe` PyInstaller | Gerado em `dist/` | Abre e cria logs (`FML_DATA_DIR` isolado) |

## Validação real com o Factorio (2.0.77, E:)

Roteiros em `tools/` (usam pasta de dados temporária do projeto; `.smoke_data/` é descartável):

- **Exclusivo** (`tools/real_check_exclusive.py`): `factorio.exe --config … --mod-directory … --create` → log do jogo mostra
  `Read data path` = instalação, `Write data path` = pasta do perfil, mods carregados do mod-list do perfil;
  `factorio-current.log` e `player-data.json` nasceram dentro do perfil; **`%APPDATA%/Factorio` ficou byte a byte igual**.
- **Compartilhado com pasta explícita** (`tools/real_check_shared.py`): `write-data` = pasta escolhida, save criado ali, 42 mods
  importados carregaram (ex.: `Loading mod Bottleneck 0.12.1`), diagnóstico sem pendências, `%APPDATA%/Factorio` intocado.

**Não validado:** modo compartilhado apontando para o `%APPDATA%/Factorio` verdadeiro (evitado de propósito para não
criar/alterar saves reais — faça o teste manual abaixo); Steam Cloud (o launcher não mexe em `userdata` da Steam e **não** afirma
nada sobre sincronização); jogar de fato pela interface (o clique em JOGAR foi testado com mock; o launch real foi via linha de comando equivalente).

## Limitações conhecidas

1. **Download real do Portal não foi exercitado** (exige usuário+token legítimos; não li o seu `player-data.json`). O fluxo completo
   (redirect sem vazar credenciais, SHA-1, ZIP, cache) está coberto por testes com servidor simulado. Sem credenciais o job fica “requer autenticação”.
2. **Steam Cloud**: só lista o que a Steam já sincronizou; baixar/enviar à nuvem exigiria a própria Steam e o launcher não faz isso.
3. **Busca por tags exige login do Mod Portal**: `POST /api/search` responde 400/403 sem `username`+`token` válidos. Sem credenciais (ou offline) o app usa o catálogo local em cache (até 24 h defasado), **sem filtro de tags**, e avisa na tela.
4. Compatibilidade de versão do jogo: mod com `factorio_version` de mesmo major e minor menor é marcado “possivelmente” (aviso), não bloqueado.
5. A resolução de dependências escolhe a release mais nova compatível sem backtracking; em conflito, bloqueia e explica (nunca instala parcial).
6. Nome/ícone/cartões usam cores configuráveis; imagens personalizadas por perfil não foram implementadas.
7. Só Windows foi considerado (detecção de processo via `tasklist`, `os.startfile`).

## Teste manual recomendado (você)

1. Crie um perfil **exclusivo**, instale um ZIP, clique JOGAR, crie e salve um mundo → deve aparecer em `profiles/<uuid>/userdata/saves`.
2. Crie um perfil **compartilhado** → confirme que seus saves habituais aparecem na lista de saves do jogo.
3. Em Configurações, use “Importar do player-data.json” e instale um mod pelo Explorar para validar o download real.

## Validação da busca por tags (rede real, 2026-10-24, Factorio 2.0.77)

`POST https://mods.factorio.com/api/search` com `{username, token, version, show_deprecated:false, tag/exclude_tag/query…}`.

| Consulta | Resultado | Verificação |
|---|---|---|
| sem filtro | 10 032 | baseline |
| `$trains` | 523 | 100 % dos resultados têm `trains` em `tags`; 25/25 amostras aleatórias confirmadas em `/api/mods/{n}/full` |
| `$logistics` | 1 288 | idem |
| `tag=[trains, logistics]` (servidor) | 1 629 = 523 + 1 288 − 182 | conjunto == união (**OR**, não AND) |
| `$trains $logistics` (app) | 182 | filtro local pelo campo `tags`; 182 == interseção; 8/8 amostras com ambas |
| `$trains -$combat` | 427 | conjunto == trains − combat (igualdade de conjuntos), 0 resultados com `combat` |
| `-$combat` | 8 861 | 0 resultados com `combat` |
| `cargo` / `cargo $trains` | 228 / 52 | todos os 52 têm `trains` |
| tag inexistente | HTTP 400 `is not a valid choice` | prova que o servidor valida; ids válidos = 16 da wiki + `planets` + `character` |
| sem token / token vazio | HTTP 400 / 403 | `/api/search` exige credenciais |

Observações: `page_size` precisa ser inteiro (`"max"` é recusado; usamos 20000); a busca já devolve `tags`, `thumbnail` e
`factorio_versions`, então a lista não precisa de `/full` para ícones. O token foi lido de `player-data.json` só em memória
(com autorização) e uma varredura confirmou que não foi gravado em nenhum arquivo do projeto, cache ou log.

## Redesign da Biblioteca (2026-10-24)

| Item | Estado | Verificação |
|---|---|---|
| Sidebar com ícones, destaque laranja, selo de downloads ativos, versão | Funcional | capturas + teste do selo |
| Cabeçalho, filtros (Todos/Favoritos/Com mods/Vanilla com contagens reais), busca (nome, notas, versão, modo, nomes dos mods), 5 ordenações persistidas | Funcional | 14 testes + capturas |
| Cards: banner, nome, versão/instalação, badges, saves, mods, último jogo, tempo jogado, favoritar, JOGAR/Detalhes/menu | Funcional | capturas + testes |
| Painel lateral (docado ≥ 1040 px, gaveta abaixo), rolagem independente, animação de 180 ms, seleção persistida | Funcional | testes + capturas em 1672/1366/1100/900 px |
| Mods no painel com interruptor: bloqueia desabilitar quando outro mod habilitado depende dele, base/core, perfil em execução | Funcional | testes |
| Saves no painel: preview real do `preview.jpg` do ZIP, ▶ carrega o save (`--load-game`), nuvem Steam só em perfil compartilhado | Funcional | captura real + testes |
| Banners: oficiais baixados sob demanda, importar imagem própria, restaurar padrão, persistência por perfil, clone copia o banner | Funcional | testes + captura real (42 imagens baixadas) |
| Tokens de design centralizados (`ui/tokens.py`), tema global gerado deles | Feito | teste |

### Decisões e limitações reais
- **Imagens oficiais não são redistribuídas** (ver `assets/README.md`); precisam ser baixadas pelo usuário uma vez. Sem isso, banner desenhado.
- **"Meus perfis"** (do mockup) não foi criado: todos os perfis são do usuário; não existe dado que o diferencie de "Todos".
- **Tempo jogado** só conta sessões iniciadas pelo launcher que duraram ≥ 10 s e enquanto o launcher estava aberto; começa em 0 (mostra "—"). Perfis antigos não têm histórico.
- Último jogo = `last_played` (gravado ao clicar em JOGAR; não detecta jogos iniciados fora do launcher).
- "Editar" altera nome, cor e banner; modo de saves/instalação continuam em Detalhes → Configurações (fluxos já existentes).
- Cards não possuem animação de hover além do realce de borda; a seleção anima o brilho (180 ms).
- Até 40 perfis os números dos cards são calculados na hora; acima disso, em segundo plano (com cache por mtime).
- Não testado: monitores com escala ≠ 100 % (os pixmaps usam `devicePixelRatio`, mas não houve captura em 125/150 %).
