"""Tests for the unified format adapter layer in translate.storage.formats."""

from gzip import GzipFile
from io import BytesIO

import pytest

from translate.storage import factory, formats, po, wordfast, xliff

PO_CONTENT = b"""#: test.c
msgid "test"
msgstr "rest"
"""

WORDFAST_CONTENT = (
    b"""%20070801~103212\t%User ID,S,S SMURRAY,SMS Samuel Murray-Smit,SM Samuel Murray-Smit,MW Mary White,DS Deepak Shota,MT! Machine translation (15),AL! Alignment (10),SM Samuel Murray,\t%TU=00000075\t%AF-ZA\t%Wordfast TM v.5.51r/00\t%EN-ZA\t%---80597535\tSubject (5),EL,EL Electronics,AC Accounting,LE Legal,ME Mechanics,MD Medical,LT Literary,AG Agriculture,CO Commercial\tClient (5),LS,LS LionSoft Corp,ST SuperTron Inc,CA CompArt Ltd\t\t\t"""
    b"""20070801~103248\tSM\t0\tAF-ZA\tLangeraad en duimpie\tEN-ZA\tBig Ben and Little John\tEL\tLS"""
)


def givefile(filename, content):
    """Returns a file dummy object with the given content."""
    file = BytesIO(content)
    file.name = filename
    return file


class TestRegistry:
    def test_matches_legacy_factory(self) -> None:
        """The registry is the single source of truth for the factory."""
        for ext, (module, class_name) in factory._classes_str.items():
            adapter = formats.get(ext)
            assert (adapter.module, adapter.class_name) == (module, class_name)
        for adapter in formats.adapters():
            for ext in adapter.extensions:
                assert ext in factory._classes_str
            if adapter.hidden:
                assert adapter.name in factory._classes_str

    def test_get_by_name_and_extension(self) -> None:
        assert formats.get("po") is formats.get("pot")
        assert formats.get("po") is formats.get(".PO")
        assert formats.get("xliff") is formats.get("xlf")
        assert formats.get("xliff") is formats.get("sdlxliff")
        assert formats.get("tab") is formats.get("omegat-tab")

    def test_get_unknown(self) -> None:
        with pytest.raises(ValueError, match="Unknown format"):
            formats.get("nosuchformat")

    def test_supported_extensions(self) -> None:
        extensions = formats.supported_extensions()
        assert "po" in extensions
        assert "xliff" in extensions
        # Hidden pseudo formats are not real extensions
        assert "_wftm" not in extensions
        assert "_trados_txt_tm" not in extensions

    def test_hidden_formats(self) -> None:
        assert formats.get("_wftm").store_class is wordfast.WordfastTMFile
        adapter = formats.get("_trados_txt_tm")
        assert (adapter.module, adapter.class_name) == ("trados", "TradosTxtTmFile")

    def test_store_class_lazy(self) -> None:
        assert formats.get("po").store_class is po.pofile
        assert formats.get("xliff").store_class is xliff.Xliff1File


class TestSniff:
    @pytest.mark.parametrize(
        ("content", "extension"),
        [
            (b'<?xml version="1.0"?>\n<xliff version="1.1">', "xlf"),
            (PO_CONTENT, "po"),
            (WORDFAST_CONTENT, "txt"),
            (b"<!DOCTYPE TS>", "ts"),
            (b'<tmx version="1.4">', "tmx"),
            (b"#UTX 1.0", "utx"),
        ],
    )
    def test_sniff(self, content, extension) -> None:
        assert formats.sniff(content) == extension

    def test_sniff_unknown(self) -> None:
        with pytest.raises(ValueError, match="Failed to guess"):
            formats.sniff(b"random content")


class TestRead:
    def test_read_from_path(self, tmp_path) -> None:
        filename = tmp_path / "file.po"
        filename.write_bytes(PO_CONTENT)
        store = formats.read(str(filename))
        assert isinstance(store, po.pofile)
        assert store.units[0].source == "test"

    def test_read_from_fileobj(self) -> None:
        store = formats.read(givefile("dummy.po", PO_CONTENT))
        assert isinstance(store, po.pofile)

    def test_read_without_name(self) -> None:
        """Format is detected from content when the file object has no name."""
        store = formats.read(BytesIO(PO_CONTENT))
        assert isinstance(store, po.pofile)

    def test_read_explicit_format(self) -> None:
        store = formats.read(BytesIO(PO_CONTENT), format="po")
        assert isinstance(store, po.pofile)
        store = formats.read(PO_CONTENT, format=formats.get("po"))
        assert isinstance(store, po.pofile)

    def test_read_passthrough(self) -> None:
        store = formats.read(BytesIO(PO_CONTENT), format="po")
        assert formats.read(store) is store

    def test_read_directory(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="Cannot process directory"):
            formats.read(str(tmp_path))

    def test_read_unknown_extension(self) -> None:
        with pytest.raises(ValueError, match="Unknown filetype"):
            formats.read("file.nosuchformat")

    def test_read_gzip(self, tmp_path) -> None:
        filename = tmp_path / "file.po.gz"
        with GzipFile(str(filename), mode="wb") as gzfile:
            gzfile.write(PO_CONTENT)
        store = formats.read(str(filename))
        assert isinstance(store, po.pofile)

    def test_read_wordfast_txt(self) -> None:
        """The txt examiner resolves the hidden Wordfast format."""
        store = formats.read(givefile("dummy.txt", WORDFAST_CONTENT))
        assert isinstance(store, wordfast.WordfastTMFile)


class TestWrite:
    def test_write_bytes(self) -> None:
        store = formats.read(BytesIO(PO_CONTENT), format="po")
        data = formats.write(store)
        assert b'msgid "test"' in data
        roundtrip = formats.read(BytesIO(data), format="po")
        assert roundtrip.units[0].source == "test"
        assert roundtrip.units[0].target == "rest"

    def test_write_to_path(self, tmp_path) -> None:
        store = formats.read(BytesIO(PO_CONTENT), format="po")
        filename = tmp_path / "out.po"
        assert formats.write(store, str(filename)) is None
        assert b'msgid "test"' in filename.read_bytes()

    def test_write_to_fileobj(self) -> None:
        store = formats.read(BytesIO(PO_CONTENT), format="po")
        out = BytesIO()
        assert formats.write(store, out) is None
        assert b'msgid "test"' in out.getvalue()

    def test_adapter_read_write(self) -> None:
        adapter = formats.get("po")
        store = adapter.read(givefile("dummy.po", PO_CONTENT))
        assert isinstance(store, po.pofile)
        assert b'msgid "test"' in adapter.write(store)


class TestFactoryShim:
    def test_getclass(self) -> None:
        assert factory.getclass("file.po") is po.pofile
        assert factory.getclass("file.po.gz") is po.pofile

    def test_getobject(self) -> None:
        store = factory.getobject(givefile("dummy.po", PO_CONTENT))
        assert isinstance(store, po.pofile)
        assert factory.getobject(store) is store
