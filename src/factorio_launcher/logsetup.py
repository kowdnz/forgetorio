from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from . import paths

_SECRET = re.compile(r"(token|password|senha|secret)=[^&\s\"']+", re.I)
_SECRET_JSON = re.compile(r"(\"(?:service-token|token|password)\"\s*:\s*\")[^\"]*", re.I)


def redact(text: str) -> str:
    text = _SECRET.sub(lambda m: f"{m.group(1)}=***", text)
    return _SECRET_JSON.sub(lambda m: f"{m.group(1)}***", text)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def setup_logging() -> None:
    logger = logging.getLogger("fml")
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    d = paths.logs_dir()
    d.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(d / "launcher.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    h.addFilter(RedactFilter())
    logger.addHandler(h)
