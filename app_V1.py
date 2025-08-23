import sys
import time
import gc
import ctypes
from ctypes import wintypes
import psutil

from PySide6.QtCore import Qt, QTimer, QPoint, QThread, Signal, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QAction
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QHBoxLayout, QVBoxLayout, QToolButton,
    QFrame, QSystemTrayIcon, QMenu, QGraphicsDropShadowEffect
)

# ============== Windows API bindings for working set trimming ==============
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

EmptyWorkingSet = psapi.EmptyWorkingSet
EmptyWorkingSet.argtypes = [wintypes.HANDLE]
EmptyWorkingSet.restype = wintypes.BOOL

GetCurrentProcess = kernel32.GetCurrentProcess
GetCurrentProcess.restype = wintypes.HANDLE

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # Vista+

# ============== Memory cleaner thread ==============
class MemoryCleaner(QThread):
    finished_with_freed = Signal(int)

    def run(self):
        # Measure available RAM before cleaning
        before = psutil.virtual_memory().available

        # Clean Python's own garbage and trim its working set
        gc.collect()
        try:
            EmptyWorkingSet(GetCurrentProcess())
        except Exception:
            pass

        # Try trimming other processes we can open (no admin required for same-user, non-protected)
        for p in psutil.process_iter(attrs=["pid", "name", "username"]):
            pid = p.info["pid"]
            # Avoid trimming critical/system-like processes
            if pid in (0, 4):  # System Idle, System
                continue
            # Skip if we can't safely open
            h = None
            try:
                # First try with full needed rights
                h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
                if not h:
                    # Try limited info + set quota (some processes allow this)
                    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_QUOTA, False, pid)
                if h:
                    EmptyWorkingSet(h)
            except Exception:
                pass
            finally:
                if h:
                    CloseHandle(h)

        # Measure again
        after = psutil.virtual_memory().available
        freed = after - before
        if freed < 0:
            freed = 0
        self.finished_with_freed.emit(int(freed))


# ============== Utility: create a simple icon with an emoji ==============
def emoji_icon(emoji: str, size: int = 128, bg=QColor(32, 48, 79), fg=QColor(220, 230, 255)):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    # Background circle
    painter.setBrush(bg)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)

    # Emoji
    font = QFont()
    font.setPointSize(int(size * 0.55))
    painter.setFont(font)
    painter.setPen(fg)
    # Center the emoji
    rect = pm.rect()
    painter.drawText(rect, Qt.AlignCenter, emoji)
    painter.end()
    return QIcon(pm)


# ============== Main Widget ==============
class MonitorWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.drag_pos = QPoint()
        self.cpu_last = psutil.cpu_percent(interval=None)  # prime

        # Panel
        self.panel = QFrame(self)
        self.panel.setObjectName("panel")
        self.panel.setStyleSheet("""
            QFrame#panel {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(20,31,52,230), stop:1 rgba(13,24,42,230));
                border: 1px solid rgba(255,255,255,22);
                border-radius: 18px;
            }
            QLabel {
                color: #D6E2FF;
                font-size: 12pt;
                font-weight: 600;
            }
            QToolButton {
                background-color: rgba(255,255,255,18);
                border: 1px solid rgba(255,255,255,22);
                border-radius: 14px;
                color: #D6E2FF;
                font-weight: 700;
                padding: 2px 6px;
            }
            QToolButton:hover {
                background-color: rgba(255,255,255,26);
            }
            QToolButton:pressed {
                background-color: rgba(255,255,255,34);
            }
        """)
        shadow = QGraphicsDropShadowEffect(self.panel)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.panel.setGraphicsEffect(shadow)

        # Controls
        self.clean_btn = QToolButton(self.panel)
        self.clean_btn.setText("🚀")
        self.clean_btn.setToolTip("Clean RAM")
        self.clean_btn.setFixedSize(28, 28)

        self.info_label = QLabel("RAM: 0%   CPU: 0%", self.panel)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self.info_label.setFont(font)

        self.action_btn = QToolButton(self.panel)
        self.action_btn.setText("➜")
        self.action_btn.setToolTip("Open Task Manager")
        self.action_btn.setFixedSize(28, 28)

        # Layout
        h = QHBoxLayout(self.panel)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(10)
        h.addWidget(self.clean_btn)
        h.addWidget(self.info_label)
        h.addStretch(1)
        h.addWidget(self.action_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.addWidget(self.panel)

        # Timer to update stats
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_stats)
        self.timer.start()

        # Button actions
        self.clean_btn.clicked.connect(self.clean_memory)
        self.action_btn.clicked.connect(self.open_task_manager)

        # Tray icon
        self.tray = QSystemTrayIcon(emoji_icon("🚀"), self)
        self.tray.setToolTip("RAM/CPU Widget")
        tray_menu = QMenu()
        act_clean = QAction("Clean RAM", self)
        act_quit = QAction("Quit", self)
        act_clean.triggered.connect(self.clean_memory)
        act_quit.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(act_clean)
        tray_menu.addSeparator()
        tray_menu.addAction(act_quit)
        self.tray.setContextMenu(tray_menu)
        self.tray.show()

        # Feedback label for freed memory
        self.toast = QLabel("", self.panel)
        self.toast.setStyleSheet("color:#A7FFC4; font-size:10pt;")
        self.toast.hide()

        # Size and position
        self.resize(320, 48)
        self.move_to_corner()

    def move_to_corner(self):
        # Place near bottom-right by default
        screen = QApplication.primaryScreen().availableGeometry()
        w = self.width()
        h = self.height()
        self.move(screen.right() - w - 20, screen.bottom() - h - 20)

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def update_stats(self):
        vm = psutil.virtual_memory()
        ram_pct = int(vm.percent)
        cpu_pct = int(psutil.cpu_percent(interval=None))
        self.info_label.setText(f"RAM: {ram_pct}%   CPU: {cpu_pct}%")

    def open_task_manager(self):
        try:
            import subprocess
            subprocess.Popen(["taskmgr"])
        except Exception:
            pass

    def set_cleaning_ui(self, cleaning: bool):
        self.clean_btn.setEnabled(not cleaning)
        self.action_btn.setEnabled(not cleaning)
        if cleaning:
            self.info_label.setText("Cleaning…")
        # else the normal timer will refresh in a second

    def show_freed_toast(self, freed_bytes: int):
        mb = max(0, freed_bytes // (1024 * 1024))
        self.toast.setText(f"Freed {mb} MB")
        self.toast.adjustSize()
        self.toast.move(self.panel.width() - self.toast.width() - 10, self.panel.height() + 2)

        self.toast.show()
        # Fade-out animation
        anim = QPropertyAnimation(self.toast, b"windowOpacity", self)
        anim.setDuration(1800)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        def done():
            self.toast.hide()
            self.toast.setWindowOpacity(1.0)
        anim.finished.connect(done)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def clean_memory(self):
        self.set_cleaning_ui(True)
        self.cleaner = MemoryCleaner()
        self.cleaner.finished_with_freed.connect(self.on_clean_done)
        self.cleaner.start()

    def on_clean_done(self, freed_bytes: int):
        self.set_cleaning_ui(False)
        self.show_freed_toast(freed_bytes)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = MonitorWidget()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
