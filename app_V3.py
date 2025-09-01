import sys
import gc
import ctypes
from ctypes import wintypes

import psutil

from PySide6.QtCore import Qt, QTimer, QPoint, QThread, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QAction, QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QHBoxLayout, QVBoxLayout, QToolButton,
    QFrame, QSystemTrayIcon, QMenu, QGraphicsDropShadowEffect
)

# ---------------- Windows API bindings for working set trimming ----------------
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

# ---------------- Memory cleaner thread ----------------
class MemoryCleaner(QThread):
    finished_with_freed = Signal(int)

    def run(self):
        before = psutil.virtual_memory().available

        gc.collect()
        try:
            EmptyWorkingSet(GetCurrentProcess())
        except Exception:
            pass

        for p in psutil.process_iter(attrs=["pid", "name", "username"]):
            pid = p.info["pid"]
            if pid in (0, 4):
                continue
            h = None
            try:
                h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
                if not h:
                    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_QUOTA, False, pid)
                if h:
                    EmptyWorkingSet(h)
            except Exception:
                pass
            finally:
                if h:
                    CloseHandle(h)

        after = psutil.virtual_memory().available
        freed = after - before
        if freed < 0:
            freed = 0
        self.finished_with_freed.emit(int(freed))

# ---------------- Utility: build an icon with an emoji ----------------
def emoji_icon(emoji: str, size: int = 128,
               bg=QColor(32, 48, 79), fg=QColor(220, 230, 255)) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(bg)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)
    font = QFont()
    font.setPointSize(int(size * 0.55))
    painter.setFont(font)
    painter.setPen(fg)
    painter.drawText(pm.rect(), Qt.AlignCenter, emoji)
    painter.end()
    return QIcon(pm)

