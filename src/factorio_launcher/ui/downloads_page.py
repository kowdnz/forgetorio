from __future__ import annotations

from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..services.download_manager import AUTH, CANCELLED, DONE, FAILED, QUEUED, RUNNING
from .common import h1, muted


class DownloadsPage(QWidget):
    def __init__(self, ctx, win):
        super().__init__()
        self.ctx, self.win = ctx, win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 16)
        lay.addWidget(h1("Downloads"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Mod", "Perfil", "Estado", "Progresso", "Detalhes"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, fn in (("Tentar novamente", self.retry), ("Cancelar", self.cancel),
                         ("Limpar concluídos", self.clear_done), ("Ir para Configurações (login)", lambda: win.goto(win.settings))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.empty = muted("Nenhum download. Instale mods pelo Explorar Mods.")
        lay.addWidget(self.empty)
        self._row: dict[str, int] = {}

    def refresh(self) -> None:
        self.table.setRowCount(0)
        self._row.clear()
        for j in self.ctx.downloads.jobs:
            self.on_job(j)
        self.empty.setVisible(not self.ctx.downloads.jobs)

    def on_job(self, job) -> None:
        if job.id not in self._row:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._row[job.id] = r
            bar = QProgressBar()
            self.table.setCellWidget(r, 3, bar)
            prof = self.ctx.pm.get_profile(job.profile_id)
            self.table.setItem(r, 0, QTableWidgetItem(job.label))
            self.table.setItem(r, 1, QTableWidgetItem(prof.name if prof else "?"))
        r = self._row[job.id]
        self.table.setItem(r, 2, QTableWidgetItem(job.status))
        bar = self.table.cellWidget(r, 3)
        if job.total:
            bar.setMaximum(job.total)
            bar.setValue(job.done)
        else:
            bar.setMaximum(1)
            bar.setValue(1 if job.status == DONE else 0)
        self.table.setItem(r, 4, QTableWidgetItem(job.error))
        self.empty.setVisible(False)

    def _selected(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        inv = {v: k for k, v in self._row.items()}
        ids = {inv[r] for r in rows if r in inv}
        return [j for j in self.ctx.downloads.jobs if j.id in ids]

    def retry(self) -> None:
        for j in self._selected():
            self.ctx.downloads.retry(j)

    def cancel(self) -> None:
        for j in self._selected():
            if j.status in (RUNNING, QUEUED):
                j.cancel.set()
                if j.status == QUEUED:
                    j.status = CANCELLED
                    self.on_job(j)

    def clear_done(self) -> None:
        self.ctx.downloads.jobs[:] = [j for j in self.ctx.downloads.jobs if j.status not in (DONE, CANCELLED)]
        self.refresh()
