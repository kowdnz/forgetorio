"""Fila de downloads/instalações (executa em threads; a UI observa via callbacks)."""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import local_mods
from .portal_client import AuthRequired, Cancelled, PortalClient, PortalError, PortalOffline, Release, copy_from_cache

log = logging.getLogger("fml.downloads")

QUEUED, RUNNING, DONE, FAILED, AUTH, CANCELLED = "na fila", "baixando", "concluído", "erro", "requer autenticação", "cancelado"


@dataclass
class DownloadJob:
    release: Release
    profile_id: str
    mods_dir: Path
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = QUEUED
    done: int = 0
    total: int = 0
    error: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)
    replaces: list = field(default_factory=list)   # ModInfo antigos removidos após sucesso (atualização)

    @property
    def label(self) -> str:
        return f"{self.release.name} {self.release.version}"


class DownloadManager:
    """Executa um job por vez (conservador com o Portal). `notify` pode ser chamado de outra thread."""

    def __init__(self, client: PortalClient, get_credentials: Callable[[], tuple[str, str] | None],
                 notify: Callable[[DownloadJob], None] | None = None, synchronous: bool = False):
        self.client, self._creds, self._notify = client, get_credentials, notify or (lambda j: None)
        self.jobs: list[DownloadJob] = []
        self._lock = threading.Lock()
        self._sync = synchronous
        self._worker: threading.Thread | None = None

    def enqueue(self, release: Release, profile_id: str, mods_dir: Path, replaces: list | None = None) -> DownloadJob:
        job = DownloadJob(release, profile_id, mods_dir, replaces=list(replaces or []))
        with self._lock:
            self.jobs.append(job)
        self._notify(job)
        if self._sync:
            self._run_job(job)
        else:
            self._ensure_worker()
        return job

    def retry(self, job: DownloadJob) -> None:
        if job.status in (FAILED, AUTH, CANCELLED):
            job.status, job.error, job.done, job.total = QUEUED, "", 0, 0
            job.cancel.clear()
            self._notify(job)
            if self._sync:
                self._run_job(job)
            else:
                self._ensure_worker()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._loop, daemon=True, name="downloads")
            self._worker.start()

    def _loop(self) -> None:
        while True:
            with self._lock:
                job = next((j for j in self.jobs if j.status == QUEUED), None)
            if job is None:
                return
            self._run_job(job)

    def _run_job(self, job: DownloadJob) -> None:
        job.status = RUNNING
        self._notify(job)

        def progress(done: int, total: int) -> None:
            job.done, job.total = done, total
            self._notify(job)

        try:
            cached = self.client.download(job.release, self._creds(), progress, job.cancel)
            copy_from_cache(cached, job.mods_dir)
            states = local_mods.read_mod_list(job.mods_dir)
            states.setdefault(job.release.name, True)
            local_mods.write_mod_list(job.mods_dir, states)
            for old in job.replaces:
                if old.filename != cached_name(job.release):
                    local_mods.remove_mod(job.mods_dir, old)
            states = local_mods.read_mod_list(job.mods_dir)
            states.setdefault(job.release.name, True)
            local_mods.write_mod_list(job.mods_dir, states)
            job.status = DONE
        except AuthRequired as e:
            job.status, job.error = AUTH, str(e)
        except Cancelled:
            job.status, job.error = CANCELLED, "Cancelado pelo usuário."
        except PortalOffline as e:
            job.status, job.error = FAILED, f"{e} Tente novamente quando houver conexão."
        except (PortalError, local_mods.ModError, OSError) as e:
            job.status, job.error = FAILED, str(e)
        log.info("Download %s: %s %s", job.label, job.status, job.error)
        self._notify(job)


def cached_name(release: Release) -> str:
    return local_mods.mod_filename(release.name, release.version)
