"""Executa funções bloqueantes fora da thread da UI e devolve o resultado via sinais."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable, args: tuple):
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = _Signals()

    def run(self) -> None:
        try:
            res = self.fn(*self.args)
        except Exception as e:  # noqa: BLE001 — repassado à UI
            self._emit(self.signals.failed, e)
        else:
            self._emit(self.signals.done, res)

    @staticmethod
    def _emit(sig, value) -> None:
        try:
            sig.emit(value)
        except RuntimeError:   # janela já destruída (app encerrando)
            pass


_alive: set = set()


def run_async(fn: Callable, on_done: Callable | None = None, on_error: Callable | None = None, *args) -> None:
    task = _Task(fn, args)
    _alive.add(task)

    def finish(cb, val):
        _alive.discard(task)
        if cb:
            cb(val)

    task.signals.done.connect(lambda v: finish(on_done, v))
    task.signals.failed.connect(lambda e: finish(on_error, e))
    QThreadPool.globalInstance().start(task)
