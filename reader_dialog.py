from __future__ import annotations

import html as html_lib
import bisect
from datetime import datetime
import io
import json
import shutil
import posixpath
import re
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


SUPPORTED_BOOKS = {".txt", ".md", ".markdown", ".epub"}
CURRENT_BOOK_FILE = ".current_book.json"


def _library_books(library_dir: Path) -> list[Path]:
    library_dir.mkdir(parents=True, exist_ok=True)
    return sorted(
        (path for path in library_dir.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_BOOKS),
        key=lambda path: path.name.casefold(),
    )


def _current_book(library_dir: Path) -> Path | None:
    marker = library_dir / CURRENT_BOOK_FILE
    try:
        filename = json.loads(marker.read_text(encoding="utf-8")).get("filename", "")
    except (OSError, ValueError, AttributeError):
        return None
    candidate = library_dir / Path(filename).name
    if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_BOOKS:
        return candidate
    return None


def _set_current_book(library_dir: Path, path: Path | None) -> None:
    marker = library_dir / CURRENT_BOOK_FILE
    if path is None:
        try:
            marker.unlink()
        except FileNotFoundError:
            pass
        return
    marker.write_text(
        json.dumps({"filename": path.name}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class BookshelfManagerDialog(QDialog):
    """Manage the room library without opening the selected book."""

    currentBookChanged = Signal(str)

    def __init__(self, library_dir: Path, parent=None):
        super().__init__(parent)
        self.library_dir = Path(library_dir)
        self._paths: list[Path] = []
        self.setWindowTitle("小屋书架")
        self.resize(520, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(10)
        heading = QLabel("小屋书架")
        heading.setObjectName("readerHeading")
        subtitle = QLabel("这里负责收藏和整理书籍。选中一本设为当前阅读后，再点击书桌上的书开始阅读。")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("readerSubtitle")
        self.current_label = QLabel("当前阅读：尚未选择")
        self.current_label.setObjectName("currentBookLabel")
        self.book_list = QListWidget()
        self.book_list.itemDoubleClicked.connect(lambda _item: self._choose_current())
        root.addWidget(heading)
        root.addWidget(subtitle)
        root.addWidget(self.current_label)
        root.addWidget(self.book_list, 1)

        buttons = QHBoxLayout()
        add_button = QPushButton("放入书架")
        add_button.clicked.connect(self._import_books)
        choose_button = QPushButton("设为当前阅读")
        choose_button.clicked.connect(self._choose_current)
        delete_button = QPushButton("删除选中书籍")
        delete_button.setObjectName("dangerButton")
        delete_button.clicked.connect(self._delete_selected)
        buttons.addWidget(add_button)
        buttons.addWidget(choose_button)
        buttons.addWidget(delete_button)
        root.addLayout(buttons)

        self.setStyleSheet(
            """
            QDialog { background: #f7f0e2; color: #4f4741; }
            #readerHeading { font: 700 24px 'Microsoft YaHei UI'; color: #67564b; }
            #readerSubtitle { font: 13px 'Microsoft YaHei UI'; color: #81736a; }
            #currentBookLabel { background:#efe2cf; border-radius:9px; padding:8px 10px; }
            QListWidget { background:#fffaf1; border:1px solid #cdbba7; border-radius:12px; padding:8px; font:14px 'Microsoft YaHei UI'; }
            QPushButton { background:#eadbc5; border:1px solid #c8b39a; border-radius:10px; padding:8px 12px; }
            QPushButton:hover { background:#dfc9aa; }
            #dangerButton { color:#8b514e; }
            """
        )
        self.refresh()

    def refresh(self) -> None:
        selected = self.book_list.currentRow()
        self._paths = _library_books(self.library_dir)
        active = _current_book(self.library_dir)
        self.book_list.clear()
        for path in self._paths:
            prefix = "▶  " if path == active else "    "
            self.book_list.addItem(prefix + path.stem)
        self.current_label.setText(f"当前阅读：{active.stem}" if active else "当前阅读：尚未选择")
        if self._paths:
            self.book_list.setCurrentRow(min(max(0, selected), len(self._paths) - 1))

    def _choose_current(self) -> None:
        row = self.book_list.currentRow()
        if not 0 <= row < len(self._paths):
            QMessageBox.information(self, "还没有选择", "请先在书架中选中一本书。")
            return
        path = self._paths[row]
        _set_current_book(self.library_dir, path)
        self.refresh()
        self.currentBookChanged.emit(str(path))

    def _delete_selected(self) -> None:
        row = self.book_list.currentRow()
        if not 0 <= row < len(self._paths):
            return
        path = self._paths[row]
        answer = QMessageBox.question(
            self,
            "删除书籍",
            f"确定从小屋书架删除《{path.stem}》吗？\n这会删除书架中的副本，但不会删除原始来源文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if _current_book(self.library_dir) == path:
            _set_current_book(self.library_dir, None)
        try:
            path.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        self.refresh()
        self.currentBookChanged.emit("")

    def _import_books(self) -> None:
        sources, _ = QFileDialog.getOpenFileNames(
            self, "选择要放进小屋书架的文字书籍", str(Path.home()),
            "文字书籍 (*.txt *.md *.markdown *.epub)",
        )
        if not sources:
            return
        self.library_dir.mkdir(parents=True, exist_ok=True)
        imported: Path | None = None
        for source_name in sources:
            source = Path(source_name)
            target = self.library_dir / source.name
            index = 2
            while target.exists() and target.resolve() != source.resolve():
                target = self.library_dir / f"{source.stem}_{index}{source.suffix}"
                index += 1
            if target.resolve() != source.resolve():
                shutil.copy2(source, target)
            imported = target
        self.refresh()
        if imported in self._paths:
            self.book_list.setCurrentRow(self._paths.index(imported))


class BookReaderDialog(QDialog):
    """Read only the book selected on the room bookshelf."""

    def __init__(self, library_dir: Path, parent=None):
        super().__init__(parent)
        self.library_dir = Path(library_dir)
        self._paths: list[Path] = []
        self._current_path: Path | None = None
        self._epub_chapters: list[tuple[str, str]] = []
        self._current_chapter = -1
        self._page_offsets: list[int] = [0]
        self.setWindowTitle("桌前阅读")
        self.resize(850, 590)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(10)

        heading = QLabel("桌前阅读")
        heading.setObjectName("readerHeading")
        subtitle = QLabel(
            "这里只阅读书架中选好的那一本。可以滚轮阅读或整页翻阅，也可以随手记笔记、保存摘抄。"
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("readerSubtitle")
        self.book_title_label = QLabel("当前阅读：—")
        self.book_title_label.setObjectName("currentBookLabel")
        root.addWidget(heading)
        root.addWidget(subtitle)
        root.addWidget(self.book_title_label)

        reading_bar = QHBoxLayout()
        reading_bar.addWidget(QLabel("章节"))
        self.chapter_combo = QComboBox()
        self.chapter_combo.setMinimumWidth(250)
        self.chapter_combo.setEnabled(False)
        self.chapter_combo.currentIndexChanged.connect(self._select_chapter)
        reading_bar.addWidget(self.chapter_combo, 1)
        reading_bar.addSpacing(12)
        reading_bar.addWidget(QLabel("阅读方式"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["滚轮阅读", "点击翻页"])
        self.mode_combo.setToolTip("滚轮阅读：鼠标滚轮连续滚动；点击翻页：左侧上一页，右侧下一页")
        self.mode_combo.currentIndexChanged.connect(self._update_page_indicator)
        reading_bar.addWidget(self.mode_combo)
        self.page_label = QLabel("页码：—")
        self.page_label.setObjectName("pageLabel")
        self.page_label.setMinimumWidth(105)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        reading_bar.addWidget(self.page_label)
        root.addLayout(reading_bar)

        self.book_list = QListWidget()
        self.book_list.hide()
        self.book_list.currentRowChanged.connect(self._show_book)
        self.reader = QTextBrowser()
        self.reader.setOpenExternalLinks(True)
        self.reader.installEventFilter(self)
        self.reader.viewport().installEventFilter(self)
        self.reader.verticalScrollBar().valueChanged.connect(self._update_page_indicator)
        root.addWidget(self.reader, 1)

        buttons = QHBoxLayout()
        note_button = QPushButton("写笔记")
        note_button.clicked.connect(self._write_note)
        quote_button = QPushButton("摘抄选中文字")
        quote_button.clicked.connect(self._save_excerpt)
        open_notes_button = QPushButton("查看笔记与摘抄")
        open_notes_button.clicked.connect(self._open_notes_folder)
        buttons.addWidget(note_button)
        buttons.addWidget(quote_button)
        buttons.addWidget(open_notes_button)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.setStyleSheet(
            """
            QDialog { background: #f7f0e2; color: #4f4741; }
            #readerHeading { font: 700 24px 'Microsoft YaHei UI'; color: #67564b; }
            #readerSubtitle { font: 13px 'Microsoft YaHei UI'; color: #81736a; }
            #currentBookLabel {
                background: #efe2cf;
                border-radius: 8px;
                padding: 6px 9px;
                color: #67564b;
            }
            #pageLabel {
                background: #efe2cf;
                border: 1px solid #cdbba7;
                border-radius: 8px;
                padding: 5px 8px;
                color: #67564b;
                font: 12px 'Microsoft YaHei UI';
            }
            QListWidget, QTextBrowser {
                background: rgba(255, 252, 245, 235);
                border: 1px solid #cdbba7;
                border-radius: 12px;
                padding: 9px;
                font: 14px 'Microsoft YaHei UI';
                selection-background-color: #d8c7ad;
            }
            QTextBrowser { font-size: 16px; line-height: 1.7; }
            QPushButton {
                background: #eadbc5;
                border: 1px solid #c8b39a;
                border-radius: 10px;
                padding: 8px 14px;
                font: 13px 'Microsoft YaHei UI';
            }
            QPushButton:hover { background: #dfc9aa; }
            """
        )
        self.refresh()

    def refresh(self) -> None:
        self._paths = _library_books(self.library_dir)
        current = _current_book(self.library_dir)
        self.book_list.clear()
        for path in self._paths:
            self.book_list.addItem(path.stem)
        if current is None:
            self._current_path = None
            self.book_title_label.setText("当前阅读：—")
            self._clear_chapters()
            self.reader.setHtml(
                "<div style='padding:24px;color:#81736a'>"
                "还没有选择当前阅读的书。请先回到小屋点击书架，放入并选择一本书。"
                "</div>"
            )
            self._page_offsets = [0]
            self._update_page_indicator()
            return
        self.book_list.setCurrentRow(self._paths.index(current))

    def _show_book(self, row: int) -> None:
        if not 0 <= row < len(self._paths):
            return
        path = self._paths[row]
        self._current_path = path
        self.book_title_label.setText(f"当前阅读：《{path.stem}》")
        if path.suffix.lower() == ".epub":
            try:
                self._epub_chapters = self._read_epub_chapters(path)
            except (OSError, KeyError, zipfile.BadZipFile, ValueError, ET.ParseError) as exc:
                self._clear_chapters()
                QMessageBox.warning(self, "没有读到这本 EPUB", str(exc))
                return
            self._populate_chapters()
            return
        self._clear_chapters()
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="gb18030", errors="replace")
        except OSError as exc:
            QMessageBox.warning(self, "没有读到这本书", str(exc))
            return
        if path.suffix.lower() in {".md", ".markdown"}:
            self.reader.setMarkdown(content)
        else:
            self.reader.setPlainText(content)
        self.reader.moveCursor(QTextCursor.MoveOperation.Start)
        QTimer.singleShot(0, self._rebuild_page_offsets)

    def _clear_chapters(self) -> None:
        self._epub_chapters = []
        self._current_chapter = -1
        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        self.chapter_combo.blockSignals(False)
        self.chapter_combo.setEnabled(False)

    def _populate_chapters(self) -> None:
        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        for index, (title, _content) in enumerate(self._epub_chapters, start=1):
            self.chapter_combo.addItem(f"{index:02d}  {title}")
        self.chapter_combo.blockSignals(False)
        self.chapter_combo.setEnabled(bool(self._epub_chapters))
        if self._epub_chapters:
            self.chapter_combo.setCurrentIndex(0)
            self._select_chapter(0)

    def _select_chapter(self, row: int) -> None:
        if not 0 <= row < len(self._epub_chapters):
            return
        self._current_chapter = row
        content = self._epub_chapters[row][1]
        self.reader.setHtml(
            "<html><head><meta charset='utf-8'></head><body>" + content + "</body></html>"
        )
        self.reader.moveCursor(QTextCursor.MoveOperation.Start)
        self.reader.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, self._rebuild_page_offsets)

    def _rebuild_page_offsets(self) -> None:
        """Build page starts at rendered text-line boundaries, never mid-line."""
        if not self.reader.toPlainText().strip():
            self._page_offsets = [0]
            self._update_page_indicator()
            return
        document = self.reader.document()
        document_layout = document.documentLayout()
        line_tops: list[int] = [0]
        block = document.begin()
        while block.isValid():
            block_rect = document_layout.blockBoundingRect(block)
            text_layout = block.layout()
            for index in range(text_layout.lineCount()):
                top = int(round(block_rect.top() + text_layout.lineAt(index).y()))
                if top > line_tops[-1]:
                    line_tops.append(top)
            block = block.next()

        bar = self.reader.verticalScrollBar()
        page_height = max(1, self.reader.viewport().height() - 8)
        max_scroll = max(0, bar.maximum())
        offsets = [0]
        target = page_height
        while target < max_scroll:
            # Start the next page at the beginning of the line intersected by
            # the previous viewport bottom.  The line may appear once more at
            # the top, but it is never skipped or resumed halfway through.
            index = bisect.bisect_right(line_tops, target) - 1
            if index < 0 or index >= len(line_tops):
                break
            offset = min(max_scroll, line_tops[index])
            if offset <= offsets[-1]:
                index += 1
                if index >= len(line_tops):
                    break
                offset = min(max_scroll, line_tops[index])
                if offset <= offsets[-1]:
                    break
            offsets.append(offset)
            target = offset + page_height
        # Add a final start close to the scrollbar maximum so the end of the
        # chapter is reachable, while still aligning that start to a full line.
        final_index = bisect.bisect_right(line_tops, max_scroll) - 1
        if final_index >= 0:
            final_offset = min(max_scroll, line_tops[final_index])
            if final_offset > offsets[-1] + 2:
                offsets.append(final_offset)
        self._page_offsets = offsets
        self._update_page_indicator()

    def _update_page_indicator(self, *_args) -> None:
        """Show the current viewport page and total pages for the active text."""
        if not self.reader.document() or not self.reader.toPlainText().strip():
            self.page_label.setText("页码：—")
            return
        bar = self.reader.verticalScrollBar()
        total_pages = max(1, len(self._page_offsets))
        current_page = min(total_pages, bisect.bisect_right(self._page_offsets, bar.value() + 2))
        mode_hint = "点击左右翻页" if self.mode_combo.currentIndex() == 1 else "滚轮连续阅读"
        self.page_label.setText(f"第 {current_page} / {total_pages} 页 · {mode_hint}")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._rebuild_page_offsets)

    def _turn_page(self, direction: int) -> None:
        """Move one viewport in click-to-turn mode, crossing EPUB chapters."""
        bar = self.reader.verticalScrollBar()
        value = bar.value()
        page_index = max(0, bisect.bisect_right(self._page_offsets, value + 2) - 1)
        if direction > 0:
            if page_index + 1 >= len(self._page_offsets):
                if self._current_chapter + 1 < len(self._epub_chapters):
                    self.chapter_combo.setCurrentIndex(self._current_chapter + 1)
                return
            bar.setValue(self._page_offsets[page_index + 1])
        else:
            if page_index <= 0:
                if self._current_chapter > 0:
                    self.chapter_combo.setCurrentIndex(self._current_chapter - 1)
                    QTimer.singleShot(0, lambda: self.reader.verticalScrollBar().setValue(self._page_offsets[-1]))
                return
            bar.setValue(self._page_offsets[page_index - 1])

    def _reading_context(self) -> str:
        book = f"《{self._current_path.stem}》" if self._current_path else "未命名书籍"
        chapter = ""
        if 0 <= self._current_chapter < len(self._epub_chapters):
            chapter = f" · {self._epub_chapters[self._current_chapter][0]}"
        page = max(1, bisect.bisect_right(self._page_offsets, self.reader.verticalScrollBar().value() + 2))
        return f"{book}{chapter} · 第 {page} 页"

    def _notes_dir(self) -> Path:
        path = self.library_dir / "阅读笔记"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _append_reading_record(self, kind: str, content: str) -> None:
        if self._current_path is None:
            return
        safe_stem = re.sub(r'[<>:"/\\|?*]+', "_", self._current_path.stem).strip() or "未命名书籍"
        target = self._notes_dir() / f"{safe_stem}_{kind}.txt"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {self._reading_context()}\n{content.strip()}\n\n")

    def _write_note(self) -> None:
        if self._current_path is None:
            QMessageBox.information(self, "没有打开书", "请先去书架选择一本书。")
            return
        note, ok = QInputDialog.getMultiLineText(self, "写阅读笔记", self._reading_context(), "")
        if ok and note.strip():
            self._append_reading_record("笔记", note)
            QMessageBox.information(self, "已保存", "这条笔记已经按书名保存。")

    def _save_excerpt(self) -> None:
        if self._current_path is None:
            QMessageBox.information(self, "没有打开书", "请先去书架选择一本书。")
            return
        selected = self.reader.textCursor().selectedText().replace("\u2029", "\n").strip()
        if not selected:
            QMessageBox.information(self, "先选择文字", "请先在正文中拖动选中想摘抄的文字。")
            return
        self._append_reading_record("摘抄", selected)
        QMessageBox.information(self, "已摘抄", "选中的文字已经保存，并附上章节与页码。")

    def _open_notes_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._notes_dir())))

    def eventFilter(self, watched, event):
        if (
            self.mode_combo.currentIndex() == 1
            and watched in {self.reader, self.reader.viewport()}
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            point = event.position().toPoint()
            # Keep ordinary hyperlinks usable in either reading mode.
            if not self.reader.anchorAt(point) and not self.reader.textCursor().hasSelection():
                self._turn_page(-1 if point.x() < self.reader.viewport().width() / 2 else 1)
                return True
        return super().eventFilter(watched, event)

    def _import_books(self) -> None:
        sources, _ = QFileDialog.getOpenFileNames(
            self,
            "选择要放进小屋书架的文字书籍",
            str(Path.home()),
            "文字书籍 (*.txt *.md *.markdown *.epub)",
        )
        if not sources:
            return
        self.library_dir.mkdir(parents=True, exist_ok=True)
        for source_name in sources:
            source = Path(source_name)
            target = self.library_dir / source.name
            index = 2
            while target.exists() and target.resolve() != source.resolve():
                target = self.library_dir / f"{source.stem}_{index}{source.suffix}"
                index += 1
            if target.resolve() != source.resolve():
                shutil.copy2(source, target)
        self.refresh()

    @staticmethod
    def _xml_local_name(tag: str) -> str:
        """Return an XML tag name without its optional namespace."""
        return tag.rsplit("}", 1)[-1]

    @classmethod
    def _read_epub_chapters(cls, path: Path) -> list[tuple[str, str]]:
        """Read an EPUB spine into ``(chapter title, HTML body)`` pairs.

        EPUB is a ZIP container.  We follow META-INF/container.xml to the OPF,
        then follow the OPF manifest/spine so chapters are shown in the book's
        intended order instead of ZIP file order.  The HTML is deliberately
        kept lightweight: text and ordinary formatting survive, while scripts
        and stylesheets are removed because QTextBrowser cannot execute them.
        """
        # Some EPUB exporters leave a large zero-filled buffer after the ZIP
        # end record.  It is harmless, but Python's ZIP reader searches only
        # the final 64 KiB and therefore misses the real end record.  Trim
        # that padding in memory before opening the archive.
        raw_file = path.read_bytes()
        archive_data = raw_file
        eocd = raw_file.rfind(b"PK\x05\x06")
        if eocd >= 0 and eocd + 22 <= len(raw_file):
            comment_length = int.from_bytes(raw_file[eocd + 20:eocd + 22], "little")
            archive_end = eocd + 22 + comment_length
            if archive_end <= len(raw_file):
                archive_data = raw_file[:archive_end]

        with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
            try:
                container = ET.fromstring(archive.read("META-INF/container.xml"))
                rootfile = next(
                    element for element in container.iter()
                    if cls._xml_local_name(element.tag) == "rootfile"
                )
                opf_name = rootfile.attrib["full-path"]
            except (KeyError, StopIteration) as exc:
                raise ValueError("EPUB 缺少有效的目录文件") from exc

            opf = ET.fromstring(archive.read(opf_name))
            manifest = {}
            for item in opf.iter():
                if cls._xml_local_name(item.tag) != "item":
                    continue
                item_id = item.attrib.get("id")
                href = item.attrib.get("href")
                if item_id and href:
                    manifest[item_id] = (
                        urllib.parse.unquote(href), item.attrib.get("media-type", "")
                    )

            # EPUB 2 books usually carry a toc.ncx.  Its labels are more
            # reliable than filenames such as chapter1.html and let us
            # distinguish front matter from the actual novel chapters.
            toc_name = ""
            for element in opf.iter():
                if cls._xml_local_name(element.tag) == "spine":
                    toc_id = element.attrib.get("toc")
                    if toc_id and toc_id in manifest:
                        toc_href, _media = manifest[toc_id]
                        toc_name = posixpath.normpath(posixpath.join(posixpath.dirname(opf_name), toc_href))
                    break
            toc_labels = {}
            if toc_name:
                try:
                    toc = ET.fromstring(archive.read(toc_name))
                    for nav_point in toc.iter():
                        if cls._xml_local_name(nav_point.tag) != "navPoint":
                            continue
                        label_node = next(
                            (node for node in nav_point.iter() if cls._xml_local_name(node.tag) == "text"),
                            None,
                        )
                        content_node = next(
                            (node for node in nav_point if cls._xml_local_name(node.tag) == "content"),
                            None,
                        )
                        if label_node is None or content_node is None:
                            continue
                        label = " ".join("".join(label_node.itertext()).split())
                        src = urllib.parse.unquote(content_node.attrib.get("src", ""))
                        src = src.split("#", 1)[0].split("?", 1)[0]
                        if label and src:
                            toc_labels[posixpath.normpath(posixpath.join(posixpath.dirname(toc_name), src))] = label
                except (KeyError, ET.ParseError):
                    toc_labels = {}

            chapter_ids = []
            for itemref in opf.iter():
                if cls._xml_local_name(itemref.tag) == "itemref":
                    idref = itemref.attrib.get("idref")
                    if idref:
                        chapter_ids.append(idref)

            opf_dir = posixpath.dirname(opf_name)
            chapters: list[tuple[str, str]] = []
            front_matter_pattern = re.compile(
                r"(封面|扉页|版权|作者简介|内容简介|作品简介|出版信息|目录|书名|cover|title\s*page|copyright|about\s+the\s+author)",
                flags=re.I,
            )
            for chapter_id in chapter_ids:
                href_media = manifest.get(chapter_id)
                if not href_media:
                    continue
                href, media_type = href_media
                if media_type and "html" not in media_type and "xhtml" not in media_type:
                    continue
                # A manifest href may contain a document fragment used by the
                # EPUB navigation map; ZIP members only contain the filename.
                href = href.split("#", 1)[0].split("?", 1)[0]
                chapter_name = posixpath.normpath(posixpath.join(opf_dir, href))
                raw = archive.read(chapter_name).decode("utf-8", errors="replace")
                raw = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", raw, flags=re.I | re.S)
                raw = re.sub(r"<style\b[^>]*>.*?</style\s*>", "", raw, flags=re.I | re.S)
                body = re.search(r"<body\b[^>]*>(.*?)</body\s*>", raw, flags=re.I | re.S)
                chapter_html = body.group(1) if body else raw
                if chapter_html.strip():
                    heading = re.search(
                        r"<h[1-6]\b[^>]*>(.*?)</h[1-6]\s*>", chapter_html,
                        flags=re.I | re.S,
                    )
                    title_source = toc_labels.get(chapter_name, "")
                    if not title_source:
                        title_source = heading.group(1) if heading else ""
                    title_source = re.sub(r"<[^>]+>", " ", title_source)
                    title_source = html_lib.unescape(re.sub(r"\s+", " ", title_source)).strip()
                    title = title_source or f"第 {len(chapters) + 1} 章"
                    if front_matter_pattern.search(title) or chapter_name.lower().endswith("coverpage.html"):
                        continue
                    chapters.append((title, chapter_html))

            if not chapters:
                raise ValueError("EPUB 中没有找到可阅读的正文章节")
            return chapters

    @classmethod
    def _read_epub(cls, path: Path) -> str:
        """Backward-compatible full-book HTML helper."""
        chapters = cls._read_epub_chapters(path)
        return (
            "<html><head><meta charset='utf-8'></head><body>"
            + "<hr style='color:#cdbba7'>".join(content for _title, content in chapters)
            + "</body></html>"
        )
