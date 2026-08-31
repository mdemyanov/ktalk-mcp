"""CLI for accessing Kontur Talk (KTalk) recordings, transcripts and summaries."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import metadata as _installed_metadata
from importlib.metadata import version as _installed_version

try:
    # Единственный источник истины — метаданные установленного дистрибутива.
    # Литерал здесь разъехался с pyproject.toml в 0.8.0: дистрибутив был 0.8.0,
    # а `ktalk --version` печатал 0.7.0, и гейт совместимости плагина
    # (`installed_version()` в ktalk-onboard.sh читает именно его) браковал
    # заведомо совместимую установку.
    #
    # ADR-022 §7 (SA-001): та же логика — теперь и для имени дистрибутива, не
    # только версии. `__package__` — имя реального Python-пакета ("ktalk_cli"),
    # не набранная заново строка; `importlib.metadata` нормализует "-"/"_"/регистр
    # ключа поиска, так что он резолвится в тот же установленный дистрибутив,
    # что и дефисное имя "ktalk-cli" из pyproject.toml.
    __version__ = _installed_version(__package__)
    __dist_name__ = _installed_metadata(__package__)["Name"]
except PackageNotFoundError:  # исходное дерево без установки
    __version__ = "0.0.0+source"
    __dist_name__ = "ktalk-cli"  # заглушка: метаданных читать неоткуда
