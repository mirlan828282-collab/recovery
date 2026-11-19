# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox
import threading

from disk_scan import list_physical_disks, scan_disk


class RecoveryApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Recovery HDD — восстановление данных")
        self.root.geometry("900x620")
        self.root.minsize(760, 520)
        self.disks = []
        self._build()
        self.refresh_disks()

    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Info.TLabel", font=("Segoe UI", 9))
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="RECOVERY HDD", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Безопасная диагностика диска • режим только чтение",
                  style="Info.TLabel").pack(anchor="w", pady=(2, 14))

        warning = tk.Label(outer,
            text="ВАЖНО: не сохраняйте восстановленные данные на исходный диск. "
                 "Эта версия ничего не записывает на проверяемый диск.",
            bg="#fff1cc", fg="#6b4800", anchor="w", justify="left", padx=10, pady=9,
            wraplength=830)
        warning.pack(fill="x", pady=(0, 12))

        row = ttk.Frame(outer)
        row.pack(fill="x")
        ttk.Label(row, text="Физический диск:").pack(side="left")
        self.disk_var = tk.StringVar()
        self.disk_combo = ttk.Combobox(row, textvariable=self.disk_var,
                                       state="readonly", width=55)
        self.disk_combo.pack(side="left", padx=8)
        ttk.Button(row, text="Обновить", command=self.refresh_disks).pack(side="left")
        self.scan_button = ttk.Button(row, text="Проверить", command=self.start_scan)
        self.scan_button.pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill="x", pady=12)
        self.status = tk.StringVar(value="Готово. Выберите физический диск.")
        ttk.Label(outer, textvariable=self.status).pack(anchor="w")

        ttk.Label(outer, text="Результаты проверки:", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(14, 5))
        self.output = tk.Text(outer, wrap="word", font=("Consolas", 9),
                              bg="#f7f8fa", relief="solid", borderwidth=1)
        self.output.pack(fill="both", expand=True)
        self.output.insert("end",
            "Программа проверит таблицу разделов и загрузочные секторы NTFS.\n"
            "Поиск старых папок и файлов пока не входит в эту диагностическую версию.\n")
        self.output.configure(state="disabled")

        ttk.Label(outer, text="Recovery HDD • предварительная версия",
                  style="Info.TLabel").pack(anchor="e", pady=(8, 0))

    def _write(self, text):
        self.output.configure(state="normal")
        self.output.insert("end", text + "\n")
        self.output.see("end")
        self.output.configure(state="disabled")

    def refresh_disks(self):
        try:
            self.disks = list_physical_disks()
            values = ["\\\\.\\PhysicalDrive%d  —  %s" % (d["number"], d["size_text"])
                      for d in self.disks]
            self.disk_combo["values"] = values
            if values:
                self.disk_combo.current(0)
                self.status.set("Обнаружено физических дисков: %d" % len(values))
            else:
                self.disk_var.set("")
                self.status.set("Физические диски не обнаружены. Запустите программу от имени администратора.")
        except Exception as exc:
            messagebox.showerror("Ошибка", str(exc))

    def start_scan(self):
        index = self.disk_combo.current()
        if index < 0 or index >= len(self.disks):
            messagebox.showwarning("Выбор диска", "Сначала выберите физический диск.")
            return
        disk = self.disks[index]
        if not messagebox.askyesno("Подтверждение",
            "Будет выполнено только чтение диска %d. Продолжить?" % disk["number"]):
            return
        self.scan_button.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Проверка диска...")
        self._write("\n=== Проверка PhysicalDrive%d ===" % disk["number"])
        thread = threading.Thread(target=self._scan_worker, args=(disk["number"],), daemon=True)
        thread.start()

    def _scan_worker(self, number):
        try:
            report = scan_disk(number)
            self.root.after(0, lambda: self._finish(report, None))
        except Exception as exc:
            self.root.after(0, lambda e=str(exc): self._finish(None, e))

    def _finish(self, report, error):
        self.progress.stop()
        self.scan_button.configure(state="normal")
        if error:
            self.status.set("Проверка завершилась с ошибкой.")
            self._write("ОШИБКА: " + error)
            return
        for line in report:
            self._write(line)
        self.status.set("Проверка завершена. Диск не изменялся.")
        self._write("Примечание: найденные сигнатуры требуют дальнейшей проверки; это не восстановленные файлы.")


def main():
    root = tk.Tk()
    RecoveryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
