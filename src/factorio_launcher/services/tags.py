"""Tags oficiais do Mod Portal + comandos `$tag` / `-$tag` do buscador.

Os 18 identificadores abaixo foram validados contra o servidor (POST /api/search recusa qualquer outro valor com
HTTP 400 "is not a valid choice"). Aliases só existem na interface; para a API sempre vai o identificador oficial.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tag:
    id: str
    label: str                       # nome exibido (PT-BR, como no Factorio localizado)
    aliases: tuple[str, ...] = ()


TAGS: tuple[Tag, ...] = (
    Tag("planets", "Planetas", ("planetas", "planet")),
    Tag("transportation", "Transporte", ("transporte", "transport", "veiculos", "vehicles")),
    Tag("logistics", "Logística", ("logistica", "logistic", "belts", "esteiras")),
    Tag("trains", "Trens", ("trem", "train", "trens", "rail", "ferrovia")),
    Tag("combat", "Combate", ("combate", "fight", "turrets")),
    Tag("armor", "Armadura", ("armadura", "armour")),
    Tag("character", "Personagem", ("personagem", "player", "jogador")),
    Tag("enemies", "Inimigos", ("inimigos", "enemy", "biters")),
    Tag("environment", "Ambiente", ("ambiente", "mapgen", "terrain", "terreno")),
    Tag("mining", "Mineração", ("mineracao", "miner", "ores")),
    Tag("fluids", "Fluidos", ("fluidos", "fluid", "oil", "oleo", "pipes")),
    Tag("logistic-network", "Rede de logística", ("rede-logistica", "robots", "roboports", "bots")),
    Tag("circuit-network", "Rede de circuito", ("rede-circuito", "circuit", "circuitos", "circuits")),
    Tag("manufacturing", "Manufatura", ("manufatura", "manufacture", "production", "producao", "crafting")),
    Tag("power", "Energia", ("energia", "electric", "eletricidade", "energy")),
    Tag("storage", "Armazenamento", ("armazenamento", "chests", "baus")),
    Tag("blueprints", "Projetos", ("projetos", "blueprint", "planta")),
    Tag("cheats", "Trapaças", ("trapacas", "cheat", "trapaca")),
)
BY_ID = {t.id: t for t in TAGS}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    return s.replace("_", "-").replace(" ", "-")


_EXACT: dict[str, str] = {}
for _t in TAGS:
    _EXACT[norm(_t.id)] = _t.id
    _EXACT[norm(_t.label)] = _t.id
    for _a in _t.aliases:
        _EXACT[norm(_a)] = _t.id


def resolve(token: str) -> str | None:
    """Identificador oficial para id/alias/nome (sem acento) ou prefixo único; None se desconhecido/ambíguo."""
    n = norm(token)
    if not n:
        return None
    if n in _EXACT:
        return _EXACT[n]
    hits = {t.id for t in TAGS if t.id.startswith(n)} | {_EXACT[k] for k in _EXACT if k.startswith(n)}
    return next(iter(hits)) if len(hits) == 1 else None


def suggest(prefix: str, exclude: set[str] | None = None) -> list[Tag]:
    """Tags cujo id, nome ou alias começa (ou contém) o prefixo digitado; prefixos primeiro."""
    n = norm(prefix)
    skip = exclude or set()
    starts, contains = [], []
    for t in TAGS:
        if t.id in skip:
            continue
        keys = [norm(t.id), norm(t.label), *map(norm, t.aliases)]
        if not n or any(k.startswith(n) for k in keys):
            starts.append(t)
        elif any(n in k for k in keys[:2]):   # "contém" só em id/nome, não em apelidos
            contains.append(t)
    return starts + contains


@dataclass
class ParsedSearch:
    text: str = ""
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    @property
    def has_tags(self) -> bool:
        return bool(self.include or self.exclude)


def parse_search(raw: str) -> ParsedSearch:
    """`cargo $trains $logistics -$combat` → texto 'cargo', include [trains, logistics], exclude [combat].
    Se a mesma tag aparece nos dois lados, vale a última ocorrência."""
    words, state = [], {}
    unknown = []
    for tok in raw.split():
        neg = tok.startswith("-$")
        if neg or tok.startswith("$"):
            name = tok[2:] if neg else tok[1:]
            if not name:
                continue  # "$" sozinho: usuário ainda digitando
            tid = resolve(name)
            if tid is None:
                unknown.append(name)
            else:
                state.pop(tid, None)
                state[tid] = neg
        else:
            words.append(tok)
    return ParsedSearch(" ".join(words), [t for t, neg in state.items() if not neg],
                        [t for t, neg in state.items() if neg], unknown)


def format_tokens(include: list[str], exclude: list[str]) -> list[str]:
    return [f"${t}" for t in include] + [f"-${t}" for t in exclude]


def replace_tag_tokens(raw: str, include: list[str], exclude: list[str]) -> str:
    """Remove os tokens $/-$ do texto e acrescenta os informados (usado pela barra lateral)."""
    keep = [w for w in raw.split() if not (w.startswith("$") or w.startswith("-$"))]
    return " ".join(keep + format_tokens(include, exclude)) + (" " if include or exclude else "")


def current_token(text: str, cursor: int) -> tuple[int, str]:
    """(início, token) sob o cursor."""
    start = text.rfind(" ", 0, cursor) + 1
    return start, text[start:cursor]
