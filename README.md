# Forgetorio

> **Aviso:** este projeto foi desenvolvido com uso de *vibecoding* e assistência de IA. Revise o código e teste os fluxos importantes antes de confiar nele para gerenciar seus perfis e saves.

**Código aberto:** qualquer pessoa pode usar, copiar, modificar e redistribuir o código sob a [licença MIT](LICENSE). Preserve o aviso de direitos autorais e a licença nas cópias. Imagens e marcas do Factorio pertencem à Wube Software e não estão incluídas nessa licença; veja [assets/README.md](assets/README.md).

Launcher para Windows que cria **perfis independentes** do Factorio: cada perfil tem seus próprios mods (ZIPs,
`mod-list.json`, configurações de mods) e escolhe entre **saves exclusivos** ou **compartilhados**. Usa o Factorio que
você já tem instalado (Steam ou standalone) — nada do jogo é copiado ou redistribuído.

## Como funciona o isolamento

O jogo é iniciado assim, sem nunca mexer em `%APPDATA%/Factorio/mods`:

```
factorio.exe --mod-directory <dados>/profiles/<uuid>/mods --config <dados>/profiles/<uuid>/config/config.ini
```

| Modo | `write-data` no config.ini do perfil | O que fica isolado |
|---|---|---|
| Exclusivo | `<dados>/profiles/<uuid>/userdata` | mods, saves, blueprints, player-data, logs |
| Compartilhado | `%APPDATA%/Factorio` (ou pasta escolhida) | só os mods; saves/blueprints/logs são os comuns |

`read-data` aponta sempre para `<instalação>/data`. Os dados do launcher ficam em
`%LOCALAPPDATA%\FactorioModpackLauncher\` (override: variável `FML_DATA_DIR`).

## Executar (desenvolvimento)

```powershell
.\start.ps1                       # cria .venv, instala dependências e abre o app
# ou, com as dependências já instaladas:
$env:PYTHONPATH="src"; python -m factorio_launcher
```

## Testes

```powershell
python -m pytest -q               # 152 testes, isolados (tmp dirs; não tocam %APPDATA%/Factorio)
```

## Gerar o .exe

```powershell
.\build.ps1                       # roda os testes e gera dist\FactorioModpackLauncher\FactorioModpackLauncher.exe
```

## Uso rápido

1. **Configurações → Detectar automaticamente** (ou “Adicionar manualmente” apontando a pasta do Factorio).
2. **Biblioteca** → cards de perfis (clique para abrir o painel lateral; estrela favorita; busca/filtros/ordenação) → **Novo perfil** (vazio, importando a pasta de mods atual por cópia, ou duplicando outro perfil).
3. Em **Detalhes** do perfil: instale ZIPs, ative/desative mods, fixe versões, faça backup, exporte a lista de mods.
4. **Explorar Mods**: com usuário+token em Configurações a busca é a oficial do Portal, com filtros por tag na lateral e comandos
   no buscador (`$trains`, `$trains $logistics`, `-$combat`, `cargo $trains`; digite `$` para autocompletar). Sem login, o catálogo
   local (baixado 1×/dia) permite busca por texto. Escolha a versão, escolha a versão e instale no perfil (precisa de usuário + token
   do Mod Portal em Configurações; sem isso, o download fica “requer autenticação” e o resto segue funcionando).
5. **JOGAR**.

Veja [docs/STATUS.md](docs/STATUS.md) para o estado real das funcionalidades e o que foi validado.

## Banners dos perfis
Editar → Alterar banner: imagens oficiais do Factorio (baixadas do site oficial para o seu cache local, ver
[assets/README.md](assets/README.md)), imagem do seu computador ou padrão. Nada da Wube vem embutido no launcher.
