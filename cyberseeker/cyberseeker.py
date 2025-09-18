#!/usr/bin/env python3
"""
CyberSeeker v2.1 - improved

Improvements since v2.0:
 - whois integration using `whois` (python-whois)
 - Export CSV / JSON
 - Generate HTML report and open in browser
 - Scheduler: run scans periodically (Start Scheduler / Stop Scheduler)
 - Clear Screen (console) button
 - Colored console tags and row color hints in results tree
 - Robust handling when whois library installed but returns little/no data
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
import threading
import socket
import subprocess
import platform
import time
import json
import os
import csv
import ipaddress
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, Empty
import webbrowser

# Optional dependencies
try:
    import requests
except Exception:
    requests = None

try:
    import tkintermapview
except Exception:
    tkintermapview = None

try:
    import whois as pywhois  # python-whois package
except Exception:
    pywhois = None

# Configs
DEFAULT_MAX_WORKERS = 30
DEFAULT_TIMEOUT = 0.6
DEFAULT_RATE_SLEEP = 0.0

def now_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def normalize_target(raw_target: str) -> str:
    if not raw_target:
        return ""
    t = raw_target.strip()
    t = re.sub(r"^https?://", "", t, flags=re.IGNORECASE)
    t = t.split("/")[0]
    return t.strip()

def parse_port_range(s: str):
    s = s.strip()
    if not s:
        return 1, 1024
    if ',' in s:
        raise ValueError("Comma-separated ranges not supported; use dash (e.g. 1-1024)")
    if '-' in s:
        a, b = s.split('-', 1)
        return int(a), int(b)
    p = int(s)
    return p, p

class CyberSeekerApp:
    def __init__(self, root):
        self.root = root
        root.title("🔥 CyberSeeker v2.1 - Advanced Network Recon")
        root.geometry("1200x820")
        root.configure(bg="#0a0a0a")

        # state
        self.log_q = Queue()
        self.scan_cancel = threading.Event()
        self.is_scanning = False
        self.scheduler_thread = None
        self.scheduler_stop = threading.Event()
        self.results = []  # list of dict
        self.history_file = "cyberseeker_history.json"
        self.history = []
        self.load_history()

        # build UI and start consumer
        self.build_ui()
        self.root.after(100, self.consume_log)
        self.log("Application started", "info")

    def build_ui(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('TFrame', background='#0a0a0a')
        style.configure('TLabel', background='#0a0a0a', foreground='#00ff00', font=('Courier New', 10))
        style.configure('TButton', background='#001100', foreground='#00ff00', font=('Courier New', 10, 'bold'))
        style.configure('TEntry', fieldbackground='#001100', foreground='#00ff00', font=('Courier New', 10))
        style.configure('TCombobox', fieldbackground='#001100', foreground='#00ff00')

        # Top controls
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=10, pady=8)

        self.title_label = tk.Label(top, text="🔥 CYBERSEEKER v2.1", bg='#0a0a0a', fg='#00ff00', font=('Courier New', 18, 'bold'))
        self.title_label.pack(side=tk.LEFT)
        self.subtitle_label = tk.Label(top, text=" - Recon & Reporting", bg='#0a0a0a', fg='#00cc00', font=('Courier New', 10))
        self.subtitle_label.pack(side=tk.LEFT, padx=(8,0))

        # Inputs
        inputf = ttk.Frame(self.root)
        inputf.pack(fill=tk.X, padx=10)

        ttk.Label(inputf, text="TARGET:", style='TLabel').pack(side=tk.LEFT, padx=(0,6))
        self.target_entry = ttk.Entry(inputf, width=30)
        self.target_entry.pack(side=tk.LEFT)
        self.target_entry.insert(0, "example.com or 192.168.1.0/24")

        ttk.Label(inputf, text="PORTS:", style='TLabel').pack(side=tk.LEFT, padx=(10,6))
        self.port_entry = ttk.Entry(inputf, width=18)
        self.port_entry.pack(side=tk.LEFT)
        self.port_entry.insert(0, "1-1024")

        ttk.Label(inputf, text="WORKERS:", style='TLabel').pack(side=tk.LEFT, padx=(10,6))
        self.workers_spin = tk.Spinbox(inputf, from_=1, to=200, width=5)
        self.workers_spin.pack(side=tk.LEFT)
        self.workers_spin.delete(0, tk.END); self.workers_spin.insert(0, str(DEFAULT_MAX_WORKERS))

        ttk.Label(inputf, text="RATE(s):", style='TLabel').pack(side=tk.LEFT, padx=(10,6))
        self.rate_entry = ttk.Entry(inputf, width=6)
        self.rate_entry.pack(side=tk.LEFT)
        self.rate_entry.insert(0, str(DEFAULT_RATE_SLEEP))

        # Scheduler controls
        schedf = ttk.Frame(self.root)
        schedf.pack(fill=tk.X, padx=10, pady=(6,0))
        ttk.Label(schedf, text="SCHEDULE (mins):", style='TLabel').pack(side=tk.LEFT)
        self.schedule_spin = tk.Spinbox(schedf, from_=0, to=1440, width=6)  # 0 = disabled
        self.schedule_spin.pack(side=tk.LEFT, padx=(6,10))
        self.schedule_spin.delete(0, tk.END); self.schedule_spin.insert(0, "0")
        ttk.Button(schedf, text="Start Scheduler", command=self.start_scheduler).pack(side=tk.LEFT, padx=(0,6))
        ttk.Button(schedf, text="Stop Scheduler", command=self.stop_scheduler).pack(side=tk.LEFT, padx=(0,6))

        # Scan type
        scanf = ttk.Frame(self.root)
        scanf.pack(fill=tk.X, padx=10, pady=(6,0))
        ttk.Label(scanf, text="SCAN TYPE:", style='TLabel').pack(side=tk.LEFT)
        self.scan_type = tk.StringVar(value="port_scan")
        types = [("Port","port_scan"), ("Ping","ping_sweep"), ("Service","service_detect"),
                 ("OS","os_fingerprint"), ("Vuln","vuln_scan"), ("WHOIS","whois_lookup"),
                 ("DNS","dns_enum")]
        for ttext, tval in types:
            rb = ttk.Radiobutton(scanf, text=ttext, variable=self.scan_type, value=tval, style='TLabel')
            rb.pack(side=tk.LEFT, padx=(8,0))

        # Buttons
        btnf = ttk.Frame(self.root)
        btnf.pack(fill=tk.X, padx=10, pady=(8,0))
        ttk.Button(btnf, text="START SCAN", command=self.start_scan).pack(side=tk.LEFT, padx=(0,6))
        ttk.Button(btnf, text="STOP SCAN", command=self.stop_scan).pack(side=tk.LEFT, padx=(0,6))
        ttk.Button(btnf, text="EXPORT CSV", command=self.export_csv).pack(side=tk.LEFT, padx=(0,6))
        ttk.Button(btnf, text="EXPORT JSON", command=self.export_json).pack(side=tk.LEFT, padx=(0,6))
        ttk.Button(btnf, text="GEN REPORT (HTML)", command=self.generate_report).pack(side=tk.LEFT, padx=(0,6))
        ttk.Button(btnf, text="CLEAR RESULTS", command=self.clear_results).pack(side=tk.LEFT, padx=(0,6))
        ttk.Button(btnf, text="CLEAR SCREEN", command=self.clear_console).pack(side=tk.LEFT, padx=(0,6))

        # Notebook
        nbf = ttk.Frame(self.root)
        nbf.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.notebook = ttk.Notebook(nbf)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Console tab
        console_tab = ttk.Frame(self.notebook)
        self.notebook.add(console_tab, text="CONSOLE")
        self.console = ScrolledText(console_tab, bg='#001100', fg='#00ff00', insertbackground='#00ff00', font=('Courier New', 10))
        self.console.pack(fill=tk.BOTH, expand=True)
        self.console.config(state=tk.DISABLED)

        # Results tab
        results_tab = ttk.Frame(self.notebook)
        self.notebook.add(results_tab, text="RESULTS")
        cols = ("timestamp","target","ip","port","service","status","banner","notes")
        self.results_tree = ttk.Treeview(results_tab, columns=cols, show='headings', selectmode='browse')
        for c in cols:
            self.results_tree.heading(c, text=c.upper())
            self.results_tree.column(c, width=120)
        self.results_tree.pack(fill=tk.BOTH, expand=True)
        # color tags for rows via tags are limited; we'll color text in console and use "status" column for quick inference

        # History tab
        history_tab = ttk.Frame(self.notebook)
        self.notebook.add(history_tab, text="HISTORY")
        self.history_list = ttk.Treeview(history_tab, columns=("ts","action","data"), show='headings')
        self.history_list.heading("ts", text="TIMESTAMP"); self.history_list.column("ts", width=150)
        self.history_list.heading("action", text="ACTION"); self.history_list.column("action", width=150)
        self.history_list.heading("data", text="DATA"); self.history_list.column("data", width=700)
        self.history_list.pack(fill=tk.BOTH, expand=True)
        self.refresh_history_view()

        # Status bar
        statusf = ttk.Frame(self.root)
        statusf.pack(fill=tk.X, padx=10, pady=(0,10))
        self.status_label = ttk.Label(statusf, text="READY", style='TLabel')
        self.status_label.pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(statusf, mode='indeterminate')
        self.progress.pack(side=tk.RIGHT, fill=tk.X, expand=True)

    # ---- logging queue consumer ----
    def log(self, message, level="info"):
        self.log_q.put({"ts": now_ts(), "msg": message, "level": level})

    def consume_log(self):
        try:
            while True:
                item = self.log_q.get_nowait()
                ts = item["ts"]; msg = item["msg"]; lvl = item["level"]
                self._append_console(f"[{ts}] {msg}\n", lvl)
        except Empty:
            pass
        self.root.after(150, self.consume_log)

    def _append_console(self, text, level):
        color = "#00ff00"
        if level == "error": color = "#ff4444"
        elif level == "warning": color = "#ffee00"
        elif level == "success": color = "#00ff88"
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, text)
        # tag last line
        self.console.tag_add(level, "end -1 lines linestart", "end -1 lines lineend")
        self.console.tag_config(level, foreground=color)
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)

    def clear_console(self):
        self.console.config(state=tk.NORMAL)
        self.console.delete(1.0, tk.END)
        self.console.config(state=tk.DISABLED)
        self.log("Console cleared", "info")

    # ---- history persistence ----
    def load_history(self):
        self.history = []
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r") as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []

    def save_history_item(self, action, data):
        entry = {"ts": now_ts(), "action": action, "data": data}
        self.history.append(entry)
        try:
            with open(self.history_file, "w") as f:
                json.dump(self.history, f, indent=2)
        except Exception:
            pass
        self.refresh_history_view()

    def refresh_history_view(self):
        for i in self.history_list.get_children():
            self.history_list.delete(i)
        for h in self.history:
            self.history_list.insert('', 'end', values=(h.get("ts"), h.get("action"), json.dumps(h.get("data"))))

    # ---- scan control ----
    def start_scan(self):
        if self.is_scanning:
            self.log("Scan already in progress", "warning")
            return
        raw = self.target_entry.get().strip()
        target = normalize_target(raw)
        if not target:
            self.log("Enter a target", "error")
            return
        # confirmation
        if not messagebox.askyesno("Confirm", "Make sure you have permission to scan this target. Continue?"):
            return
        try:
            start_port, end_port = parse_port_range(self.port_entry.get().strip())
        except Exception as e:
            self.log(f"Invalid port range: {e}", "error")
            return
        try:
            workers = int(self.workers_spin.get())
        except Exception:
            workers = DEFAULT_MAX_WORKERS
        try:
            rate = float(self.rate_entry.get())
        except Exception:
            rate = DEFAULT_RATE_SLEEP

        st = threading.Thread(target=self._run_scan_thread, args=(target, self.scan_type.get(), start_port, end_port, workers, rate), daemon=True)
        st.start()
        self.is_scanning = True
        self.progress.start()
        self.update_status("SCANNING")
        self.save_history_item("start_scan", {"target": target, "type": self.scan_type.get(), "ports": f"{start_port}-{end_port}"})
        self.log(f"Starting {self.scan_type.get()} on {target}", "info")

    def stop_scan(self):
        if not self.is_scanning:
            self.log("No scan in progress", "warning")
            return
        self.scan_cancel.set()
        self.is_scanning = False
        self.progress.stop()
        self.update_status("STOPPED")
        self.log("Scan stopped by user", "warning")
        self.save_history_item("stop_scan", {})

    def _run_scan_thread(self, target, scan_type, start_port, end_port, workers, rate):
        self.scan_cancel.clear()
        try:
            if scan_type == "port_scan":
                self._port_scan(target, start_port, end_port, workers, rate)
            elif scan_type == "ping_sweep":
                self._ping_sweep(target)
            elif scan_type == "service_detect":
                self._service_detect(target, start_port, end_port, workers, rate)
            elif scan_type == "os_fingerprint":
                self._os_fingerprint(target)
            elif scan_type == "vuln_scan":
                self._vuln_scan(target)
            elif scan_type == "whois_lookup":
                self._whois_lookup(target)
            elif scan_type == "dns_enum":
                self._dns_enum(target)
        except Exception as e:
            self.log(f"Scan error: {e}", "error")
        finally:
            self.is_scanning = False
            self.progress.stop()
            self.update_status("READY")
            self.log("Scan finished", "info")
            self.save_history_item("scan_finished", {"target": target, "type": scan_type})

    # ---- scan implementations ----
    def _resolve(self, target):
        try:
            return socket.gethostbyname(target)
        except Exception:
            return None

    def _port_scan(self, target, start_port, end_port, workers, rate):
        ip = self._resolve(target)
        if not ip:
            self.log(f"Could not resolve {target}", "error")
            return
        self.log(f"Resolved {target} -> {ip}", "info")
        self.update_status("PORT SCANNING")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(self._scan_port_task, ip, p): p for p in range(start_port, end_port+1)}
            for fut in as_completed(futures):
                if self.scan_cancel.is_set():
                    break
                res = fut.result()
                if res:
                    self._record_result(res)
                if rate > 0:
                    time.sleep(rate)
        self.log("Port scan finished", "info")

    def _scan_port_task(self, ip, port):
        if self.scan_cancel.is_set():
            return None
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(DEFAULT_TIMEOUT)
        try:
            r = sock.connect_ex((ip, port))
            if r == 0:
                service = self.get_service_name(port)
                banner = ""
                try:
                    sock.sendall(b"\r\n")
                    banner = sock.recv(1024).decode(errors='ignore').strip()
                except Exception:
                    pass
                return {"timestamp": now_ts(), "target": ip, "ip": ip, "port": port, "service": service, "status": "OPEN", "banner": banner, "notes": ""}
        except Exception:
            pass
        finally:
            sock.close()
        return None

    def _ping_sweep(self, target):
        # accept CIDR or single host
        try:
            hosts = [str(h) for h in ipaddress.ip_network(target, strict=False).hosts()] if '/' in target else [target]
        except Exception:
            self.log("Invalid target/network", "error")
            return
        self.update_status("PING SWEEP")
        for h in hosts:
            if self.scan_cancel.is_set():
                break
            self._ping_one(h)

    def _ping_one(self, host):
        param = '-n' if platform.system().lower()=='windows' else '-c'
        cmd = ['ping', param, '1', host]
        try:
            out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
            if out.returncode == 0:
                self.log(f"Host {host} is UP", "success")
                self.results_tree.insert('', 'end', values=(now_ts(), host, host, 'ICMP', 'UP', '', ''))
            else:
                self.log(f"Host {host} is DOWN", "info")
        except subprocess.TimeoutExpired:
            self.log(f"Host {host} timed out", "warning")

    def _service_detect(self, target, start_port, end_port, workers, rate):
        self._port_scan(target, start_port, end_port, workers, rate)
        self.log("Service detection (basic) complete", "info")

    def _os_fingerprint(self, target):
        ip = self._resolve(target)
        if not ip:
            self.log(f"Could not resolve {target}", "error")
            return
        param = '-n' if platform.system().lower()=='windows' else '-c'
        cmd = ['ping', param, '1', ip]
        try:
            out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            if out.returncode == 0:
                txt = out.stdout.decode(errors='ignore')
                m = re.search(r"TTL[=:]?(\d+)", txt, re.IGNORECASE)
                if m:
                    ttl = int(m.group(1))
                    guess = "Linux/Unix" if ttl <= 64 else "Windows" if ttl <= 128 else "Other"
                    self.log(f"OS guess for {ip}: TTL={ttl} -> {guess}", "success")
                else:
                    self.log("Could not parse TTL", "warning")
            else:
                self.log("No ping response", "warning")
        except Exception as e:
            self.log(f"OS fingerprint error: {e}", "error")

    def _vuln_scan(self, target):
        ip = self._resolve(target)
        if not ip:
            self.log(f"Could not resolve {target}", "error")
            return
        self.update_status("VULN SCAN")
        for port in (80,443,8080,8443):
            if self.scan_cancel.is_set():
                break
            try:
                proto = "https" if port in (443,8443) else "http"
                url = f"{proto}://{ip}:{port}"
                if requests:
                    try:
                        r = requests.get(url, timeout=3, verify=False)
                        server = r.headers.get("Server","Unknown")
                        self.log(f"{url} -> Server: {server}", "info")
                        notes=[]
                        if "Apache" in server and "2.4" not in server:
                            notes.append("Apache - old?")
                        if notes:
                            self.results.append({"timestamp": now_ts(),"target": target,"ip":ip,"port":port,"service":"HTTP","status":"OPEN","banner":server,"notes":", ".join(notes)})
                            self.results_tree.insert('', 'end', values=(now_ts(), target, ip, port, "HTTP", "OPEN", server, ", ".join(notes)))
                    except Exception:
                        pass
            except Exception:
                pass
        self.log("Vuln checks finished", "info")

    def _whois_lookup(self, target):
        t = normalize_target(target)
        self.update_status("WHOIS")
        if not pywhois:
            self.log("python-whois not installed. Install with: pip install python-whois", "error")
            return
        try:
            self.log(f"Querying WHOIS for {t} (this may take a few seconds)...", "info")
            w = pywhois.whois(t)
            # w may be dict-like or object; try to extract main fields safely
            info = {}
            for k in ("domain_name","registrar","whois_server","creation_date","expiration_date","name","org","emails","status"):
                try:
                    v = getattr(w, k, None) if hasattr(w, k) else w.get(k) if isinstance(w, dict) else None
                    info[k] = v
                except Exception:
                    info[k] = None
            # present summary in console and results
            pretty = json.dumps({k:v for k,v in info.items() if v}, default=str, indent=2)
            if not pretty.strip():
                pretty = "WHOIS returned no usable fields."
            self.log(pretty, "info")
            # insert into tree for user to save/export
            self.results_tree.insert('', 'end', values=(now_ts(), t, "", "", "WHOIS", "INFO", "", pretty))
            self.results.append({"timestamp": now_ts(), "target": t, "ip":"", "port":"", "service":"WHOIS", "status":"INFO", "banner":"", "notes": pretty})
        except Exception as e:
            self.log(f"WHOIS error: {e}", "error")

    def _dns_enum(self, target):
        t = normalize_target(target)
        self.update_status("DNS ENUM")
        try:
            ip = socket.gethostbyname(t)
            self.log(f"{t} -> {ip}", "info")
            try:
                rev = socket.gethostbyaddr(ip)[0]
                self.log(f"Reverse DNS: {ip} -> {rev}", "info")
                self.results_tree.insert('', 'end', values=(now_ts(), t, ip, "", "DNS", "PTR", rev, ""))
                self.results.append({"timestamp": now_ts(), "target": t, "ip": ip, "port":"", "service":"DNS", "status":"PTR", "banner":rev, "notes":""})
            except Exception:
                self.log("No PTR record", "info")
        except Exception as e:
            self.log(f"DNS enumeration failed: {e}", "error")

    # ---- result handling / export / report ----
    def _record_result(self, r):
        if not r:
            return
        self.results.append(r)
        self.results_tree.insert('', 'end', values=(r["timestamp"], r["target"], r["ip"], r["port"], r["service"], r["status"], r["banner"], r["notes"]))
        # do not auto-open maps to avoid spam/leaks

    def export_csv(self):
        if not self.results and not self.results_tree.get_children():
            messagebox.showinfo("Export", "No results to export")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp","target","ip","port","service","status","banner","notes"])
                for r in self.results:
                    writer.writerow([r.get("timestamp"), r.get("target"), r.get("ip"), r.get("port"), r.get("service"), r.get("status"), r.get("banner"), r.get("notes")])
            messagebox.showinfo("Export", f"Exported {len(self.results)} results to {path}")
            self.save_history_item("export_csv", {"path": path, "rows": len(self.results)})
            self.log(f"Exported results to {path}", "success")
        except Exception as e:
            messagebox.showerror("Export error", str(e))
            self.log(f"Export error: {e}", "error")

    def export_json(self):
        if not self.results:
            messagebox.showinfo("Export", "No results to export")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.results, f, indent=2, default=str)
            messagebox.showinfo("Export", f"Exported {len(self.results)} results to {path}")
            self.save_history_item("export_json", {"path": path, "rows": len(self.results)})
            self.log(f"Exported results to {path}", "success")
        except Exception as e:
            messagebox.showerror("Export error", str(e))
            self.log(f"Export error: {e}", "error")

    def generate_report(self):
        if not self.results:
            messagebox.showinfo("Report", "No results to include in report")
            return
        path = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML","*.html")])
        if not path:
            return
        try:
            title = "CyberSeeker Report"
            html = [f"<html><head><meta charset='utf-8'><title>{title}</title></head><body style='background:#0a0a0a;color:#00ff00;font-family:monospace'><h2>{title}</h2><p>Generated: {now_ts()}</p><table border='1' cellpadding='6' style='color:#00ff00'>"]
            html.append("<tr><th>timestamp</th><th>target</th><th>ip</th><th>port</th><th>service</th><th>status</th><th>banner</th><th>notes</th></tr>")
            for r in self.results:
                html.append("<tr>" + "".join(f"<td>{str(r.get(k,''))}</td>" for k in ["timestamp","target","ip","port","service","status","banner","notes"]) + "</tr>")
            html.append("</table></body></html>")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(html))
            webbrowser.open(f"file://{os.path.abspath(path)}")
            self.save_history_item("generate_report", {"path": path, "rows": len(self.results)})
            self.log(f"Report generated: {path}", "success")
        except Exception as e:
            self.log(f"Report error: {e}", "error")
            messagebox.showerror("Report error", str(e))

    def clear_results(self):
        if messagebox.askyesno("Confirm", "Clear results table and memory?"):
            for i in self.results_tree.get_children():
                self.results_tree.delete(i)
            self.results.clear()
            self.log("Results cleared", "info")
            self.save_history_item("clear_results", {})

    # ---- scheduler ----
    def start_scheduler(self):
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.log("Scheduler already running", "warning")
            return
        try:
            mins = int(self.schedule_spin.get())
        except Exception:
            self.log("Invalid schedule value", "error")
            return
        if mins <= 0:
            self.log("Set schedule minutes > 0 to enable", "warning")
            return
        self.scheduler_stop.clear()
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, args=(mins,), daemon=True)
        self.scheduler_thread.start()
        self.log(f"Scheduler started, interval {mins} minutes", "success")
        self.save_history_item("start_scheduler", {"interval_mins": mins})

    def stop_scheduler(self):
        if not self.scheduler_thread or not self.scheduler_thread.is_alive():
            self.log("Scheduler not running", "warning")
            return
        self.scheduler_stop.set()
        self.log("Scheduler stop requested", "info")
        self.save_history_item("stop_scheduler", {})

    def _scheduler_loop(self, mins):
        self.log("Scheduler loop active", "info")
        interval = max(1, mins) * 60
        while not self.scheduler_stop.is_set():
            # perform a scan with current UI parameters
            target = normalize_target(self.target_entry.get().strip())
            scan_type = self.scan_type.get()
            try:
                sp, ep = parse_port_range(self.port_entry.get().strip())
            except Exception:
                sp, ep = 1, 1024
            workers = int(self.workers_spin.get()) if self.workers_spin.get().isdigit() else DEFAULT_MAX_WORKERS
            rate = float(self.rate_entry.get()) if self.rate_entry.get() else DEFAULT_RATE_SLEEP
            # run scan (blocking here in scheduler thread)
            self.log(f"[Scheduler] Running {scan_type} on {target}", "info")
            self._run_scan_thread(target, scan_type, sp, ep, workers, rate)
            # sleep interval
            for _ in range(int(interval)):
                if self.scheduler_stop.is_set():
                    break
                time.sleep(1)
        self.log("Scheduler stopped", "info")

    # ---- helpers ----
    def update_status(self, text):
        try:
            self.status_label.config(text=text)
        except Exception:
            pass

    def save_history_item(self, action, data):
        entry = {"ts": now_ts(), "action": action, "data": data}
        self.history.append(entry)
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2)
        except Exception:
            pass
        self.refresh_history_view()

    def refresh_history_view(self):
        for i in self.history_list.get_children():
            self.history_list.delete(i)
        for h in self.history:
            self.history_list.insert('', 'end', values=(h.get("ts"), h.get("action"), json.dumps(h.get("data"))))

    def get_service_name(self, port):
        common = {20:"FTP",21:"FTP",22:"SSH",23:"Telnet",25:"SMTP",53:"DNS",80:"HTTP",110:"POP3",143:"IMAP",443:"HTTPS",3306:"MySQL",3389:"RDP"}
        return common.get(port, "Unknown")

if __name__ == "__main__":
    root = tk.Tk()
    app = CyberSeekerApp(root)
    root.mainloop()
