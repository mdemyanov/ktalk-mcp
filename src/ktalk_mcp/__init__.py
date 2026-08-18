"""MCP server for accessing Kontur Talk (KTalk) recordings, transcripts and summaries."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

try:
    # Единственный источник истины — метаданные установленного дистрибутива.
    # Литерал здесь разъехался с pyproject.toml в 0.8.0: дистрибутив был 0.8.0,
    # а `ktalk --version` печатал 0.7.0, и гейт совместимости плагина
    # (`installed_version()` в ktalk-onboard.sh читает именно его) браковал
    # заведомо совместимую установку.
    __version__ = _installed_version("ktalk-mcp")
except PackageNotFoundError:  # исходное дерево без установки
    __version__ = "0.0.0+source"
