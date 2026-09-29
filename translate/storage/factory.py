#
# Copyright 2006-2010 Zuza Software Foundation
#
# This file is part of translate.
#
# translate is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# translate is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <https://www.gnu.org/licenses/>.

"""
Factory methods to build real storage objects that conform to base.py.

.. note::

   This module is a compatibility shim over
   :mod:`translate.storage.formats`, the unified registry of supported
   storage formats.  New code should use ``translate.storage.formats``
   directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO

from translate.storage import formats
from translate.storage.formats import decompressclass, import_class

if TYPE_CHECKING:
    from translate.storage.base import TranslationStore

__all__ = ("decompressclass", "getclass", "getobject", "import_class")

# TODO: Monolingual formats (with template?)

_classes_str = formats.classes_str()
###  XXX:  if you add anything here, you must also add it to translate.storage.

"""Dictionary of file extensions and the names of their associated class.

Used for dynamic lazy loading of modules.
_ext is a pseudo extension, that is their is no real extension by that name.
"""

_hiddenclasses = formats.hidden_classes()


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
    return formats.getclass(
        storefile,
        localfiletype,
        ignore,
        classes=classes,
        classes_str=classes_str,
        hiddenclasses=hiddenclasses,
    )


def getobject(
    storefile: str | TranslationStore | BinaryIO,
    localfiletype: str | None = None,
    ignore: str | None = None,
    classes: dict | None = None,
    classes_str: dict | None = None,
    hiddenclasses: dict | None = None,
) -> TranslationStore:
    """
    Factory that returns a usable object for the type of file presented.
    :param storefile: File object or file name.

    Specify ignore to ignore some part at the back of the name (like .gz).
    """
    return formats.read(
        storefile,
        localfiletype,
        ignore,
        classes=classes,
        classes_str=classes_str,
        hiddenclasses=hiddenclasses,
    )


supported = [
    (
        "Gettext PO file",
        ["po", "pot"],
        [
            "text/x-gettext-catalog",
            "text/x-gettext-translation",
            "text/x-po",
            "text/x-pot",
        ],
    ),
    (
        "XLIFF Translation File",
        ["xlf", "xliff", "sdlxliff"],
        ["application/x-xliff", "application/x-xliff+xml"],
    ),
    (
        "Gettext MO file",
        ["mo", "gmo"],
        ["application/x-gettext-catalog", "application/x-mo"],
    ),
    ("Qt .qm file", ["qm"], ["application/x-qm"]),
    ("TBX Glossary", ["tbx"], ["application/x-tbx"]),
    ("TMX Translation Memory", ["tmx"], ["application/x-tmx"]),
    ("Qt Linguist Translation File", ["ts"], ["application/x-linguist"]),
    ("Qt Phrase Book", ["qph"], ["application/x-qph"]),
    ("OmegaT Glossary", ["utf8", "tab"], ["application/x-omegat-glossary"]),
    ("UTX Dictionary", ["utx"], ["text/x-utx"]),
    ("Haiku catkeys file", ["catkeys"], ["application/x-catkeys"]),
    ("Fluent file", ["ftl"], []),
    ("WiX Localization File", ["wxl"], ["text/xml"]),
]


def supported_files() -> list[tuple[str, list[str], list[str]]]:
    """
    Returns data about all supported files.

    :return: list of type that include (name, extensions, mimetypes)
    """
    return supported[:]