# ---------------- Main widget ----------------
class MonitorWidget(QWidget):
    def __init__(self):
        super().__init__()

        # Window behavior/look
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.drag_pos = QPoint()
        psutil.cpu_percent(interval=None)  # prime first call

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
                min-width: 28px; min-height: 28px;
            }
            QToolButton:hover { background-color: rgba(255,255,255,26); }
            QToolButton:pressed { background-color: rgba(255,255,255,34); }
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

        # Base font (labels and values share the same font)
        base_font = QFont("Segoe UI", 12, QFont.DemiBold)

        # Static text labels
        self.ram_text = QLabel("RAM:", self.panel)
        self.cpu_text = QLabel("CPU:", self.panel)
        self.ram_text.setFont(base_font)
        self.cpu_text.setFont(base_font)
        self.ram_text.setTextFormat(Qt.PlainText)
        self.cpu_text.setTextFormat(Qt.PlainText)
        self.ram_text.setLayoutDirection(Qt.LeftToRight)
        self.cpu_text.setLayoutDirection(Qt.LeftToRight)

        # Value labels (same font/style as static labels)
        self.ram_val = QLabel(self.panel)
        self.cpu_val = QLabel(self.panel)
        for lbl in (self.ram_val, self.cpu_val):
            lbl.setFont(base_font)
            lbl.setTextFormat(Qt.PlainText)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setLayoutDirection(Qt.LeftToRight)

        # Fix width to fit "100%" so the label area is constant and stable
        fm = QFontMetrics(self.ram_val.font())
        fixed_w = fm.horizontalAdvance("100%")
        self.ram_val.setFixedWidth(fixed_w)
        self.cpu_val.setFixedWidth(fixed_w)

        self.action_btn = QToolButton(self.panel)
        self.action_btn.setText("➜")
        self.action_btn.setToolTip("Open Task Manager")

        # Layout
        h = QHBoxLayout(self.panel)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(10)
        h.addWidget(self.clean_btn)

        ram_box = QHBoxLayout()
        ram_box.setSpacing(6)
        ram_box.addWidget(self.ram_text)
        ram_box.addWidget(self.ram_val)
        ram_wrap = QFrame(self.panel)
        ram_wrap.setLayout(ram_box)
        h.addWidget(ram_wrap)

        cpu_box = QHBoxLayout()
        cpu_box.setSpacing(6)
        cpu_box.addWidget(self.cpu_text)
        cpu_box.addWidget(self.cpu_val)
        cpu_wrap = QFrame(self.panel)
        cpu_wrap.setLayout(cpu_box)
        h.addWidget(cpu_wrap)

        h.addStretch(1)
        h.addWidget(self.action_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.addWidget(self.panel)

        # Smoothing state
        self._disp_ram = 0.0
        self._disp_cpu = 0.0
        self._last_ram_i = -1
        self._last_cpu_i = -1

        # Timer (faster for smoother motion)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.update_stats)
        self.timer.start()

        # Actions
        self.clean_btn.clicked.connect(self.clean_memory)
        self.action_btn.clicked.connect(self.open_task_manager)

        # Tray
        self.tray = QSystemTrayIcon(emoji_icon("🚀"), self)
        self.tray.setToolTip("RAM/CPU Widget")
        tray_menu = QMenu()
        act_show = QAction("Show/Hide", self)
        act_clean = QAction("Clean RAM", self)
        act_quit = QAction("Quit", self)
        act_show.triggered.connect(self.toggle_visible)
        act_clean.triggered.connect(self.clean_memory)
        act_quit.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(act_show)
        tray_menu.addAction(act_clean)
        tray_menu.addSeparator()
        tray_menu.addAction(act_quit)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

        # Toast for freed memory
        self.toast = QLabel("", self.panel)
        self.toast.setStyleSheet("color:#A7FFC4; font-size:10pt;")
        self.toast.hide()
        self.toast_anim = None

        # Size/pos
        self.resize(380, 50)
        self.move_to_corner()
        self.update_stats()

    # ----- UI helpers -----
    def move_to_corner(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 20,
                  screen.bottom() - self.height() - 20)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    # ----- Stats/formatting -----
    @staticmethod
    def ltr_text(text: str) -> str:
        # Prefix with LRM to ensure LTR rendering in plain text
        return "\u200e" + text

    def update_stats(self):
        vm = psutil.virtual_memory()
        ram = float(vm.percent)
        cpu = float(psutil.cpu_percent(interval=None))

        # Exponential smoothing
        alpha = 0.3
        if self._last_ram_i == -1 and self._last_cpu_i == -1 and self._disp_ram == 0.0 and self._disp_cpu == 0.0:
            self._disp_ram = ram
            self._disp_cpu = cpu
        else:
            self._disp_ram += (ram - self._disp_ram) * alpha
            self._disp_cpu += (cpu - self._disp_cpu) * alpha

        ram_i = int(round(self._disp_ram))
        cpu_i = int(round(self._disp_cpu))

        updated_any = False
        if ram_i != self._last_ram_i:
            self.ram_val.setText(self.ltr_text(f"{ram_i}%"))
            self._last_ram_i = ram_i
            updated_any = True
        if cpu_i != self._last_cpu_i:
            self.cpu_val.setText(self.ltr_text(f"{cpu_i}%"))
            self._last_cpu_i = cpu_i
            updated_any = True

        # Ensure background behind labels is repainted to avoid ghosting
        if updated_any:
            self.panel.update(self.ram_val.geometry().adjusted(-2, -2, 2, 2))
            self.panel.update(self.cpu_val.geometry().adjusted(-2, -2, 2, 2))

    # ----- Actions -----
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
            self.ram_val.setText(self.ltr_text("..."))
            self.cpu_val.setText(self.ltr_text("..."))

    def show_freed_toast(self, freed_bytes: int):
        mb = max(0, freed_bytes // (1024 * 1024))
        self.toast.setText(f"Freed {mb} MB")
        self.toast.adjustSize()
        self.toast.move(self.panel.width() - self.toast.width() - 10,
                        self.panel.height() + 2)
        self.toast.setWindowOpacity(1.0)
        self.toast.show()

        if self.toast_anim:
            self.toast_anim.stop()
            self.toast_anim.deleteLater()
        self.toast_anim = QPropertyAnimation(self.toast, b"windowOpacity", self)
        self.toast_anim.setDuration(1800)
        self.toast_anim.setStartValue(1.0)
        self.toast_anim.setEndValue(0.0)
        self.toast_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.toast_anim.finished.connect(self.toast.hide)
        self.toast_anim.start()

    def clean_memory(self):
        self.set_cleaning_ui(True)
        self.cleaner = MemoryCleaner()
        self.cleaner.finished_with_freed.connect(self.on_clean_done)
        self.cleaner.start()

    def on_clean_done(self, freed_bytes: int):
        self.set_cleaning_ui(False)
        self.show_freed_toast(freed_bytes)

    # ----- Tray helpers -----
    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_visible()

def main():
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.LeftToRight)  # app-wide LTR
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(emoji_icon("🧠"))
    w = MonitorWidget()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
