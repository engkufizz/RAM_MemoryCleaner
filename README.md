# 🧠 RAM/CPU Monitor & Memory Cleaner

A lightweight **Windows desktop widget** built with **PySide6** that displays **CPU and RAM usage in real-time** and includes a **one-click memory cleaner**.  
It also comes with a **system tray icon** for quick access and runs unobtrusively in the background.

---

## ✨ Features

- 📊 **Live monitoring** of CPU and RAM usage (updates every second).  
- 🚀 **One-click RAM cleaner** (calls Windows API `EmptyWorkingSet` for all processes).  
- 🖥️ **Open Task Manager** directly from the widget.  
- 🍃 **Automatic garbage collection** before memory cleanup.  
- 🔔 **Tray integration** with context menu:
  - Show/Hide widget  
  - Clean RAM  
  - Quit app  
- 🎨 **Modern UI** with translucent panel, shadows, and smooth animations.  
- 💡 **Toast notification** after cleanup showing how much memory was freed.  
- 🖱️ **Draggable floating widget** that stays on top of other windows.

---

## ⚙️ Requirements

- **Windows OS** (tested on Windows 10/11).  
- **Python 3.9+**  
- Dependencies:
  - [psutil](https://pypi.org/project/psutil/)  
  - [PySide6](https://pypi.org/project/PySide6/)  

Install them with:

```bash
pip install psutil PySide6
````

---

## 🚀 Usage

Clone this repository and run:

```bash
python app.py
```

* The widget will appear in the bottom-right corner of your screen.
* Use the **🚀 button** to clean memory.
* Use the **➜ button** to open Task Manager.
* The **system tray icon** allows hiding/restoring the widget and quick cleaning.

---

## 🔧 How Memory Cleaning Works

The memory cleaner uses:

* **Python `gc.collect()`** for garbage collection.
* **Windows API `EmptyWorkingSet`** to trim memory usage of processes.
* Frees up unused RAM and displays how many MB were released.

⚠️ Note: Cleaning does not "magically" increase total RAM, it just releases unused pages from processes back to the system.

---

## 🔑 Admin vs Non-Admin Mode

The effectiveness of memory cleaning depends on whether you run the app with Administrator rights:

* **Without Administrator:**

  * Can monitor CPU/RAM normally.
  * Can clean memory only from its own process (and a few user-level processes).
  * Usually frees only a small amount of RAM.

* **With Administrator:**

  * Can access and trim memory of almost all running processes (except critical system ones).
  * Memory cleanup is **much more effective** — often hundreds of MB or more.

👉 For **best results**, run the app as **Administrator**.

---

## 📂 Project Structure

```
app.py        # Main application (widget, tray, memory cleaner)
README.md     # Project documentation
```

---

## 📜 License

MIT License – feel free to use, modify, and share.
