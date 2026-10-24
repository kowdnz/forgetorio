"""Resolução de dependências obrigatórias/transitivas, incompatibilidades, versões e DLC.

Conservador: nunca decide silenciosamente. O resultado (Plan) lista o que seria instalado, avisos e
problemas; a UI exige confirmação e, havendo problemas (issues), nada é instalado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..models.entities import ModInfo
from ..models.versions import (DLC_MODS, Dependency, Version, fmt_version, parse_dependencies, parse_dependency,
                               parse_version)
from .portal_client import Release, game_compat

FetchReleases = Callable[[str], list[Release]]


@dataclass
class Plan:
    to_install: list[Release] = field(default_factory=list)
    to_replace: list[tuple[str, str, str]] = field(default_factory=list)  # (mod, versão atual, nova)
    issues: list[str] = field(default_factory=list)      # bloqueiam a instalação
    warnings: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def report(self) -> str:
        lines = []
        if self.to_install:
            lines.append("Será instalado:")
            lines += [f"  • {r.name} {r.version}" for r in self.to_install]
        if self.to_replace:
            lines.append("Substitui versões instaladas:")
            lines += [f"  • {n}: {a} → {b}" for n, a, b in self.to_replace]
        if self.optional:
            lines.append("Dependências opcionais (não instaladas): " + ", ".join(self.optional))
        if self.warnings:
            lines.append("Avisos:")
            lines += [f"  ⚠ {w}" for w in self.warnings]
        if self.issues:
            lines.append("PROBLEMAS (nada será instalado):")
            lines += [f"  ✖ {i}" for i in self.issues]
        return "\n".join(lines)


def _vt(v: str) -> Version:
    return parse_version(v) or (0, 0, 0)


def check_profile(installed: list[ModInfo], game_version: str, dlcs: list[str]) -> list[str]:
    """Diagnóstico do perfil: dependências faltando/incompatíveis entre mods HABILITADOS."""
    problems: list[str] = []
    enabled = {m.name: m for m in installed if m.enabled}
    gv = parse_version(game_version)
    for m in enabled.values():
        deps = parse_dependencies(m.dependencies)
        for d in deps:
            if d.kind == "required":
                if d.name in ("base", "core"):
                    if not d.accepts(gv):
                        problems.append(f"{m.name}: exige {d.name} {d.constraint_text()}, o jogo é {game_version}")
                elif d.name in DLC_MODS:
                    if d.name not in dlcs:
                        problems.append(f"{m.name}: exige a DLC {d.name}, que não está instalada")
                elif d.name not in enabled:
                    problems.append(f"{m.name}: dependência obrigatória ausente/desabilitada: {d.name}")
                elif not d.accepts(_vt(enabled[d.name].version)):
                    problems.append(f"{m.name}: exige {d.name} {d.constraint_text()}, instalado {enabled[d.name].version}")
            elif d.kind == "incompatible" and d.name in enabled and d.accepts(_vt(enabled[d.name].version)):
                problems.append(f"{m.name} é incompatível com {d.name}")
        if m.factorio_version and game_compat(m.factorio_version, game_version) == "no":
            problems.append(f"{m.name}: feito para Factorio {m.factorio_version}, o jogo é {game_version}")
    return problems


def resolve_install(target: Release, installed: list[ModInfo], game_version: str, dlcs: list[str],
                    fetch_releases: FetchReleases, pins: dict[str, str] | None = None,
                    max_mods: int = 60) -> Plan:
    pins = pins or {}
    plan = Plan()
    gv = parse_version(game_version)
    have = {m.name: m for m in installed}
    chosen: dict[str, tuple[Version, Release | None]] = {n: (_vt(m.version), None) for n, m in have.items()}
    constraints: dict[str, list[tuple[str, Dependency]]] = {}
    chosen_releases: dict[str, Release] = {}

    if game_compat(target.factorio_version, game_version) == "no":
        plan.issues.append(f"{target.name} {target.version} é para Factorio {target.factorio_version}; "
                           f"a instalação é {game_version}.")
        return plan

    def add_release(rel: Release, replacing: bool) -> None:
        if replacing and rel.name in have:
            plan.to_replace.append((rel.name, have[rel.name].version, rel.version))
        plan.to_install.append(rel)
        chosen[rel.name] = (_vt(rel.version), rel)
        chosen_releases[rel.name] = rel

    add_release(target, target.name in have and have[target.name].version != target.version)
    queue = [target]
    seen_pairs: set[tuple[str, str]] = set()
    while queue:
        if len(plan.to_install) > max_mods:
            plan.issues.append("Árvore de dependências grande demais; operação interrompida.")
            return plan
        rel = queue.pop(0)
        if (rel.name, rel.version) in seen_pairs:
            continue
        seen_pairs.add((rel.name, rel.version))
        deps = parse_dependencies(rel.dependencies)
        if len(deps) != len(rel.dependencies):
            plan.warnings.append(f"{rel.name} {rel.version}: dependência(s) com sintaxe inválida ignorada(s): "
                                 + ", ".join(x for x in rel.dependencies if parse_dependency(x) is None))
        for d in deps:
            if d.kind in ("optional", "hidden_optional"):
                if d.name not in chosen and d.name not in plan.optional and d.name not in DLC_MODS:
                    plan.optional.append(d.name)
                continue
            if d.kind == "no_order":
                continue
            if d.kind == "incompatible":
                if d.name in chosen and d.accepts(chosen[d.name][0]):
                    plan.issues.append(f"{rel.name} {rel.version} é incompatível com {d.name} "
                                       f"({fmt_version(chosen[d.name][0])}) já presente")
                constraints.setdefault(d.name, []).append((rel.name, d))
                continue
            # obrigatória
            if d.name in ("base", "core"):
                if not d.accepts(gv):
                    plan.issues.append(f"{rel.name}: exige {d.name} {d.constraint_text()}; jogo {game_version}")
                continue
            if d.name in DLC_MODS:
                if d.name not in dlcs:
                    plan.issues.append(f"{rel.name}: exige a DLC {d.name}, que não está instalada no jogo")
                continue
            constraints.setdefault(d.name, []).append((rel.name, d))
            cur = chosen.get(d.name)
            if cur and all(c.accepts(cur[0]) for _, c in constraints[d.name] if c.kind == "required"):
                continue
            # precisa instalar/atualizar
            if d.name in pins and d.name in have:
                plan.issues.append(f"{rel.name} exige {d.name} {d.constraint_text()}, mas {d.name} está fixado "
                                   f"na versão {pins[d.name]}. Remova a fixação para atualizar.")
                continue
            try:
                options = fetch_releases(d.name)
            except Exception as e:  # noqa: BLE001 — erro de rede/portal vira problema explícito
                plan.issues.append(f"Não foi possível consultar {d.name} no Portal: {e}")
                continue
            reqs = [c for _, c in constraints[d.name] if c.kind == "required"]
            incs = [c for _, c in constraints[d.name] if c.kind == "incompatible"]
            good = [r for r in options
                    if game_compat(r.factorio_version, game_version) != "no"
                    and all(c.accepts(_vt(r.version)) for c in reqs)
                    and not any(c.accepts(_vt(r.version)) for c in incs)]
            if not good:
                plan.issues.append(f"Nenhuma versão de {d.name} atende às restrições "
                                   f"({', '.join(f'{c.constraint_text() or "qualquer"} por {o}' for o, c in constraints[d.name])}) "
                                   f"para Factorio {game_version}.")
                continue
            pick = max(good, key=lambda r: _vt(r.version))
            add_release(pick, d.name in have)
            queue.append(pick)
    # revalida incompatibilidades acumuladas contra tudo que ficará presente
    for name, lst in constraints.items():
        if name in chosen:
            for owner, c in lst:
                if c.kind == "incompatible" and c.accepts(chosen[name][0]):
                    msg = f"{owner} é incompatível com {name} {fmt_version(chosen[name][0])}"
                    if msg not in plan.issues and not any(msg.split(" (")[0] in i for i in plan.issues):
                        plan.issues.append(msg)
    # mods já instalados e habilitados que declaram incompatibilidade com o que vamos instalar
    for m in installed:
        if not m.enabled:
            continue
        for d in parse_dependencies(m.dependencies):
            if d.kind == "incompatible" and d.name in chosen_releases and d.accepts(_vt(chosen_releases[d.name].version)):
                plan.issues.append(f"{m.name} (instalado) é incompatível com {d.name} {chosen_releases[d.name].version}")
    for r in plan.to_install:
        gc = game_compat(r.factorio_version, game_version)
        if gc == "maybe":
            plan.warnings.append(f"{r.name} {r.version} declara Factorio {r.factorio_version}; "
                                 f"pode não funcionar corretamente no {game_version}.")
    if plan.to_replace:
        plan.warnings.append("Atualizar mods pode tornar saves existentes incompatíveis; considere um backup.")
    return plan
