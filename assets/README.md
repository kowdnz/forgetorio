# Assets do launcher

| Pasta | Conteúdo |
|---|---|
| `factorio/` | (vazia no repositório) imagens oficiais da Wube — **não embutidas**, ver abaixo |
| `launcher/` | (vazia) ícones da interface e placeholders são desenhados em código (`ui/icons.py`, `ui/imagecache.py`); o ícone do app fica em `src/factorio_launcher/assets/` |
| `manifest.json` | catálogo de URLs oficiais, fonte, autor e licença de cada imagem |

## Política de imagens oficiais do Factorio

- Fontes: capturas em <https://factorio.com/game/screenshots> (34), conteúdo do Space Age em
  <https://factorio.com/space-age/content> (8). Autor/titular: Wube Software Ltd.
- Permissão encontrada: o Presskit (<https://factorio.com/presskit>) diz *"You are welcome to use any of the assets,
  screenshots, and artwork, that you can find on our website"*, voltado a imprensa/criadores de conteúdo. Os Termos de Serviço
  (<https://factorio.com/terms-of-service>) afirmam que os assets de arte são © Wube e **não podem ser redistribuídos**.
- Como a autorização para redistribuir dentro de um software não é clara, **nenhuma imagem é copiada para este repositório
  nem para o `.exe`**. Em *Biblioteca → Editar/Alterar banner → "Baixar banners oficiais"* (ação explícita do usuário) o
  launcher baixa cada imagem uma única vez do CDN oficial para `%LOCALAPPDATA%\FactorioModpackLauncher\assets\factorio\`,
  reduzindo-a (1280 px + miniatura 480 px). Depois disso a Biblioteca não faz mais nenhuma requisição de imagem (sem hotlinking).
- Sem as imagens baixadas, os cards usam um banner industrial desenhado pelo próprio launcher.
- O manifesto local (com caminhos e SHA-256 do que foi baixado) é gravado em `<dados>/assets/manifest.json`.
- Quem tiver dúvida sobre o uso pode consultar press@factorio.com.
