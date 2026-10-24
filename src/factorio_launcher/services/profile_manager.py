"""CRUD de perfis, instalações e importações. Tudo dentro do diretório de dados do launcher."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from ..models.entities import SAVE_EXCLUSIVE, SAVE_SHARED, FactorioInstall, ModInfo, Profile
from ..persistence.jsonstore import load_json, save_json
from ..models.versions import parse_dependencies
from . import config_manager, install_detector, local_mods
from .asset_service import AssetError, AssetService
from .local_mods import ModError


class ProfileError(Exception):
    pass


@dataclass
class ProfileSummary:
    """Números exibidos nos cards (cacheados por mtime para a Biblioteca ficar rápida com muitos perfis)."""
    mods: int = 0
    enabled: int = 0
    saves: int = 0


class ProfileManager:
    def __init__(self, data_dir: Path | None = None, system_factorio: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else paths.data_dir()
        self.profiles_root = self.data_dir / "profiles"
        # %APPDATA%/Factorio: usado somente como LEITURA (modelo de config / importação).
        self.system_factorio = Path(system_factorio) if system_factorio else paths.system_factorio_dir()
        self.profiles_root.mkdir(parents=True, exist_ok=True)
        self.assets = AssetService(self.data_dir)
        self._summary_cache: dict[str, tuple[tuple, ProfileSummary]] = {}
        self._mods_cache: dict[str, tuple[tuple, list[ModInfo]]] = {}

    # ---------- instalações ----------
    @property
    def _installs_file(self) -> Path:
        return self.data_dir / "installs.json"

    def list_installs(self) -> list[FactorioInstall]:
        return [FactorioInstall.from_dict(d) for d in load_json(self._installs_file).get("installs", [])]

    def _save_installs(self, installs: list[FactorioInstall]) -> None:
        save_json(self._installs_file, {"installs": [i.to_dict() for i in installs]})

    def add_install(self, inst: FactorioInstall) -> FactorioInstall:
        installs = self.list_installs()
        for i in installs:
            if Path(i.exe).resolve() == Path(inst.exe).resolve():
                i.version, i.build = inst.version, inst.build
                self._save_installs(installs)
                return i
        installs.append(inst)
        self._save_installs(installs)
        return inst

    def remove_install(self, install_id: str) -> None:
        if any(p.install_id == install_id for p in self.list_profiles()):
            raise ProfileError("Há perfis usando esta instalação.")
        self._save_installs([i for i in self.list_installs() if i.id != install_id])

    def get_install(self, install_id: str) -> FactorioInstall | None:
        return next((i for i in self.list_installs() if i.id == install_id), None)

    # ---------- perfis ----------
    def profile_root(self, profile_id: str) -> Path:
        root = (self.profiles_root / profile_id).resolve()
        if root.parent != self.profiles_root.resolve():
            raise ProfileError("ID de perfil inválido")
        return root

    def mods_dir(self, p: Profile) -> Path:
        return self.profile_root(p.id) / "mods"

    def config_file(self, p: Profile) -> Path:
        return self.profile_root(p.id) / "config" / "config.ini"

    def saves_dir(self, p: Profile) -> Path:
        return config_manager.write_data_dir(p, self.profile_root(p.id)) / "saves"

    def list_profiles(self) -> list[Profile]:
        out = []
        for d in sorted(self.profiles_root.iterdir()) if self.profiles_root.is_dir() else []:
            m = d / "manifest.json"
            if m.is_file():
                data = load_json(m)
                try:
                    out.append(Profile.from_dict(data["profile"] if "profile" in data else data))
                except (TypeError, KeyError):
                    continue
        return sorted(out, key=lambda p: p.name.lower())

    def get_profile(self, profile_id: str) -> Profile | None:
        return next((p for p in self.list_profiles() if p.id == profile_id), None)

    def save_profile(self, p: Profile) -> None:
        save_json(self.profile_root(p.id) / "manifest.json", {"profile": p.to_dict()})

    def _check_name(self, name: str, ignore_id: str = "") -> str:
        name = name.strip()
        if not name:
            raise ProfileError("Informe um nome para o perfil.")
        if any(p.name.lower() == name.lower() and p.id != ignore_id for p in self.list_profiles()):
            raise ProfileError(f"Já existe um perfil chamado “{name}”.")
        return name

    def regenerate_config(self, p: Profile, inherit_settings: bool = True) -> Path:
        inst = self.get_install(p.install_id)
        if inst is None:
            raise ProfileError("A instalação do Factorio deste perfil não está cadastrada.")
        return config_manager.write_profile_config(
            p, inst, self.profile_root(p.id), self.system_factorio / "config" / "config.ini", inherit_settings)

    def create_profile(self, name: str, install: FactorioInstall, save_mode: str = SAVE_EXCLUSIVE,
                       template: str = "empty", source: Profile | None = None, color: str = "#4f8cff",
                       shared_dir: str = "", copy_saves: bool = False) -> Profile:
        """template: 'empty' | 'duplicate' (requer source) | 'import_current' (mods da pasta do sistema)."""
        if save_mode not in (SAVE_SHARED, SAVE_EXCLUSIVE):
            raise ProfileError("Modo de saves inválido.")
        name = self._check_name(name)
        p = Profile.new(name, install_id=install.id, save_mode=save_mode, color=color, shared_dir=shared_dir)
        root = self.profile_root(p.id)
        try:
            (root / "mods").mkdir(parents=True)
            if template == "duplicate":
                if source is None:
                    raise ProfileError("Perfil de origem ausente.")
                self._copy_mods(self.mods_dir(source), root / "mods")
                p.pins = dict(source.pins)
                p.extra_args = list(source.extra_args)
                p.banner = source.banner
                src_banner = self.assets.custom_file(self.profile_root(source.id))
                if source.banner == "custom" and src_banner:
                    shutil.copy2(src_banner, root / src_banner.name)
                if copy_saves and source.save_mode == SAVE_EXCLUSIVE and save_mode == SAVE_EXCLUSIVE:
                    src_saves = self.saves_dir(source)
                    if src_saves.is_dir():
                        shutil.copytree(src_saves, root / "userdata" / "saves")
            else:
                local_mods.write_mod_list(root / "mods", local_mods.default_mod_list(
                    install_detector.installed_dlcs(install)))
            self.save_profile(p)
            self.regenerate_config(p)
        except BaseException:
            shutil.rmtree(root, ignore_errors=True)  # só a pasta recém-criada deste perfil
            raise
        return p

    @staticmethod
    def _copy_mods(src: Path, dst: Path) -> None:
        if src.is_dir():
            for item in src.iterdir():
                if item.is_dir():
                    shutil.copytree(item, dst / item.name)
                else:
                    shutil.copy2(item, dst / item.name)

    def duplicate_profile(self, source: Profile, new_name: str, copy_saves: bool = False) -> Profile:
        inst = self.get_install(source.install_id)
        if inst is None:
            raise ProfileError("A instalação do perfil de origem não está cadastrada.")
        return self.create_profile(new_name, inst, source.save_mode, "duplicate", source, source.color,
                                   source.shared_dir, copy_saves)

    def rename_profile(self, p: Profile, new_name: str) -> None:
        p.name = self._check_name(new_name, p.id)
        self.save_profile(p)

    def update_settings(self, p: Profile, **changes) -> None:
        mode_changed = "save_mode" in changes and changes["save_mode"] != p.save_mode
        for k, v in changes.items():
            setattr(p, k, v)
        self.save_profile(p)
        if mode_changed or "shared_dir" in changes or "install_id" in changes:
            self.regenerate_config(p)

    def delete_profile(self, p: Profile) -> None:
        """Remove SOMENTE a pasta do perfil dentro do diretório do launcher (incluindo saves exclusivos).
        Saves compartilhados e %APPDATA%/Factorio nunca são tocados."""
        root = self.profile_root(p.id)
        if root.parent != self.profiles_root.resolve() or not (root / "manifest.json").is_file():
            raise ProfileError("Pasta de perfil inesperada; exclusão cancelada.")
        shutil.rmtree(root)

    # ---------- personalização / metadados ----------
    def set_favorite(self, p: Profile, value: bool) -> None:
        p.favorite = value
        self.save_profile(p)

    def set_official_banner(self, p: Profile, image_id: str) -> None:
        if self.assets.image_path(image_id) is None:
            raise ProfileError("Essa imagem oficial ainda não foi baixada.")
        self.assets.remove_custom(self.profile_root(p.id))
        p.banner = f"official:{image_id}"
        self.save_profile(p)

    def import_banner(self, p: Profile, src: Path) -> None:
        try:
            self.assets.import_custom(self.profile_root(p.id), Path(src))
        except AssetError as e:
            raise ProfileError(str(e)) from e
        p.banner = "custom"
        self.save_profile(p)

    def reset_banner(self, p: Profile) -> None:
        self.assets.remove_custom(self.profile_root(p.id))
        p.banner = ""
        self.save_profile(p)

    def banner_file(self, p: Profile, thumb: bool = False) -> Path | None:
        return self.assets.banner_file(p.banner, p.id, self.profile_root(p.id), thumb)

    def update_appearance(self, p: Profile, name: str | None = None, color: str | None = None) -> None:
        if name is not None and name.strip() != p.name:
            p.name = self._check_name(name, p.id)
        if color:
            p.color = color
        self.save_profile(p)

    def add_play_time(self, profile_id: str, seconds: int) -> None:
        """Soma tempo de jogo medido pelo launcher (relê o manifesto para não sobrescrever mudanças recentes)."""
        p = self.get_profile(profile_id)
        if p and seconds > 0:
            p.play_seconds += int(seconds)
            self.save_profile(p)

    @staticmethod
    def _stamp(path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    def summary(self, p: Profile) -> ProfileSummary:
        mods_dir = self.mods_dir(p)
        key = (self._stamp(mods_dir), self._stamp(local_mods.mod_list_path(mods_dir)), self._stamp(self.saves_dir(p)))
        hit = self._summary_cache.get(p.id)
        if hit and hit[0] == key:
            return hit[1]
        mods = self.scan_mods_cached(p)
        s = ProfileSummary(len(mods), sum(m.enabled for m in mods), len(self.list_saves(p)))
        self._summary_cache[p.id] = (key, s)
        return s

    def scan_mods_cached(self, p: Profile) -> list[ModInfo]:
        mods_dir = self.mods_dir(p)
        key = (self._stamp(mods_dir), self._stamp(local_mods.mod_list_path(mods_dir)), tuple(sorted(p.pins.items())))
        hit = self._mods_cache.get(p.id)
        if hit and hit[0] == key:
            return hit[1]
        mods = local_mods.scan_mods(mods_dir, p.pins)
        self._mods_cache[p.id] = (key, mods)
        return mods

    def mod_icon(self, p: Profile, mod: ModInfo) -> Path | None:
        """thumbnail.png do mod, lido do ZIP sem extrair e guardado em cache; None se o mod não tem ícone."""
        if mod.is_dir:
            f = self.mods_dir(p) / mod.filename / "thumbnail.png"
            return f if f.is_file() else None
        dest = self.data_dir / "cache" / "modicons" / f"{mod.name}_{mod.version}.png"
        if dest.is_file():
            return dest
        data = local_mods.read_zip_thumbnail(self.mods_dir(p) / mod.filename)
        if not data:
            return None
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        except OSError:
            return None
        return dest

    def save_preview(self, save: Path) -> Path | None:
        """preview.jpg de dentro do ZIP do save (lido sem extrair tudo), guardado em cache por (caminho, mtime)."""
        import hashlib
        import zipfile
        try:
            st = save.stat()
        except OSError:
            return None
        key = hashlib.sha1(f"{save}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:20]
        dest = self.data_dir / "cache" / "savepreviews" / f"{key}.jpg"
        if dest.is_file():
            return dest
        try:
            with zipfile.ZipFile(save) as zf:
                for zi in zf.infolist():
                    parts = zi.filename.replace("\\", "/").split("/")
                    if len(parts) == 2 and parts[1].lower() == "preview.jpg" and ".." not in parts and 0 < zi.file_size <= 3_000_000:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(zf.read(zi))
                        return dest
        except (zipfile.BadZipFile, OSError):
            pass
        return None

    def toggle_problems(self, p: Profile, name: str, enable: bool) -> list[str]:
        """Motivos para NÃO alternar o mod com segurança (lista vazia = pode). Respeita dependências obrigatórias."""
        if name in ("base", "core"):
            return ["Os mods base não podem ser desabilitados."]
        mods = self.scan_mods_cached(p)
        by_name = {m.name: m for m in mods}
        problems: list[str] = []
        if not enable:
            for m in mods:
                if m.enabled and m.name != name and any(
                        d.is_required and d.name == name for d in parse_dependencies(m.dependencies)):
                    problems.append(f"{m.name} depende obrigatoriamente de {name}.")
        else:
            target = by_name.get(name)
            if target:
                for d in parse_dependencies(target.dependencies):
                    if (d.is_required and d.name not in ("base", "core", "elevated-rails", "quality", "space-age")
                            and not (d.name in by_name and by_name[d.name].enabled)):
                        problems.append(f"{name} exige {d.name}, que não está instalado/habilitado.")
                    if d.kind == "incompatible" and d.name in by_name and by_name[d.name].enabled:
                        problems.append(f"{name} é incompatível com {d.name}, que está habilitado.")
        return problems

    # ---------- mods ----------
    def scan_mods(self, p: Profile) -> list[ModInfo]:
        return local_mods.scan_mods(self.mods_dir(p), p.pins)

    def install_zip(self, p: Profile, zip_path: Path, overwrite: bool = False) -> ModInfo:
        return local_mods.install_zip(zip_path, self.mods_dir(p), overwrite)

    def import_system_mods(self, p: Profile, include_disabled: bool = True) -> tuple[list[str], list[str]]:
        """Copia ZIPs de %APPDATA%/Factorio/mods (somente leitura na origem) respeitando o mod-list de lá.
        Retorna (importados, ignorados_com_motivo)."""
        src_dir = self.system_factorio / "mods"
        if not src_dir.is_dir():
            raise ProfileError("A pasta de mods do sistema não existe.")
        src_states = local_mods.read_mod_list(src_dir)
        done, skipped = [], []
        for z in sorted(src_dir.glob("*.zip")):
            try:
                info = local_mods.read_zip_info(z)
                if not include_disabled and not src_states.get(info["name"], True):
                    skipped.append(f"{z.name}: desabilitado na origem")
                    continue
                m = self.install_zip(p, z)
                local_mods.set_enabled(self.mods_dir(p), m.name, src_states.get(m.name, True))
                done.append(z.name)
            except ModError as e:
                skipped.append(f"{z.name}: {e}")
        return done, skipped

    # ---------- exportar / importar manifesto de modpack ----------
    def export_modpack(self, p: Profile, dest: Path) -> None:
        """Lista de mods (nome/versão/estado/fixação) sem ZIPs de terceiros e sem credenciais."""
        states = local_mods.read_mod_list(self.mods_dir(p))
        mods = [{"name": m.name, "version": m.version, "enabled": m.enabled, "pinned": m.pinned}
                for m in self.scan_mods(p)]
        for n in ("base", "elevated-rails", "quality", "space-age"):
            if n in states and not any(x["name"] == n for x in mods):
                mods.append({"name": n, "version": "", "enabled": states[n], "pinned": False})
        save_json(dest, {"kind": "factorio-modpack", "name": p.name, "save_mode": p.save_mode,
                         "mods": mods}, backup=False)

    @staticmethod
    def read_modpack(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ProfileError(f"Arquivo de modpack ilegível: {e}") from e
        if not isinstance(data, dict) or data.get("kind") != "factorio-modpack" or not isinstance(data.get("mods"), list):
            raise ProfileError("Arquivo não é um manifesto de modpack válido.")
        return data

    def apply_modpack_states(self, p: Profile, data: dict) -> list[str]:
        """Aplica estados habilitado/desabilitado de mods já presentes. Devolve mods ausentes (a baixar/importar)."""
        installed = {m.name for m in self.scan_mods(p)} | {"base", "elevated-rails", "quality", "space-age"}
        states = local_mods.read_mod_list(self.mods_dir(p))
        missing = []
        for m in data["mods"]:
            if not isinstance(m, dict) or "name" not in m:
                continue
            if m["name"] in installed:
                states[m["name"]] = bool(m.get("enabled", True))
            else:
                missing.append(f"{m['name']} {m.get('version', '')}".strip())
            if m.get("pinned") and m.get("version"):
                p.pins[m["name"]] = m["version"]
        local_mods.write_mod_list(self.mods_dir(p), states)
        self.save_profile(p)
        return missing

    # ---------- saves ----------
    def list_saves(self, p: Profile) -> list[Path]:
        d = self.saves_dir(p)
        return sorted(d.glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True) if d.is_dir() else []
