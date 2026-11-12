from __future__ import annotations

import difflib
import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, QRect, QSize, Signal, QObject, QRunnable, QThreadPool, QTimer, QStandardPaths
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QIcon, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat, QKeySequence
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QFileDialog, QTreeView, QFileSystemModel, QTabWidget, QPlainTextEdit,
    QLabel, QPushButton, QComboBox, QMessageBox, QInputDialog, QDialog,
    QFormLayout, QLineEdit, QDialogButtonBox, QScrollArea, QFrame, QToolBar,
    QTextEdit, QSizePolicy,
)

from . import core, __version__
from .document_io import Document
from .agent_client import AgentClient, TransferUncertain
from .transfer import TransferTracker

ASSETS = Path(__file__).parent / "assets"
FILTER = "Programas CNC (*.nc *.tap *.gcode *.cnc *.txt *.min *.iso *.mpf *.spf *.prg *.dnc *.pgm *.h *.i *.ptp *.anc *.fnc);;Todos los archivos (*)"


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)) / "settings.json"
        try:
            self.values = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.values, dict):
                self.values = {}
        except (OSError, ValueError):
            self.values = {}

    def get(self, name, default=None):
        return self.values.get(name, default)

    def save(self, **values):
        self.values.update(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(self.values, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, self.path)
        if os.name != "nt":
            self.path.chmod(0o600)


class JobSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function, self.signals = function, JobSignals()

    def run(self):
        try:
            result = self.function()
        except Exception as error:
            self.signals.failed.emit(str(error))
        else:
            self.signals.completed.emit(result)


class Highlighter(QSyntaxHighlighter):
    COLORS = {"G": "#237CE4", "M": "#D34F8F", "T": "#A78028", "S": "#9964C9", "F": "#D77418", "X": "#34956A", "Y": "#34956A", "Z": "#34956A", "N": "#9297A1"}

    def highlightBlock(self, text):
        for match in core.WORD.finditer(text):
            color = self.COLORS.get(match[1].upper())
            if color:
                format_ = QTextCharFormat()
                format_.setForeground(QColor(color))
                self.setFormat(match.start(), match.end() - match.start(), format_)
        comment = QTextCharFormat()
        comment.setForeground(QColor("#7F9589"))
        comment.setFontItalic(True)
        depth = max(0, self.previousBlockState())
        start = 0 if depth else None
        for index, char in enumerate(text):
            if char == "(":
                if not depth:
                    start = index
                depth += 1
            elif depth and char == ")":
                depth -= 1
                if not depth and start is not None:
                    self.setFormat(start, index - start + 1, comment)
                    start = None
            elif not depth and char == ";":
                self.setFormat(index, len(text) - index, comment)
                break
        if depth and start is not None:
            self.setFormat(start, len(text) - start, comment)
        self.setCurrentBlockState(depth)


class NumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_numbers(event)


class Editor(QPlainTextEdit):
    def __init__(self, document: Document, font_size=13):
        super().__init__()
        self.file = document
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(font_size)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setPlainText(document.text)
        self.document().setModified(False)
        self.highlighter = Highlighter(self.document())
        self.number_area = NumberArea(self)
        self.blockCountChanged.connect(self.update_gutter)
        self.updateRequest.connect(self.update_numbers)
        self.cursorPositionChanged.connect(self.current_line)
        self.update_gutter()
        self.current_line()
        self.setAcceptDrops(False)

    def gutter_width(self):
        return 16 + self.fontMetrics().horizontalAdvance("9") * max(2, len(str(self.blockCount())))

    def update_gutter(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def update_numbers(self, rect, delta):
        if delta:
            self.number_area.scroll(0, delta)
        else:
            self.number_area.update(0, rect.y(), self.number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_gutter()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        area = self.contentsRect()
        self.number_area.setGeometry(QRect(area.left(), area.top(), self.gutter_width(), area.height()))

    def paint_numbers(self, event):
        painter = QPainter(self.number_area)
        painter.fillRect(event.rect(), self.palette().alternateBase())
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        number = block.blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(self.palette().placeholderText().color())
                painter.drawText(0, top, self.number_area.width() - 8, self.fontMetrics().height(), Qt.AlignRight, str(number + 1))
            block = block.next()
            top, bottom = bottom, bottom + round(self.blockBoundingRect(block).height())
            number += 1

    def current_line(self):
        selection = QTextEdit.ExtraSelection()
        color = self.palette().highlight().color()
        color.setAlpha(22)
        selection.format.setBackground(color)
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def transform(self, function):
        source = self.toPlainText()
        result = function(source)
        if result == source:
            return
        cursor = self.textCursor()
        position = cursor.position()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        cursor.insertText(result)
        cursor.setPosition(min(position, len(result.encode("utf-16-le")) // 2))
        cursor.endEditBlock()
        self.setTextCursor(cursor)


class FindDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Buscar y reemplazar")
        form = QFormLayout(self)
        self.find = QLineEdit()
        self.replace = QLineEdit()
        form.addRow("Buscar", self.find)
        form.addRow("Reemplazar con", self.replace)
        row = QHBoxLayout()
        for title, function in [("Siguiente", self.next), ("Reemplazar", self.one), ("Reemplazar todo", self.all)]:
            button = QPushButton(title)
            button.clicked.connect(function)
            row.addWidget(button)
        form.addRow(row)
        self.find.returnPressed.connect(self.next)
        self.message = QLabel("Coincidencia exacta; distingue mayúsculas.")
        form.addRow(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        form.addRow(buttons)

    def next(self):
        editor = self.window.editor()
        if editor and self.find.text():
            if not editor.find(self.find.text(), editor.document().FindFlag.FindCaseSensitively):
                cursor = editor.textCursor()
                cursor.movePosition(QTextCursor.Start)
                editor.setTextCursor(cursor)
                if not editor.find(self.find.text(), editor.document().FindFlag.FindCaseSensitively):
                    self.message.setText("No se encontró el texto.")
                    return
            self.message.setText("Coincidencia seleccionada.")

    def one(self):
        editor = self.window.editor()
        if editor and self.find.text():
            cursor = editor.textCursor()
            if cursor.selectedText() == self.find.text():
                cursor.insertText(self.replace.text())
            self.next()

    def all(self):
        editor = self.window.editor()
        if editor and self.find.text():
            count = editor.toPlainText().count(self.find.text())
            editor.transform(lambda text: text.replace(self.find.text(), self.replace.text()))
            self.message.setText(f"{count} reemplazos.")


class Window(QMainWindow):
    def __init__(self, settings: Settings | None = None, *, restore=True):
        super().__init__()
        self.settings = settings or Settings()
        self.jobs = set()
        self.client = None
        self.transfer_client = None
        self.transfer_machine = ""
        self.transfer_busy = False
        self.transfer_tracker = None
        self.status_inflight = False
        self.find_dialog = None
        self.setWindowTitle("ZEUZ Edit")
        self.setWindowIcon(QIcon(str(ASSETS / "AppIcon.png")))
        self.resize(1240, 780)
        self.setMinimumSize(980, 600)
        self.make_ui()
        self.make_menus()
        self.poll = QTimer(self)
        self.poll.setInterval(1500)
        self.poll.timeout.connect(self.poll_transfer)
        if restore:
            for value in self.settings.get("reopen", [])[:20]:
                if Path(value).is_file():
                    self.open_file(Path(value))
            root = self.settings.get("folder")
            if root and Path(root).is_dir():
                self.set_folder(Path(root))
            if self.settings.get("token"):
                try:
                    self.client = AgentClient(self.settings.get("endpoint", "http://127.0.0.1:47820"), self.settings.get("token"))
                except Exception:
                    self.transfer_label.setText("Revisa la dirección guardada con Conectar Agent…")
                else:
                    QTimer.singleShot(0, self.refresh_machines)
        if self.tabs.count() == 0:
            self.new_document()
        self.statusBar().showMessage("Listo · ZEUZ Edit " + __version__)

    def make_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 14, 12, 8)
        dark = self.palette().window().color().lightness() < 128
        brand = QSvgWidget(str(ASSETS / ("edit-dark.svg" if dark else "edit-light.svg")))
        brand.setFixedSize(220, 68)
        brand.setAccessibleName("ZEUZ Edit")
        left_layout.addWidget(brand)
        explorer_row = QHBoxLayout()
        explorer_row.addWidget(QLabel("EXPLORADOR"))
        add = QPushButton("Agregar carpeta…")
        add.clicked.connect(self.choose_folder)
        explorer_row.addWidget(add)
        left_layout.addLayout(explorer_row)
        self.folder_label = QLabel("Elige la carpeta de programas")
        self.folder_label.setWordWrap(True)
        left_layout.addWidget(self.folder_label)
        self.files = QFileSystemModel(self)
        self.files.setReadOnly(True)
        self.files.setNameFilters(["*.nc", "*.tap", "*.gcode", "*.cnc", "*.txt", "*.min", "*.iso", "*.mpf", "*.spf", "*.prg", "*.dnc", "*.pgm", "*.h", "*.i", "*.ptp", "*.anc", "*.fnc"])
        self.files.setNameFilterDisables(False)
        self.tree = QTreeView()
        self.tree.setModel(self.files)
        self.tree.setHeaderHidden(True)
        for column in [1, 2, 3]:
            self.tree.hideColumn(column)
        self.tree.setRootIsDecorated(True)
        self.tree.doubleClicked.connect(self.tree_open)
        self.tree.setAccessibleName("Explorador de programas CNC")
        left_layout.addWidget(self.tree, 1)
        splitter.addWidget(left)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.update_current)
        center_layout.addWidget(self.tabs, 1)
        send_box = QFrame()
        send_box.setFrameShape(QFrame.StyledPanel)
        send_layout = QVBoxLayout(send_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Máquina"))
        self.machine = QComboBox()
        self.machine.setMinimumWidth(160)
        self.machine.addItem("Conecta Zeuz Agent", "")
        row.addWidget(self.machine, 1)
        self.connect_button = QPushButton("Conectar Agent…")
        self.connect_button.clicked.connect(self.pair_agent)
        row.addWidget(self.connect_button)
        self.send_button = QPushButton("Enviar a la máquina…")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.confirm_send)
        row.addWidget(self.send_button)
        send_layout.addLayout(row)
        row = QHBoxLayout()
        self.transfer_label = QLabel("Conecta Agent para enviar mediante ZeuzDNC.")
        self.transfer_label.setWordWrap(True)
        row.addWidget(self.transfer_label, 1)
        self.cancel_button = QPushButton("Cancelar envío")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_transfer)
        row.addWidget(self.cancel_button)
        send_layout.addLayout(row)
        center_layout.addWidget(send_box)
        splitter.addWidget(center)
        tools = QWidget()
        tool_layout = QVBoxLayout(tools)
        tool_layout.setContentsMargins(10, 10, 10, 10)
        sections = [
            ("ARCHIVO", [("Nuevo", self.new_document), ("Abrir…", self.open_dialog), ("Guardar", self.save_document), ("Guardar como…", lambda: self.save_document(save_as=True))]),
            ("BUSCAR", [("Buscar y reemplazar…", self.show_find), ("Ir a línea o bloque N…", self.goto)]),
            ("LÍNEAS", [("Numerar donde falte", lambda: self.apply(lambda t: core.renumber(t, missing_only=True))), ("Quitar numeración N", lambda: self.apply(core.remove_numbers)), ("Renumerar todas", lambda: self.apply(core.renumber)), ("Formatear espacios", lambda: self.apply(core.format_spacing))]),
            ("AJUSTES", [("Quitar refrigerante M8/M08", lambda: self.apply(lambda t: core.remove_mcodes(t, {8}))), ("Quitar códigos M…", self.remove_codes), ("Ajustar avance F…", lambda: self.scale("F")), ("Ajustar husillo S…", lambda: self.scale("S")), ("Código en mayúsculas", lambda: self.apply(core.uppercase_code))]),
            ("NAVEGACIÓN", [("Siguiente herramienta", self.next_tool), ("Comparar programas…", self.compare), ("Análisis y rangos XYZ", self.analysis)]),
        ]
        for title, commands in sections:
            label = QLabel(title)
            label.setStyleSheet("color:#278BDB;font-weight:700;padding-top:8px")
            tool_layout.addWidget(label)
            for text, function in commands:
                button = QPushButton(text)
                button.setFlat(True)
                button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
                button.setStyleSheet("QPushButton{text-align:left;padding:6px}QPushButton:hover{background:rgba(39,139,219,0.12)}")
                button.clicked.connect(function)
                tool_layout.addWidget(button)
        tool_layout.addStretch()
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Tamaño de letra"))
        for text, delta in [("A−", -1), ("A+", 1)]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, value=delta: self.zoom(value))
            font_row.addWidget(button)
        tool_layout.addLayout(font_row)
        scroll = QScrollArea()
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setWidget(tools)
        scroll.setMinimumWidth(220)
        scroll.setMaximumWidth(270)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 740, 240])
        self.setCentralWidget(splitter)

    def action(self, menu, title, function, shortcut=None):
        action = QAction(title, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(function)
        menu.addAction(action)
        return action

    def make_menus(self):
        file = self.menuBar().addMenu("&Archivo")
        self.action(file, "Nuevo", self.new_document, QKeySequence.New)
        self.action(file, "Abrir…", self.open_dialog, QKeySequence.Open)
        self.recent_menu = file.addMenu("Recientes")
        self.refresh_recent_menu()
        self.action(file, "Agregar carpeta…", self.choose_folder)
        file.addSeparator()
        self.action(file, "Guardar", self.save_document, QKeySequence.Save)
        self.action(file, "Guardar como…", lambda: self.save_document(save_as=True), QKeySequence.SaveAs)
        self.action(file, "Cerrar pestaña", lambda: self.close_tab(self.tabs.currentIndex()), QKeySequence.Close)
        self.action(file, "Salir", self.close, QKeySequence.Quit)
        edit = self.menuBar().addMenu("&Edición")
        for title, method, key in [("Deshacer", "undo", QKeySequence.Undo), ("Rehacer", "redo", QKeySequence.Redo), ("Cortar", "cut", QKeySequence.Cut), ("Copiar", "copy", QKeySequence.Copy), ("Pegar", "paste", QKeySequence.Paste), ("Seleccionar todo", "selectAll", QKeySequence.SelectAll)]:
            self.action(edit, title, lambda checked=False, command=method: self.editor() and getattr(self.editor(), command)(), key)
        self.action(edit, "Buscar y reemplazar…", self.show_find, QKeySequence.Find)
        self.action(edit, "Ir a línea o bloque N…", self.goto, "Ctrl+L")
        program = self.menuBar().addMenu("&Programa")
        for title, function in [("Numerar donde falte", lambda: self.apply(lambda t: core.renumber(t, missing_only=True))), ("Quitar numeración N", lambda: self.apply(core.remove_numbers)), ("Renumerar todas", lambda: self.apply(core.renumber)), ("Formatear espacios", lambda: self.apply(core.format_spacing)), ("Quitar refrigerante M8/M08", lambda: self.apply(lambda t: core.remove_mcodes(t, {8}))), ("Quitar códigos M…", self.remove_codes), ("Ajustar avance F…", lambda: self.scale("F")), ("Ajustar husillo S…", lambda: self.scale("S")), ("Código en mayúsculas", lambda: self.apply(core.uppercase_code)), ("Siguiente herramienta", self.next_tool), ("Comparar programas…", self.compare), ("Análisis y rangos XYZ", self.analysis)]:
            self.action(program, title, function)
        view = self.menuBar().addMenu("&Ver")
        self.action(view, "Agrandar letra", lambda: self.zoom(1), QKeySequence.ZoomIn)
        self.action(view, "Reducir letra", lambda: self.zoom(-1), QKeySequence.ZoomOut)
        machine = self.menuBar().addMenu("&Máquina")
        self.action(machine, "Conectar Agent…", self.pair_agent)
        self.action(machine, "Actualizar máquinas", self.refresh_machines)
        self.action(machine, "Enviar a la máquina…", self.confirm_send)
        self.action(machine, "Consultar estado", self.poll_transfer)
        self.action(machine, "Cancelar envío", self.cancel_transfer)
        help_ = self.menuBar().addMenu("A&yuda")
        self.action(help_, "Acerca de ZEUZ Edit", lambda: QMessageBox.about(self, "ZEUZ Edit", f"ZEUZ Edit {__version__}\nWindows y Linux · interfaz de escritorio Qt\nEnvío mediante Zeuz Agent API v1.\nAnálisis de texto NC; no simula la trayectoria de la CNC."))

    def editor(self):
        current = self.tabs.currentWidget()
        return current if isinstance(current, Editor) else None

    def add_editor(self, document):
        editor = Editor(document, self.settings.get("font_size", 13))
        self.tabs.addTab(editor, document.path.name if document.path else "Sin título")
        self.tabs.setCurrentWidget(editor)
        editor.document().modificationChanged.connect(lambda modified, item=editor: self.refresh_tab(item))
        editor.cursorPositionChanged.connect(self.position_status)
        editor.setFocus()
        return editor

    def new_document(self):
        self.add_editor(Document())

    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Abrir programas", self.settings.get("folder", ""), FILTER)
        for path in paths:
            self.open_file(Path(path))

    def open_file(self, path):
        for index in range(self.tabs.count()):
            if self.tabs.widget(index).file.path == path.resolve():
                self.tabs.setCurrentIndex(index)
                return
        try:
            if path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("El editor admite archivos de hasta 32 MiB.")
            document = Document.read(path)
            self.add_editor(document)
            recent = [str(document.path)] + [value for value in self.settings.get("recent", []) if value != str(document.path)]
            self.settings.save(recent=recent[:15])
            self.refresh_recent_menu()
        except Exception as error:
            self.error(str(error))

    def refresh_recent_menu(self):
        if not hasattr(self, "recent_menu"):
            return
        self.recent_menu.clear()
        for path in self.settings.get("recent", []):
            self.action(self.recent_menu, path, lambda checked=False, value=path: self.open_file(Path(value)))
        self.recent_menu.setEnabled(bool(self.settings.get("recent", [])))

    def save_document(self, checked=False, *, save_as=False):
        editor = self.editor()
        if not editor:
            return False
        path = editor.file.path
        if save_as or path is None:
            value, _ = QFileDialog.getSaveFileName(self, "Guardar programa", str(path or "Programa.nc"), FILTER)
            if not value:
                return False
            path = Path(value)
        try:
            editor.file.save(editor.toPlainText(), path)
        except Exception as error:
            self.error(str(error))
            return False
        editor.document().setModified(False)
        self.refresh_tab(editor)
        self.statusBar().showMessage("Guardado: " + str(path), 6000)
        return True

    def refresh_tab(self, editor):
        index = self.tabs.indexOf(editor)
        if index >= 0:
            name = editor.file.path.name if editor.file.path else "Sin título"
            self.tabs.setTabText(index, name + (" •" if editor.document().isModified() else ""))
            self.tabs.setTabToolTip(index, str(editor.file.path or "Programa sin guardar"))
        self.update_current()

    def update_current(self, *_):
        editor = self.editor()
        self.setWindowTitle((editor.file.path.name if editor and editor.file.path else "Sin título") + " — ZEUZ Edit")
        self.position_status()

    def position_status(self):
        editor = self.editor()
        if editor:
            cursor = editor.textCursor()
            self.statusBar().showMessage(f"Línea {cursor.blockNumber()+1}, columna {cursor.positionInBlock()+1} · {editor.blockCount()} líneas · {editor.file.encoding}")

    def close_tab(self, index):
        if index < 0:
            return True
        editor = self.tabs.widget(index)
        if not self.confirm_close(editor):
            return False
        self.tabs.removeTab(index)
        editor.deleteLater()
        return True

    def confirm_close(self, editor):
        if editor.document().isModified():
            self.tabs.setCurrentWidget(editor)
            result = QMessageBox.question(self, "Cambios sin guardar", "¿Guardar los cambios del programa antes de cerrarlo?", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if result == QMessageBox.Cancel or (result == QMessageBox.Save and not self.save_document()):
                return False
        return True

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Agregar carpeta de programas", self.settings.get("folder", ""))
        if path:
            self.set_folder(Path(path))
            self.settings.save(folder=path)

    def set_folder(self, path):
        self.files.setRootPath(str(path))
        self.tree.setRootIndex(self.files.index(str(path)))
        self.folder_label.setText(str(path))

    def tree_open(self, index):
        path = Path(self.files.filePath(index))
        if path.is_file():
            self.open_file(path)

    def apply(self, function):
        if self.editor():
            try:
                self.editor().transform(function)
            except Exception as error:
                self.error(str(error))

    def zoom(self, delta):
        size = min(28, max(10, self.settings.get("font_size", 13) + delta))
        self.settings.save(font_size=size)
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            font = editor.font()
            font.setPointSize(size)
            editor.setFont(font)
            editor.update_gutter()

    def show_find(self):
        if self.find_dialog is None:
            self.find_dialog = FindDialog(self)
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.find.setFocus()

    def goto(self):
        editor = self.editor()
        if not editor:
            return
        value, ok = QInputDialog.getText(self, "Ir a línea o bloque N", "Número de línea o bloque, por ejemplo N120")
        if not ok:
            return
        try:
            if value.strip().upper().startswith("N"):
                number = int(value.strip()[1:])
                import re
                match = re.search(r"(?im)^[ \t]*N0*" + str(number) + r"(?!\d)", core.code_mask(editor.toPlainText()))
                if not match:
                    raise ValueError("No se encontró el bloque.")
                position = match.start()
            else:
                block = editor.document().findBlockByNumber(int(value) - 1)
                if not block.isValid():
                    raise ValueError("La línea está fuera del programa.")
                position = block.position()
            cursor = editor.textCursor()
            if value.strip().upper().startswith("N"):
                position = len(editor.toPlainText()[:position].encode("utf-16-le")) // 2
            cursor.setPosition(position)
            editor.setTextCursor(cursor)
            editor.centerCursor()
        except ValueError as error:
            self.error(str(error))

    def next_tool(self):
        editor = self.editor()
        if not editor:
            return
        matches = [match for match in core.words(editor.toPlainText()) if match[1].upper() == "T"]
        if not matches:
            self.statusBar().showMessage("No se encontraron llamadas T.", 4000)
            return
        cursor = editor.textCursor()
        text = editor.toPlainText()
        ranges = [(len(text[:match.start()].encode("utf-16-le")) // 2,
                   len(text[:match.end()].encode("utf-16-le")) // 2) for match in matches]
        start, end = next((value for value in ranges if value[0] >= cursor.selectionEnd() + (not cursor.hasSelection())), ranges[0])
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.centerCursor()

    def scale(self, letter):
        percent, ok = QInputDialog.getDouble(self, "Ajustar " + letter, "Cambio porcentual (−10 reduce 10%; +10 aumenta 10%)", -10, -100, 10000, 2)
        if ok:
            self.apply(lambda text: core.scale_words(text, letter, 1 + percent / 100))

    def remove_codes(self):
        value, ok = QInputDialog.getText(self, "Quitar códigos M", "Códigos separados por coma; por ejemplo 8, 9")
        if ok:
            try:
                codes = {int(part.strip().upper().removeprefix("M")) for part in value.split(",")}
                self.apply(lambda text: core.remove_mcodes(text, codes))
            except ValueError:
                self.error("Introduce números M separados por coma.")

    def analysis(self):
        editor = self.editor()
        if not editor:
            return
        result = core.analyze(editor.toPlainText())
        text = f"{result.lines} líneas\nUnidades: {result.units}\nHerramientas: " + (", ".join("T" + value for value in result.tools) or "No declaradas")
        for axis, (low, high) in result.axes.items():
            text += f"\n{axis}: {low:g} a {high:g} · rango {high-low:g}"
        text += "\n\nRangos de valores escritos; no considera offsets, ciclos ni cinemática de la CNC."
        if result.warnings:
            text += "\n\n" + "\n".join(result.warnings)
        QMessageBox.information(self, "Análisis del programa", text)

    def compare(self):
        editor = self.editor()
        if not editor:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Comparar con otro programa", self.settings.get("folder", ""), FILTER)
        if not path:
            return
        try:
            other = Document.read(Path(path))
        except Exception as error:
            self.error(str(error))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Comparar: programa actual ↔ " + Path(path).name)
        dialog.resize(1050, 700)
        layout = QVBoxLayout(dialog)
        compare_split = QSplitter(Qt.Horizontal)
        for text in [editor.toPlainText(), other.text]:
            view = QPlainTextEdit()
            view.setReadOnly(True)
            view.setFont(editor.font())
            view.setPlainText(text)
            Highlighter(view.document())
            compare_split.addWidget(view)
        layout.addWidget(compare_split)
        diff = "".join(difflib.unified_diff(editor.toPlainText().splitlines(keepends=True), other.text.splitlines(keepends=True), fromfile="Actual", tofile=Path(path).name))
        summary = QPlainTextEdit(diff or "Los programas son iguales.")
        summary.setReadOnly(True)
        summary.setMaximumHeight(220)
        summary.setFont(editor.font())
        layout.addWidget(summary)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def run_job(self, function, success, *, failure=None):
        job = Job(function)
        self.jobs.add(job)
        def done(result):
            self.jobs.discard(job)
            success(result)
        def failed(message):
            self.jobs.discard(job)
            (failure or self.error)(message)
        job.signals.completed.connect(done)
        job.signals.failed.connect(failed)
        QThreadPool.globalInstance().start(job)

    def pair_agent(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Conectar Zeuz Agent")
        form = QFormLayout(dialog)
        address = QLineEdit(self.settings.get("endpoint", "http://127.0.0.1:47820"))
        code = QLineEdit()
        code.setPlaceholderText("Código de seis dígitos mostrado en Agent")
        form.addRow("Dirección de Agent", address)
        form.addRow("Código", code)
        hint = QLabel("Agent debe estar activo en esta computadora o en la red local.")
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            client = AgentClient(address.text())
        except Exception as error:
            self.error(str(error))
            return
        pairing_code = code.text()
        self.transfer_label.setText("Conectando con Agent…")
        def connected(name):
            self.client = client
            self.settings.save(endpoint=client.endpoint, token=client.token)
            self.transfer_label.setText("Conectado a " + name)
            self.refresh_machines()
        self.run_job(lambda: client.pair(pairing_code), connected)

    def refresh_machines(self):
        if not self.client:
            self.pair_agent()
            return
        client = self.client
        def updated(machines):
            selected = self.machine.currentData()
            self.machine.clear()
            for machine in machines:
                self.machine.addItem(machine.get("name", machine["id"]), machine["id"])
            previous = self.machine.findData(selected)
            if previous >= 0:
                self.machine.setCurrentIndex(previous)
            self.send_button.setEnabled(bool(machines) and not self.transfer_busy)
            if not self.transfer_busy:
                self.transfer_label.setText(f"Agent conectado · {len(machines)} máquinas disponibles")
        self.run_job(client.machines, updated)

    def confirm_send(self):
        editor = self.editor()
        machine_id = self.machine.currentData()
        if not editor or not self.client or not machine_id or self.transfer_busy:
            self.error("Conecta Agent, selecciona una máquina y espera a que termine el envío actual.")
            return
        content = editor.toPlainText()
        if not content.strip():
            self.error("El programa está vacío.")
            return
        try:
            size = len(content.encode("latin-1", errors="strict"))
        except UnicodeEncodeError:
            self.error("Agent admite texto Latin-1. Revisa caracteres fuera de ese juego antes de enviar.")
            return
        if size > 4 * 1024 * 1024:
            self.error("Este envío desde el editor admite hasta 4 MiB. Para programas mayores, guarda el archivo en la biblioteca y envíalo desde Agent.")
            return
        name = editor.file.path.name if editor.file.path else "Programa.nc"
        result = QMessageBox.question(self, "Enviar programa a la CNC", f"Programa: {name}\nMáquina: {self.machine.currentText()}\nTamaño: {size:,} bytes\n\nSe cargará una copia con nombre único en la biblioteca de Agent y se enviará el contenido actual del editor. Prepara la CNC para recibir.", QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if result != QMessageBox.Yes:
            return
        client = AgentClient(self.client.endpoint, self.client.token)
        self.transfer_client, self.transfer_machine = client, machine_id
        self.transfer_busy = True
        self.send_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.transfer_label.setText("Cargando el programa y solicitando envío…")
        self.transfer_tracker = None
        def upload_failed(message):
            self.transfer_busy = False
            self.transfer_tracker = None
            self.send_button.setEnabled(self.machine.count() > 0)
            self.transfer_client = None
            self.transfer_machine = ""
            self.transfer_label.setText("No se inició el envío: " + message)
            self.error(message)
        def sent(result):
            self.transfer_tracker.request_pending = False
            self.transfer_tracker.acknowledged = True
            self.transfer_label.setText("Envío solicitado · " + self.transfer_tracker.filename)
            self.cancel_button.setEnabled(True)
            self.poll.start()
            self.poll_transfer()
        def failed_send(error):
            message = str(error)
            self.transfer_tracker.request_pending = False
            self.transfer_tracker.phase = "unknown"
            self.transfer_label.setText(message)
            # An uncertain POST is never repeated; query the exact same target.
            self.cancel_button.setEnabled(True)
            self.poll.start()
            self.error(message)
        def uploaded(path):
            self.transfer_tracker = TransferTracker(Path(path).name)
            # Preserve the error classification across the worker boundary.
            def request():
                try:
                    return {"result": client.send(path, machine_id)}
                except TransferUncertain as error:
                    return {"uncertain": str(error)}
            def finished(value):
                if "uncertain" in value:
                    failed_send(value["uncertain"])
                else:
                    sent(value["result"])
            self.run_job(request, finished, failure=upload_failed)
        self.run_job(lambda: client.upload(name, content), uploaded, failure=upload_failed)

    def poll_transfer(self):
        client = self.transfer_client or self.client
        machine_id = self.transfer_machine or self.machine.currentData()
        if not client or not machine_id or self.status_inflight:
            return
        self.status_inflight = True
        def updated(result):
            self.status_inflight = False
            if self.transfer_machine and self.transfer_machine != machine_id:
                return
            status = result.get("status", "idle")
            tracker = self.transfer_tracker
            if self.transfer_busy:
                if tracker is None:
                    return
                status = tracker.accept_status(result)
            message = result.get("message", "")
            if status == "unknown":
                message = "ZeuzDNC todavía no confirma este programa. Consulta el equipo antes de repetir el envío."
            sent, total = result.get("sent_bytes", result.get("bytes_sent", 0)), result.get("total_bytes", 0)
            labels = {"idle": "En espera", "sending": "Enviando", "success": "Envío completado", "error": "Error de envío", "cancelled": "Envío cancelado", "unknown": "Estado sin confirmar", "pending": "Esperando confirmación"}
            self.transfer_label.setText(labels.get(status, status) + (f" · {sent:,}/{total:,} bytes" if total else "") + (" · " + str(message) if message else ""))
            if status in {"idle", "success", "error", "cancelled"} and (tracker is None or not tracker.active):
                self.transfer_busy = False
                self.poll.stop()
                self.cancel_button.setEnabled(False)
                self.send_button.setEnabled(self.machine.count() > 0)
                self.transfer_client = None
                self.transfer_machine = ""
                self.transfer_tracker = None
        def failed(message):
            self.status_inflight = False
            self.transfer_label.setText(message + " El envío no se repite automáticamente.")
        self.run_job(lambda: client.status(machine_id), updated, failure=failed)

    def cancel_transfer(self):
        if self.transfer_client and self.transfer_machine:
            if self.transfer_tracker is None or self.transfer_tracker.request_pending:
                self.transfer_label.setText("Espera la respuesta de Agent antes de cancelar.")
                return
            client, machine_id = self.transfer_client, self.transfer_machine
            self.cancel_button.setEnabled(False)
            def cancelled(_):
                if self.transfer_tracker:
                    self.transfer_tracker.cancel_acknowledged = True
                self.poll_transfer()
            self.run_job(lambda: client.cancel(machine_id), cancelled, failure=lambda message: (self.cancel_button.setEnabled(True), self.error(message)))

    def error(self, message):
        QMessageBox.warning(self, "ZEUZ Edit", message)

    def closeEvent(self, event):
        reopen = [str(self.tabs.widget(index).file.path) for index in range(self.tabs.count()) if self.tabs.widget(index).file.path]
        for index in reversed(range(self.tabs.count())):
            if not self.confirm_close(self.tabs.widget(index)):
                event.ignore()
                return
        try:
            self.settings.save(reopen=reopen)
        except OSError:
            pass
        self.poll.stop()
        event.accept()


def main():
    import sys
    app = QApplication(sys.argv)
    app.setOrganizationName("Zeuz")
    app.setApplicationName("ZeuzEditDesktop")
    app.setApplicationDisplayName("ZEUZ Edit")
    if "--smoke-test" in sys.argv:
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            window = Window(Settings(Path(temporary) / "settings.json"), restore=False)
            window.editor().setPlainText("%\nO1000\nG21\nT1M6\nG1 X10 Y20 Z-2 F100\nM30\n%\n")
            window.apply(core.renumber)
            assert "N10 G21" in window.editor().toPlainText()
            window.editor().undo()
            assert "N10" not in window.editor().toPlainText()
            window.editor().document().setModified(False)
            window.show()
            app.processEvents()
            window.grab().save(str(Path.cwd() / "zeuzedit-smoke.png"))
            window.close()
        print("ZEUZ Edit desktop smoke test passed")
        return 0
    window = Window()
    for value in sys.argv[1:]:
        if Path(value).is_file():
            window.open_file(Path(value))
    window.show()
    return app.exec()
