# -*- coding: utf-8 -*-
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from disk_scan import list_physical_disks
from ntfs_recovery import find_ntfs_volumes, scan_deleted_files, recover_file


class RecoveryApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Recovery HDD — восстановление данных")
        self.root.geometry("1020x700")
        self.root.minsize(820, 580)
        self.disks = []
        self.volumes = []
        self.items = []
        self._build()
        self.refresh_disks()

    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="RECOVERY HDD", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Поиск удалённых файлов NTFS • исходный диск только для чтения").pack(
            anchor="w", pady=(2, 12))

        warning = tk.Label(outer,
            text="ВАЖНО: не записывайте ничего на диск, с которого восстанавливаете данные. "
                 "Сохраняйте найденные файлы только на ДРУГОЙ физический диск. "
                 "Результат зависит от того, сохранились ли записи NTFS.",
            bg="#fff1cc", fg="#6b4800", anchor="w", justify="left",
            padx=10, pady=9, wraplength=950)
        warning.pack(fill="x", pady=(0, 12))

        row = ttk.Frame(outer)
        row.pack(fill="x")
        ttk.Label(row, text="Исходный физический диск:").pack(side="left")
        self.disk_var = tk.StringVar()
        self.disk_combo = ttk.Combobox(row, textvariable=self.disk_var,
                                       state="readonly", width=48)
        self.disk_combo.pack(side="left", padx=8)
        ttk.Button(row, text="Обновить", command=self.refresh_disks).pack(side="left")
        self.scan_button = ttk.Button(row, text="Найти удалённые файлы",
                                       command=self.start_scan)
        self.scan_button.pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill="x", pady=10)
        self.status = tk.StringVar(value="Выберите физический диск и запустите поиск.")
        ttk.Label(outer, textvariable=self.status).pack(anchor="w")

        ttk.Label(outer, text="Найденные файлы (путь восстановлен по записям MFT):",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 5))
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        self.results = tk.Listbox(body, font=("Segoe UI", 9), selectmode="extended")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.results.yview)
        self.results.configure(yscrollcommand=scroll.set)
        self.results.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(10, 0))
        self.restore_button = ttk.Button(bottom, text="Восстановить выбранные",
                                         command=self.restore_selected, state="disabled")
        self.restore_button.pack(side="left")
        ttk.Label(bottom, text="Recovery HDD • экспериментальная версия").pack(side="right")

    def refresh_disks(self):
        try:
            self.disks = list_physical_disks()
            values = ["PhysicalDrive%d — %s" % (d["number"], d["size_text"])
                      for d in self.disks]
            self.disk_combo["values"] = values
            if values:
                self.disk_combo.current(0)
                self.status.set("Обнаружено физических дисков: %d" % len(values))
            else:
                self.disk_var.set("")
                self.status.set("Диски не обнаружены. Запустите программу от имени администратора.")
        except Exception as exc:
            messagebox.showerror("Ошибка", str(exc))

    def _progress(self, value, message):
        self.root.after(0, lambda: (self.progress.stop(),
            self.progress.configure(mode="determinate", maximum=100, value=value),
            self.status.set(message)))

    def start_scan(self):
        index = self.disk_combo.current()
        if index < 0 or index >= len(self.disks):
            messagebox.showwarning("Выбор диска", "Сначала выберите исходный физический диск.")
            return
        disk = self.disks[index]
        if not messagebox.askyesno("Подтверждение",
            "Будет выполнено чтение всего PhysicalDrive%d. Никаких изменений на нём не производится.\n\n"
            "Полное сканирование большого диска может занять длительное время. Продолжить?" %
            disk["number"]):
            return
        self.items = []
        self.volumes = []
        self.results.delete(0, "end")
        self.scan_button.configure(state="disabled")
        self.restore_button.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.status.set("Поиск сохранившихся загрузочных секторов NTFS...")
        threading.Thread(target=self._scan_worker, args=(disk["number"],), daemon=True).start()

    def _scan_worker(self, number):
        try:
            volumes = find_ntfs_volumes(number,
                progress=lambda p: self._progress(p, "Поиск NTFS по диску: %d%%" % p))
            all_items = []
            for n, volume in enumerate(volumes):
                self._progress(0, "Анализ MFT: найденный NTFS-том %d из %d" % (n + 1, len(volumes)))
                found = scan_deleted_files(number, volume)
                for item in found:
                    item["volume_index"] = n
                all_items.extend(found)
            self.root.after(0, lambda: self._scan_done(volumes, all_items, None))
        except Exception as exc:
            self.root.after(0, lambda e=str(exc): self._scan_done([], [], e))

    def _scan_done(self, volumes, items, error):
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100)
        self.scan_button.configure(state="normal")
        if error:
            self.status.set("Ошибка поиска.")
            messagebox.showerror("Ошибка сканирования", error)
            return
        self.volumes, self.items = volumes, items
        for item in items:
            size = item["size"]
            size_text = ("%.2f МБ" % (size / 1048576.0)) if size >= 1048576 else ("%d байт" % size)
            self.results.insert("end", "%s    [%s]" % (item.get("path", item["name"]), size_text))
        self.status.set("Найдено NTFS-кандидатов: %d; записей удалённых файлов: %d. "
                        "Это предварительные результаты." % (len(volumes), len(items)))
        if items:
            self.restore_button.configure(state="normal")
        else:
            messagebox.showinfo("Поиск завершён",
                "Записи удалённых файлов не найдены. Возможно, старые метаданные уже перезаписаны "
                "или старый NTFS-раздел не удалось обнаружить.")

    def restore_selected(self):
        selected = list(self.results.curselection())
        if not selected:
            messagebox.showwarning("Выбор файлов", "Выберите один или несколько файлов.")
            return
        folder = filedialog.askdirectory(title="Выберите папку на ДРУГОМ физическом диске")
        if not folder:
            return
        index = self.disk_combo.current()
        disk_number = self.disks[index]["number"]
        if not messagebox.askyesno("Подтверждение восстановления",
            "Будут восстановлены %d выбранных файлов в:\n%s\n\n"
            "Убедитесь, что эта папка находится на другом физическом диске. Продолжить?" %
            (len(selected), folder)):
            return
        restored, errors = 0, []
        for list_index in selected:
            item = self.items[list_index]
            try:
                vol = self.volumes[item["volume_index"]]
                path = recover_file(disk_number, vol, item, folder)
                restored += 1
            except Exception as exc:
                errors.append("%s: %s" % (item.get("path", item["name"]), exc))
        message = "Успешно сохранено файлов: %d" % restored
        if errors:
            message += "\nОшибок: %d\n\n%s" % (len(errors), "\n".join(errors[:10]))
        messagebox.showinfo("Результат восстановления", message)


def main():
    root = tk.Tk()
    RecoveryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
