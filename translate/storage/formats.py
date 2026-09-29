"""
Unified access to the supported localization storage formats.

This module is the single place that knows which storage formats exist and
how their specifics (file extensions, store classes, content detection) map
to actual implementations.  Callers use :func:`read` and :func:`write` and
do not need to know anything about the underlying format modules.

Adding support for a new format means registering a single
:class:`FormatAdapter` here; :mod:`translate.storage.factory` and everything
built on top of it picks it up automatically.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from io import BytesIO
from typing import TYPE_CHECKING, BinaryIO, overload

from translate.storage.base import TranslationStore

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "FormatAdapter",
    "adapters",
    "classes_str",
    "decompressclass",
    "get",
    "getclass",
    "hidden_classes",
    "read",
    "register",
    "register_examiner",
    "register_sniffer",
    "sniff",
    "supported_extensions",
    "write",
]

decompressclass = {
    "gz": ("gzip", "GzipFile"),
    "bz2": ("bz2", "BZ2File"),
}
"""Mapping of compression extensions to (module, class) for wrapped files."""


@lru_cache(maxsize=128)
def import_class(module_name, class_name, prefix=None):
    """Lazily import and return *class_name* from *module_name*."""
    if prefix:
        module_name = f"{prefix}.{module_name}"
    module = import_module(module_name)
    return getattr(module, class_name)


@dataclass(frozen=True)
class FormatAdapter:
    """
    Adapter encapsulating the specifics of a single storage format.

    The format specific logic (parsing, serialization, encoding and plural
    handling) stays in the store implementation; the adapter only knows how
    to locate and name it.
    """

    name: str
    """Canonical name of the format, for example ``po`` or ``xliff``."""
    module: str
    """Module within :mod:`translate.storage` providing the store class."""
    class_name: str
    """Name of the :class:`~translate.storage.base.TranslationStore` class."""
    extensions: tuple[str, ...] = ()
    """File extensions (without dot) associated with this format."""
    hidden: bool = False
    """Whether the format is a pseudo format not used as a real extension."""

    @property
    def store_class(self) -> type[TranslationStore]:
        """The lazily imported store class implementing this format."""
        return import_class(self.module, self.class_name, "translate.storage")

    def read(self, source: str | BinaryIO) -> TranslationStore:
        """Read *source* (a filename or binary file object) as this format."""
        return self.store_class.parsefile(source)

    @overload
    def write(self, store: TranslationStore, target: None = None) -> bytes: ...

    @overload
    def write(self, store: TranslationStore, target: str | BinaryIO) -> None: ...

    def write(
        self, store: TranslationStore, target: str | BinaryIO | None = None
    ) -> bytes | None:
        """Write *store* to *target*, see :func:`write` for details."""
        return write(store, target)


_adapters: dict[str, FormatAdapter] = {}
_extensions: dict[str, FormatAdapter] = {}
_examiners: dict[str, Callable] = {}
_sniffers: list[tuple[Callable[[bytes], bool], str]] = []


def register(adapter: FormatAdapter) -> FormatAdapter:
    """Register *adapter*, making its format available through this module."""
    _adapters[adapter.name] = adapter
    if adapter.hidden:
        _extensions[adapter.name] = adapter
    for extension in adapter.extensions:
        _extensions[extension] = adapter
    return adapter


def register_examiner(extension: str, examiner: Callable) -> None:
    """
    Register a callback resolving the real format for *extension*.

    The examiner receives the file (name or object) and returns the format
    name or extension to use instead, for example for ``.txt`` files whose
    content can be one of several formats.
    """
    _examiners[extension] = examiner


def register_sniffer(predicate: Callable[[bytes], bool], extension: str) -> None:
    """
    Register a content based format detector.

    *predicate* receives the first bytes of a file and returns whether the
    content matches, in which case *extension* is used as its format.
    Sniffers are consulted in registration order.
    """
    _sniffers.append((predicate, extension))


def get(name: str) -> FormatAdapter:
    """Return the adapter registered for a format name or extension."""
    key = name.lower().lstrip(".")
    try:
        return _extensions[key]
    except KeyError:
        pass
    try:
        return _adapters[key]
    except KeyError:
        raise ValueError(f"Unknown format ({name})") from None


def adapters() -> tuple[FormatAdapter, ...]:
    """Return all registered format adapters."""
    return tuple(_adapters.values())


def supported_extensions() -> list[str]:
    """Return the sorted real extensions of all registered formats."""
    return sorted({ext for adapter in _adapters.values() for ext in adapter.extensions})


def classes_str() -> dict[str, tuple[str, str]]:
    """Return the extension to (module, class) mapping (legacy factory API)."""
    return {
        key: (adapter.module, adapter.class_name)
        for key, adapter in _extensions.items()
    }


def hidden_classes() -> dict[str, Callable]:
    """Return the extension to examiner mapping (legacy factory API)."""
    return dict(_examiners)


def sniff(start: bytes) -> str:
    """Guess the format extension from the first bytes of a file."""
    for predicate, extension in _sniffers:
        if predicate(start):
            return extension
    raise ValueError("Failed to guess file type.")


def _examine_txt(storefile):
    """Determine the true filetype for a .txt file."""
    if isinstance(storefile, str) and os.path.exists(storefile):
        storefile = open(storefile, "rb")
    try:
        start = storefile.read(600)
    except AttributeError:
        raise ValueError("Need to read object to determine type") from None
    # Some encoding magic for Wordfast
    # pylint: disable-next=import-outside-toplevel
    from translate.storage import wordfast  # ruff:ignore[import-outside-top-level]

    encoding = wordfast.detect_encoding(start)
    start = start.decode(encoding)
    if "%Wordfast TM" in start:
        pseudo_extension = "_wftm"
    elif "<RTF Preamble>" in start:
        pseudo_extension = "_trados_txt_tm"
    else:
        raise ValueError("Failed to guess file type.")
    storefile.seek(0)
    return pseudo_extension


def _is_wordfast(content: bytes) -> bool:
    """Detect Wordfast content using its supported encodings."""
    # pylint: disable-next=import-outside-toplevel
    from translate.storage import wordfast  # ruff:ignore[import-outside-top-level]

    try:
        return "%Wordfast TM" in content.decode(wordfast.detect_encoding(content))
    except UnicodeDecodeError:
        return False


def _guess_extension(storefile):
    """
    Guesses the type of a file object by looking at the first few
    characters.  The return value is a file extension.
    """
    start = storefile.read(600)
    extension = sniff(start)
    storefile.seek(0)
    return extension


def _get_dummy_name(storefile) -> str:
    """
    Provides a dummy name for a file object without a name attribute, by
    guessing the file type.
    """
    return f"dummy.{_guess_extension(storefile)}"


def _get_name(storefile):
    """Returns the filename."""
    if storefile is None:
        raise ValueError(
            "This method cannot magically produce a filename when given None as input."
        )
    if not isinstance(storefile, str):
        if not hasattr(storefile, "name"):
            storefilename = _get_dummy_name(storefile)
        else:
            storefilename = storefile.name
    else:
        storefilename = storefile
    return storefilename


def _lookup_class(ext, classes, classes_str):
    # we prefer classes (if given) since that is the older API that Pootle uses
    if classes:
        return classes[ext]
    if classes_str is not None:
        return import_class(*classes_str[ext], "translate.storage")
    return _extensions[ext].store_class


def getclass(
    storefile,
    localfiletype=None,
    ignore=None,
    classes=None,
    classes_str=None,
    hiddenclasses=None,
):
    """
    Factory that returns the applicable class for the type of file
    presented.  Specify ignore to ignore some part at the back of the name
    (like .gz).
    """
    storefilename = _get_name(storefile)
    if hiddenclasses is None:
        hiddenclasses = _examiners
    if ignore and storefilename.endswith(ignore):
        storefilename = storefilename[: -len(ignore)]
    ext = localfiletype
    if ext is None:
        root, ext = os.path.splitext(storefilename)
        ext = ext[len(os.path.extsep) :].lower()
        decomp = None
        if ext in decompressclass:
            decomp = ext
            root, ext = os.path.splitext(root)
            ext = ext[len(os.path.extsep) :].lower()
        if ext in hiddenclasses:
            guesserfn = hiddenclasses[ext]
            if decomp:
                file = import_class(*decompressclass[decomp])
                ext = guesserfn(file(storefile))
            else:
                ext = guesserfn(storefile)
    try:
        return _lookup_class(ext, classes, classes_str)
    except KeyError:
        raise ValueError(f"Unknown filetype ({storefilename})") from None


def read(
    storefile: str | bytes | TranslationStore | BinaryIO,
    localfiletype: str | None = None,
    ignore: str | None = None,
    classes: dict | None = None,
    classes_str: dict | None = None,
    hiddenclasses: dict | None = None,
    format: str | FormatAdapter | None = None,
) -> TranslationStore:
    """
    Read *storefile* and return a store object for its format.

    :param storefile: File object, file name or an existing store, which is
        returned unchanged.
    :param format: Explicit format name, extension or :class:`FormatAdapter`
        to read *storefile* as, bypassing format detection.

    Specify ignore to ignore some part at the back of the name (like .gz).
    """
    if isinstance(storefile, TranslationStore):
        return storefile
    if format is not None:
        adapter = get(format) if isinstance(format, str) else format
        source = storefile
        if isinstance(source, (bytes, bytearray)):
            source = BytesIO(source)
        return adapter.read(source)
    if isinstance(storefile, str) and (
        os.path.isdir(storefile) or storefile.endswith(os.path.sep)
    ):
        raise ValueError(
            f'Cannot process directory "{storefile}" as a translation storage object. '
            "Please specify a path to a supported file instead."
        )
    storefilename = _get_name(storefile)
    storeclass = getclass(
        storefile,
        localfiletype,
        ignore,
        classes=classes,
        classes_str=classes_str,
        hiddenclasses=hiddenclasses,
    )
    if os.path.exists(storefilename) or not getattr(storefile, "closed", True):
        _name, ext = os.path.splitext(storefilename)
        ext = ext[len(os.path.extsep) :].lower()
        if ext in decompressclass:
            file = import_class(*decompressclass[ext])
            storefile = file(storefilename)
        store = storeclass.parsefile(storefile)
    else:
        store = storeclass()
        store.filename = storefilename
    return store


@overload
def write(store: TranslationStore, target: None = None) -> bytes: ...


@overload
def write(store: TranslationStore, target: str | os.PathLike | BinaryIO) -> None: ...


def write(
    store: TranslationStore, target: str | os.PathLike | BinaryIO | None = None
) -> bytes | None:
    """
    Serialize *store* to *target*.

    :param target: A file name or a binary file object to write to.  When
        omitted, the serialized content is returned as bytes.
    """
    if target is None:
        out = BytesIO()
        store.serialize(out)
        return out.getvalue()
    if isinstance(target, (str, os.PathLike)):
        with open(target, "wb") as out:
            store.serialize(out)
        return None
    store.serialize(target)
    return None


# The registry of supported formats.  This is the single source of truth for
# translate.storage.factory as well: adding a format here makes it available
# to all callers of the factory and of this module.
register(FormatAdapter("csv", "csvl10n", "csvfile", ("csv",)))
register(FormatAdapter("omegat-tab", "omegat", "OmegaTFileTab", ("tab",)))
register(FormatAdapter("omegat", "omegat", "OmegaTFile", ("utf8",)))
register(FormatAdapter("po", "po", "pofile", ("po", "pot")))
register(FormatAdapter("mo", "mo", "mofile", ("mo", "gmo")))
register(FormatAdapter("qm", "qm", "qmfile", ("qm",)))
register(FormatAdapter("lang", "mozilla_lang", "LangStore", ("lang",)))
register(FormatAdapter("utx", "utx", "UtxFile", ("utx",)))
register(FormatAdapter("_wftm", "wordfast", "WordfastTMFile", hidden=True))
register(FormatAdapter("_trados_txt_tm", "trados", "TradosTxtTmFile", hidden=True))
register(FormatAdapter("catkeys", "catkeys", "CatkeysFile", ("catkeys",)))
register(FormatAdapter("qph", "qph", "QphFile", ("qph",)))
register(FormatAdapter("tbx", "tbx", "tbxfile", ("tbx",)))
register(FormatAdapter("tmx", "tmx", "tmxfile", ("tmx",)))
register(FormatAdapter("ts", "ts2", "tsfile", ("ts",)))
register(FormatAdapter("xliff", "xliff", "Xliff1File", ("xliff", "xlf", "sdlxliff")))
register(FormatAdapter("ftl", "fluent", "FluentFile", ("ftl",)))
register(FormatAdapter("toml", "toml", "TOMLFile", ("toml",)))
register(FormatAdapter("wxl", "wxl", "WxlFile", ("wxl",)))

# Formats hiding behind a generic extension.
register_examiner("txt", _examine_txt)

# Content based detection for file objects without a name.  The order is
# significant, the first matching sniffer wins.
register_sniffer(lambda start: b"<xliff " in start, "xlf")
register_sniffer(lambda start: b'msgid "' in start, "po")
register_sniffer(_is_wordfast, "txt")
register_sniffer(lambda start: b"<!DOCTYPE TS>" in start, "ts")
register_sniffer(lambda start: b"<tmx " in start, "tmx")
register_sniffer(lambda start: b"#UTX" in start, "utx")
