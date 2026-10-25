"""Offline Windows Help-style Info panel. No network or WebEngine required."""

from html import escape

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut, QTextCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTreeWidget, QTreeWidgetItem, QTextBrowser, QSplitter,
)

from help_content import TOPICS, TOPIC_BY_ID


class InfoPanel(QWidget):
    """Read-only offline help with chapter navigation and text search."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = {}
        self._history = []
        self._history_pos = -1
        self._active_topic = None

        layout = QVBoxLayout(self)
        headline = QLabel('Help and Information')
        font = headline.font()
        font.setPointSize(max(13, font.pointSize() + 3))
        font.setBold(True)
        headline.setFont(font)
        layout.addWidget(headline)
        subtitle = QLabel('Offline user guide  |  F1 opens help for the active tab  |  Ctrl+F searches this guide')
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        toolbar = QHBoxLayout()
        self.home_button = QPushButton('Home')
        self.home_button.clicked.connect(lambda: self.show_topic('contents'))
        toolbar.addWidget(self.home_button)
        self.back_button = QPushButton('Back')
        self.back_button.clicked.connect(self.go_back)
        toolbar.addWidget(self.back_button)
        self.forward_button = QPushButton('Forward')
        self.forward_button.clicked.connect(self.go_forward)
        toolbar.addWidget(self.forward_button)
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText('Find words in this guide…')
        self.search_field.setClearButtonEnabled(True)
        self.search_field.returnPressed.connect(self.find_next)
        toolbar.addWidget(self.search_field, 1)
        self.find_button = QPushButton('Find next')
        self.find_button.clicked.connect(self.find_next)
        toolbar.addWidget(self.find_button)
        layout.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.contents = QTreeWidget()
        self.contents.setHeaderLabel('Contents')
        self.contents.setMinimumWidth(210)
        self.contents.setRootIsDecorated(True)
        self.contents.itemClicked.connect(self._tree_clicked)
        groups = {}
        for group, slug, title, _body in TOPICS:
            if group not in groups:
                parent_node = QTreeWidgetItem([group])
                parent_node.setFlags(parent_node.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                groups[group] = parent_node
                self.contents.addTopLevelItem(parent_node)
            child = QTreeWidgetItem([title])
            child.setData(0, Qt.ItemDataRole.UserRole, slug)
            groups[group].addChild(child)
            self._items[slug] = child
        self.contents.expandAll()
        self.splitter.addWidget(self.contents)

        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.anchorClicked.connect(self._anchor_clicked)
        self.browser.setHtml(self._render_document())
        self.splitter.addWidget(self.browser)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([265, 890])
        layout.addWidget(self.splitter, 1)

        self.find_status = QLabel('All help topics are available offline.')
        layout.addWidget(self.find_status)
        shortcut = QShortcut(QKeySequence('Ctrl+F'), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.focus_find)
        self.show_topic('contents')

    def _render_document(self):
        palette = self.browser.palette()
        foreground = palette.text().color().name()
        background = palette.base().color().name()
        accent = palette.highlight().color().name()
        header_bg = palette.alternateBase().color().name()
        chapters = []
        for group, slug, title, body in TOPICS:
            chapters.append(
                f'<a name="{slug}"></a>'
                f'<h2>{escape(title)}</h2>'
                f'<p class="crumb">{escape(group)}</p>{body}'
                '<p class="return"><a href="#contents">Back to contents</a></p>'
                '<hr/>'
            )
        toc = []
        current = None
        for group, slug, title, _body in TOPICS:
            if group != current:
                if current is not None:
                    toc.append('</ul>')
                toc.append(f'<h3>{escape(group)}</h3><ul>')
                current = group
            toc.append(f'<li><a href="#{slug}">{escape(title)}</a></li>')
        toc.append('</ul>')
        return (
            '<!DOCTYPE html><html><head><meta charset="UTF-8"/>'
            '<style>'
            f'body {{ color: {foreground}; background-color: {background}; font-size: 11pt; }}'
            f'a {{ color: {accent}; text-decoration: underline; }}'
            f'h1, h2 {{ color: {foreground}; }}'
            f'h2 {{ background-color: {header_bg}; padding: 8px; margin-top: 20px; }}'
            'h3 { margin-top: 14px; }'
            'table { border-collapse: collapse; margin: 9px 0; }'
            'th, td { padding: 6px; vertical-align: top; }'
            'p, li { line-height: 1.4; }'
            f'.crumb {{ color: {foreground}; font-style: italic; }}'
            '</style></head><body>'
            '<a name="contents"></a><h1>Universal Linux Software Manager</h1>'
            '<p><b>Info and Help — Version 1.0.0</b></p>'
            '<p>Choose a topic in the left-hand contents tree, or use the links below. '
            'Press <b>F1</b> on any tab to open its help.</p>'
            + ''.join(toc)
            + '<hr/>' + ''.join(chapters)
            + '</body></html>'
        )

    def _tree_clicked(self, item, _column):
        slug = item.data(0, Qt.ItemDataRole.UserRole)
        if slug:
            self.show_topic(slug)

    def _anchor_clicked(self, url):
        # Do not navigate to external sites from offline help.
        if url.scheme() or url.host():
            return
        slug = url.fragment()
        if slug == 'contents' or slug in TOPIC_BY_ID:
            self.show_topic(slug)

    def show_topic(self, slug, record=True):
        if slug != 'contents' and slug not in TOPIC_BY_ID:
            return False
        self.browser.scrollToAnchor(slug)
        if slug == 'contents':
            self.contents.clearSelection()
        else:
            self.contents.setCurrentItem(self._items[slug])
        self._active_topic = slug
        if record and (not self._history or self._history[self._history_pos] != slug):
            self._history = self._history[:self._history_pos + 1]
            self._history.append(slug)
            self._history_pos += 1
        self._refresh_history_buttons()
        self.find_status.setText('Contents' if slug == 'contents' else 'Chapter: ' + TOPIC_BY_ID[slug][2])
        return True

    def _refresh_history_buttons(self):
        self.back_button.setEnabled(self._history_pos > 0)
        self.forward_button.setEnabled(0 <= self._history_pos < len(self._history) - 1)

    def go_back(self):
        if self._history_pos > 0:
            self._history_pos -= 1
            self.show_topic(self._history[self._history_pos], record=False)

    def go_forward(self):
        if self._history_pos + 1 < len(self._history):
            self._history_pos += 1
            self.show_topic(self._history[self._history_pos], record=False)

    def focus_find(self):
        self.search_field.setFocus()
        self.search_field.selectAll()

    def find_next(self):
        word = self.search_field.text().strip()
        if not word:
            self.focus_find()
            return
        if not self.browser.find(word):
            cursor = self.browser.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.browser.setTextCursor(cursor)
            if not self.browser.find(word):
                self.find_status.setText('No match for: ' + word)
                return
        self.find_status.setText('Find: ' + word + '  (press Enter for the next match)')
