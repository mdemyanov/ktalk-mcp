"""Единственная точка входа указателя: сказать, куда переехало, и выйти ненулём.

Ненулевой код возврата — не грубость, а контракт: скрипт, вызвавший старое имя
в автоматизации, обязан заметить переезд, а не продолжить как ни в чём не бывало.
"""

from __future__ import annotations

import sys
import warnings

from . import REPLACEMENT, __version__

MESSAGE = f"""\
Пакет `ktalk-mcp` больше не развивается: продукт переехал в `{REPLACEMENT}`.

MCP-поверхность снята целиком — остался CLI `ktalk`, тот же по составу команд.

  uv tool install {REPLACEMENT}

Если на этой машине ещё стоит старый `ktalk-mcp`, снимите его перед установкой:
два пакета не могут владеть одним именем команды, и установка откажет.

  uv tool uninstall ktalk-mcp
  uv tool install {REPLACEMENT}
"""


def main() -> int:
    warnings.warn(
        f"ktalk-mcp {__version__} — пакет-указатель; продукт переехал в {REPLACEMENT}",
        DeprecationWarning,
        stacklevel=2,
    )
    print(MESSAGE, file=sys.stderr, end="")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
