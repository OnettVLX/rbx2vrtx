"""Roblox -> Vortex Studio converter (window version).
Click Open, pick a .rbxlx, it converts, then click Download to save the .vrtx."""
import os, queue, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox
import rbx2vrtx

BG, FG, ACCENT, MUTED = "#ffffff", "#1a1a1a", "#2f6fed", "#777777"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Roblox to Vortex Converter")
        self.geometry("460x400")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.q = queue.Queue()  # worker thread -> window messages
        self.result = None      # converted .vrtx bytes
        self.src_name = "export"

        tk.Label(self, text="Roblox  \u2192  Vortex Studio", font=("Segoe UI", 18, "bold"),
                 bg=BG, fg=FG).pack(pady=(26, 2))
        tk.Label(self, text="Open a Roblox .rbxlx place file to convert it.",
                 font=("Segoe UI", 10), bg=BG, fg=MUTED).pack()

        self.fix_var = tk.BooleanVar(value=True)
        tk.Checkbutton(self, text="Fix old Roblox script calls (recommended)", variable=self.fix_var,
                       bg=BG, fg=FG, activebackground=BG, selectcolor=BG,
                       font=("Segoe UI", 9)).pack(pady=(10, 0))

        self.open_btn = tk.Button(self, text="Open", width=18, font=("Segoe UI", 11, "bold"),
                                  bg=ACCENT, fg="white", activebackground="#1f56c4",
                                  activeforeground="white", relief="flat", pady=8,
                                  cursor="hand2", command=self.on_open)
        self.open_btn.pack(pady=(24, 10))

        self.bar = ttk.Progressbar(self, mode="indeterminate", length=300)
        self.bar.pack(pady=4)

        self.status = tk.Label(self, text="Waiting for a file...", font=("Segoe UI", 9),
                               bg=BG, fg=MUTED, wraplength=420, height=5, justify="center")
        self.status.pack(pady=(6, 6))

        self.dl_btn = tk.Button(self, text="Download", width=18, font=("Segoe UI", 11, "bold"),
                                bg="#e6e6e6", fg="#999999", relief="flat", pady=8,
                                state="disabled", command=self.on_download)
        self.dl_btn.pack()

    def set_status(self, text, color=MUTED):
        self.status.config(text=text, fg=color)

    def on_open(self):
        path = filedialog.askopenfilename(
            title="Open Roblox place file",
            filetypes=[("Roblox place (XML)", "*.rbxlx"), ("All files", "*.*")])
        if not path:
            return
        self.result = None
        self.src_name = os.path.splitext(os.path.basename(path))[0]
        self.open_btn.config(state="disabled")
        self.dl_btn.config(state="disabled", bg="#e6e6e6", fg="#999999", cursor="")
        self.set_status(f"Converting {os.path.basename(path)} ... (big files can take a minute)")
        self.bar.config(mode="indeterminate")
        self.bar.start(12)
        threading.Thread(target=self.work, args=(path, self.fix_var.get()), daemon=True).start()
        self.after(100, self.poll)

    def work(self, path, fix):
        try:
            data, st = rbx2vrtx.build_bytes(path, fix_scripts=fix)
            self.q.put(("ok", data, st))
        except Exception as e:
            self.q.put(("err", e, None))

    def poll(self):
        try:
            kind, a, b = self.q.get_nowait()
        except queue.Empty:
            self.after(100, self.poll)
            return
        if kind == "ok":
            self.done(a, b)
        else:
            self.failed(a)

    def done(self, data, st):
        self.bar.stop()
        self.bar.config(mode="determinate", value=100)
        self.result = data
        self.open_btn.config(state="normal")
        self.dl_btn.config(state="normal", bg="#1e9e4a", fg="white", cursor="hand2")
        msg = "Done!  " + "  ".join(rbx2vrtx.summarize(st))
        self.set_status(msg + " Press Download to save.", "#1e9e4a")

    def failed(self, e):
        self.bar.stop()
        self.bar.config(mode="determinate", value=0)
        self.open_btn.config(state="normal")
        self.set_status("Something went wrong.", "#c62828")
        messagebox.showerror("Conversion failed", f"{type(e).__name__}: {e}")

    def on_download(self):
        if not self.result:
            return
        path = filedialog.asksaveasfilename(
            title="Save Vortex file", defaultextension=".vrtx",
            initialdir=rbx2vrtx.desktop_dir() or os.path.expanduser("~"),
            initialfile=self.src_name + ".vrtx",
            filetypes=[("Vortex Studio project", "*.vrtx")])
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(self.result)
            self.set_status(f"Saved to {path}", "#1e9e4a")
        except Exception as e:
            messagebox.showerror("Could not save", str(e))


if __name__ == "__main__":
    App().mainloop()
