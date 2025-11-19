import os
import sys
import json
import ast
import subprocess
import importlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import xml.etree.ElementTree as ET
from typing import Optional, Tuple
import platform

# ==========================================================
# 🔧 Ensure all required packages are installed automatically
# ==========================================================

PYTHON_PATH = sys.executable

# Extract the Python root directory (the folder where python.exe sits)
PYTHON_ROOT = os.path.dirname(PYTHON_PATH)

# Build path to tal inside Lib/site-packages
EXTRA_LIB_ROOT = os.path.join(PYTHON_ROOT, "Lib", "site-packages", "tal")


def ensure_package(pkg_name, import_name=None):
    """Automatically install a pip package if missing."""
    import_name = import_name or pkg_name
    try:
        importlib.import_module(import_name)
    except ImportError:
        print(f"📦 Installing missing package: {pkg_name} ...")
        subprocess.check_call([PYTHON_PATH, "-m", "pip", "install", pkg_name, "-q"])
        print(f"✅ {pkg_name} installed.")
    finally:
        globals()[import_name] = importlib.import_module(import_name)

# --- Required GUI and Excel libraries ---
ensure_package("customtkinter")

# ==========================================================
# 📦 Now safely import external modules
# ==========================================================
import customtkinter as ctk

# tal root stays the same

class TestStepTreeApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("MAIA - Scripted Test Steps Selector")
        self.geometry("1520x850")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # will be set by auto-detect below
        self.project_root = None
        self.checked_steps = {}
        self.workspace_root = None   # <— add this

        # Default editor path (Notepad++ preferred)
        self.editor_path = r"C:\Program Files\Notepad++\notepad++.exe"
        if not os.path.exists(self.editor_path):
            self.editor_path = "notepad.exe"

        # layout
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=5)
        self._diag_impl_cache = None  # (module_name, class_name) cache
        self._diag_type_raw = None    # e.g. "uds.symbolic"

        # ===== header =====
        header = ctk.CTkFrame(self, corner_radius=0, height=48, fg_color="#131722")
        header.grid(row=0, column=0, columnspan=4, sticky="nsew")
        header.grid_columnconfigure(0, weight=1)
        # will be updated once we know the project root
        self.title_label = ctk.CTkLabel(
            header,
            text="Project – Test Steps",
            font=("Calibri", 16, "bold"),
        )
        self.title_label.grid(row=0, column=0, sticky="w", padx=14, pady=8)

        self.root_label = ctk.CTkLabel(
            header,
            text="Root: (not selected)",
            font=("Calibri", 15, "italic"),
        )
        self.root_label.grid(row=0, column=1, sticky="e", padx=(0, 10))

        ctk.CTkButton(
            header,
            text="Browse…",
            width=100,
            fg_color="#1aa3a3",
            hover_color="#148080",
            text_color="white",
            font=("Segoe UI", 13, "bold"),
            corner_radius=12,
            border_width=1,
            border_color="#0b4f4f",
            command=self.browse_for_root,
        ).grid(row=0, column=2, sticky="e", padx=10, pady=8)

        # ===== left (tree) =====
        left_frame = ctk.CTkFrame(self, fg_color="#181c27")
        left_frame.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(6, 8))
        left_frame.grid_rowconfigure(0, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(left_frame, show="tree")
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(left_frame, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)

        self.checked_steps = {}
        self.workspace_root = None   # <— already there
        self.step_sources = {}       # <— ADD THIS

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Treeview",
            background="#181c27",
            foreground="white",
            fieldbackground="#181c27",
            font=("Segoe UI", 10),
            rowheight=26,
            bordercolor="#181c27",
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", "#2c5f5a")])

        self.tree.tag_configure("info_tag", font=("Calibri", 11, "italic"), foreground="#8ab4ff")
        self.tree.tag_configure("folder_tag", font=("Calibri", 12, "bold"), foreground="#FFFFFF")
        self.tree.tag_configure("file_tag", font=("Calibri", 11, "normal"))
        self.tree.tag_configure("method_tag", font=("Calibri", 11, "italic"))
        self.tree.tag_configure(
            "checked_tag",
            foreground="#5ad2ff",
            background="#23313f",
            font=("Segoe UI Semibold", 12)
        )

        # ===== right (preview) =====
        right_frame = ctk.CTkFrame(self, fg_color="#181c27")
        right_frame.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=(6, 8))
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            right_frame, text="Selected steps (preview)", font=("Segoe UI", 14, "bold")
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 4))

        self.preview = ctk.CTkTextbox(
            right_frame, wrap="none", font=("Consolas", 12), fg_color="#0f1117"
        )
        self.preview.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        bottom = ctk.CTkFrame(right_frame, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
        bottom.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            bottom,
            text="💾 Export JSON",
            fg_color="#6c4ad1",
            hover_color="#5539aa",
            text_color="white",
            font=("Segoe UI", 11, "bold"),
            corner_radius=12,
            border_width=1,
            border_color="#3d287e",
            command=self.export_json,
            height=32,
        ).grid(row=0, column=0, padx=(0, 12))

        self.status_label = ctk.CTkLabel(bottom, text="0 steps selected", anchor="w")
        self.status_label.grid(row=0, column=1, sticky="w")

        # events
        self.tree.bind("<<TreeviewOpen>>", self.on_tree_open)
        self.tree.bind("<Button-1>", self.on_tree_click)

        # right-click menu
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Open in editor", command=self._open_selected_in_editor)
        self.tree.bind("<Button-3>", self.on_tree_right_click)

        # 🔎 auto-detect ...\Workspaces\<project>\ProjectComponents
        self._autodetect_project_root()

    # === PATCH: add to class TestStepTreeApp ===
    def _diagnosis_type_to_class(self, diag_type: str) -> Optional[str]:
        """
        Map 'uds.symbolic' -> 'UdsSymbolic', etc.
        Extend this mapping as needed.
        """
        if not diag_type:
            return None
        diag_type = diag_type.strip().lower()
        mapping = {
            "uds.symbolic": "UdsSymbolic",
            "uds.raw": "UdsRaw",
            "uds.obd": "UdsObd",
            "uds.odis": "UdsOdis",
            "uds.odibas": "UdsOdibas",
        }
        return mapping.get(diag_type)

    def _update_header_project_name(self):
        """
        Update the 'Project – Test Steps' label with the actual project name
        inferred from the project_root path:
            ...\Workspaces\<PROJECT_NAME>\ProjectComponents
        """
        if not self.project_root:
            self.title_label.configure(text="Project – Test Steps")
            return

        # project_root = ...\Workspaces\<project>\ProjectComponents
        workspace_dir = os.path.dirname(self.project_root)      # ...\Workspaces\<project>
        project_name = os.path.basename(workspace_dir)          # <project>

        self.title_label.configure(text=f"{project_name} – Test Steps")


    def _find_devices_cfgs(self) -> list[str]:
        """
        Return the best matching *_devices.cfg under <workspace_root>\Config\Devices.

        Preference order:
        1. <station>_devices.cfg   (where <station> is the platform/host name)
        2. devices.cfg / device.cfg
        3. (optional) nothing -> caller will treat as not resolved
        """
        if not self.workspace_root:
            return []

        devices_dir = os.path.join(self.workspace_root, "Config", "Devices")
        if not os.path.isdir(devices_dir):
            return []

        # All .cfg files in Devices folder
        all_cfgs = [f for f in os.listdir(devices_dir) if f.lower().endswith(".cfg")]
        if not all_cfgs:
            print(f"[DiagResolution] No .cfg files found in {devices_dir}")
            return []

        # 1) Try station-specific: <station>_devices.cfg
        station = platform.node().lower()  # e.g. 'iads197n'
        selected: list[str] = []

        if station:
            wanted = f"{station}_devices.cfg"
            for name in all_cfgs:
                if name.lower() == wanted:
                    selected.append(os.path.join(devices_dir, name))
                    break  # exact match, we’re done

        # 2) Fallback to generic devices.cfg / device.cfg
        if not selected:
            for generic in ("devices.cfg", "device.cfg"):
                for name in all_cfgs:
                    if name.lower() == generic:
                        selected.append(os.path.join(devices_dir, name))
                        break
                if selected:
                    break

        # 3) If still nothing → report and let caller treat as "not resolved"
        if not selected:
            print(
                f"[DiagResolution] No matching devices cfg found for station "
                f"'{station}' in {devices_dir}. "
                "Expected '<station>_devices.cfg' or 'devices.cfg'/'device.cfg'."
            )
            return []

        return selected

    def _resolve_diag_impl_from_cfg(self) -> Optional[Tuple[str, str]]:
        """
        Inspect *_devices.cfg and return ('ProjectComponents.Diagnosis', '<ClassName>')
        for the TAL-DEVICE named 'DiagnosisInterface'.
        Cached after first success.
        """
        if self._diag_impl_cache:
            return self._diag_impl_cache

        for cfg in self._find_devices_cfgs():
            try:
                tree = ET.parse(cfg)
                root = tree.getroot()
            except Exception:
                continue

            # Find TAL-DEVICE with name='DiagnosisInterface'
            for dev in root.findall(".//TAL-DEVICE"):
                name = dev.get("name") or dev.get("NAME") or ""
                if name.strip().lower() != "diagnosisinterface":
                    continue

                diag_type = dev.get("type") or dev.get("TYPE") or ""
                cls = self._diagnosis_type_to_class(diag_type)
                if not cls:
                    # Try looking for a PARM like <PARM name="type" value="uds.symbolic"/>
                    for p in dev.findall(".//PARM"):
                        if (p.get("name") or "").strip().lower() == "type":
                            cls = self._diagnosis_type_to_class(p.get("value") or "")
                            if cls:
                                break
                if cls:
                    # Remember raw type (e.g. "uds.symbolic") for display
                    self._diag_type_raw = diag_type.strip() or None
                    # UDS classes are in tal.FunctionalComponents.Diagnosis.DiagnosisInterface
                    self._diag_impl_cache = (
                        "tal.FunctionalComponents.Diagnosis.DiagnosisInterface",
                        cls,
                    )
                    return self._diag_impl_cache

        # nothing found
        return None

    def _get_diag_description(self) -> str:
        """
        Build a human-readable description of the currently resolved diagnosis type,
        e.g. 'Diagnosis: uds.symbolic → UdsSymbolic (tal.FunctionalComponents.Diagnosis.DiagnosisInterface)'
        """
        resolved = self._resolve_diag_impl_from_cfg()
        if not resolved:
            return "Diagnosis: (not resolved)"

        mod, cls = resolved
        if self._diag_type_raw:
            return f"Diagnosis: {self._diag_type_raw} \u2192 {cls} ({mod})"
        else:
            return f"Diagnosis: {cls} ({mod})"

    # -----------------------------------------------------------
    # helper to keep only PascalCase-like names
    # -----------------------------------------------------------
    def _is_camel_step(self, name: str) -> bool:
        """
        Keep only names like 'BatterySetVoltage':
        - start with uppercase
        - no underscores
        """
        if not name:
            return False
        if not name[0].isupper():
            return False
        if "_" in name:
            return False
        return True

    # -----------------------------------------------------------
    # auto detect
    # -----------------------------------------------------------
    def _autodetect_project_root(self):
        script_dir = os.path.abspath(os.path.dirname(__file__))
        parts = script_dir.split(os.sep)

        if "Workspaces" in parts:
            idx = parts.index("Workspaces")
            if idx + 1 < len(parts):
                project_dir = os.sep.join(parts[: idx + 2])
                pc_dir = os.path.join(project_dir, "ProjectComponents")
                if os.path.isdir(pc_dir):
                    self.project_root = pc_dir
                    self.workspace_root = os.path.dirname(self.project_root)
                    self.root_label.configure(text=f"Root: {self.project_root}")
                    self._update_header_project_name()
                    self.populate_root()
                    return


        self.tree.insert(
            "",
            "end",
            text="☐ ❗ Please select your ProjectComponents root (Browse…)",
            values=("info", ""),
            tags=("info_tag",),
        )

    # ==================================================================
    # BROWSE / TREE / PARSE / EXPORT
    # ==================================================================
    def browse_for_root(self):
        new_root = filedialog.askdirectory(title="Select ProjectComponents root")
        if not new_root:
            return

        self.project_root = new_root
        # keep workspace_root in sync for Devices cfg detection
        self.workspace_root = os.path.dirname(self.project_root)

        self.root_label.configure(text=f"Root: {self.project_root}")
        self._update_header_project_name()

    def populate_root(self):
        if not self.project_root or not os.path.isdir(self.project_root):
            return

        root_id = self.tree.insert(
            "",
            "end",
            text=self._unchecked("🧱 " + (os.path.basename(self.project_root) or self.project_root)),
            open=True,
            values=("root", self.project_root),
            tags=("folder_tag",),
        )

        for name in sorted(os.listdir(self.project_root)):
            full = os.path.join(self.project_root, name)
            if os.path.isdir(full) and name != "__pycache__":
                folder_id = self.tree.insert(
                    root_id,
                    "end",
                    text=self._unchecked("📁 " + name),
                    values=("folder", full),
                    tags=("folder_tag",),
                )
                self.tree.insert(folder_id, "end", text="...", values=("dummy", ""))

    def on_tree_open(self, event):
        item_id = self.tree.focus()
        node_type, payload = self.get_node_info(item_id)
        if node_type == "folder":
            self._clear_dummy(item_id)
            self.populate_folder(item_id, payload)
        elif node_type == "file":
            self._clear_dummy(item_id)
            self.populate_file_methods(item_id, payload)

    def _clear_dummy(self, item_id):
        for child in self.tree.get_children(item_id):
            vals = self.tree.item(child, "values")
            if vals and vals[0] == "dummy":
                self.tree.delete(child)

    def populate_folder(self, folder_item_id, folder_path):
        children = self.tree.get_children(folder_item_id)
        has_real = any(self.tree.item(c, "values")[0] != "dummy" for c in children)
        if has_real:
            return

        for fname in sorted(os.listdir(folder_path)):
            if not fname.endswith(".py") or fname.startswith("__init__"):
                continue

            fpath = os.path.join(folder_path, fname)

            # 🔍 Parse to see if it contains any valid test steps
            entries = self.parse_python_file(os.path.basename(folder_path), fname, fpath)
            if not entries:
                # ⚠️ Skip this file because it has no methods to show
                continue

            # ✅ Only display files that contain at least one method
            file_id = self.tree.insert(
                folder_item_id,
                "end",
                text=self._unchecked("📄 " + fname),
                values=("file", fpath),
                tags=("file_tag",),
            )
            self.tree.insert(file_id, "end", text="...", values=("dummy", ""))


    def populate_file_methods(self, file_item_id, file_path):
        for child in self.tree.get_children(file_item_id):
            self.tree.delete(child)

        folder_item_id = self.tree.parent(file_item_id)
        folder_name = self._strip_all(self.tree.item(folder_item_id, "text"))
        file_name = self._strip_all(self.tree.item(file_item_id, "text"))

        entries = self.parse_python_file(folder_name, file_name, file_path)
        for e in entries:
            method_name = e["test_step_definition"].split(".")[-1]
            self.tree.insert(
                file_item_id,
                "end",
                text=self._unchecked("🛠️" + method_name),
                values=("method", json.dumps(e)),
                tags=("method_tag",),
            )

    # clicks ----------------------------------------------------
    def on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)

        if region == "tree":
            elem = self.tree.identify("element", event.x, event.y)
            if elem == "Treeitem.indicator":
                return

        if region not in ("tree", "cell"):
            return

        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return

        text = self.tree.item(item_id, "text")
        node_type, payload = self.get_node_info(item_id)
        if node_type == "info":
            return

        is_checked = text.startswith("☑")

        if is_checked:
            clean = self._strip_checkbox(text)
            self.tree.item(item_id, text=self._unchecked(clean))
            tags = list(self.tree.item(item_id, "tags"))
            if "checked_tag" in tags:
                tags.remove("checked_tag")
            self.tree.item(item_id, tags=tuple(tags))
            self.uncheck_node(item_id, node_type, payload)
        else:
            clean = self._strip_checkbox(text)
            self.tree.item(item_id, text=self._checked(clean))
            tags = list(self.tree.item(item_id, "tags"))
            if "checked_tag" not in tags:
                tags.append("checked_tag")
            self.tree.item(item_id, tags=tuple(tags))
            self.check_node(item_id, node_type, payload)

        self.refresh_preview()
        return "break"

    # right-click -----------------------------------------------
    def on_tree_right_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        self.tree.selection_set(item_id)
        self.tree.focus(item_id)
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def choose_editor(self):
        new_editor = filedialog.askopenfilename(
            title="Select Text Editor Executable",
            filetypes=[("Executables", "*.exe"), ("All files", "*.*")]
        )
        if new_editor:
            self.editor_path = new_editor
            messagebox.showinfo("Editor Selected", f"Editor set to:\n{self.editor_path}")

    def _open_selected_in_editor(self):
        item_id = self.tree.focus()
        if not item_id:
            return

        node_type, payload = self.get_node_info(item_id)
        file_path = None

        if node_type == "file":
            file_path = payload

        elif node_type == "method":
            entry = json.loads(payload)
            src = entry.get("source_path")
            if src:
                file_path = src
            else:
                parent_id = self.tree.parent(item_id)
                _, file_path = self.get_node_info(parent_id)

        elif node_type in ("folder", "root"):
            folder_path = payload
            if folder_path and os.path.isdir(folder_path):
                try:
                    subprocess.Popen(["explorer", folder_path])
                except Exception as e:
                    messagebox.showerror("Open folder", f"Could not open folder:\n{e}")
            return

        else:
            return

        if not file_path or not os.path.isfile(file_path):
            messagebox.showerror("Open", f"File not found:\n{file_path}")
            return

        try:
            subprocess.Popen([self.editor_path, file_path], shell=False)
        except Exception as e:
            messagebox.showerror("Open", f"Could not open file in editor:\n{e}")

    # check / uncheck -------------------------------------------
    def check_node(self, item_id, node_type, payload):
        if node_type == "method":
            entry = json.loads(payload)
            self._add_entry(entry)
        elif node_type == "file":
            folder_item_id = self.tree.parent(item_id)
            folder_name = self._strip_all(self.tree.item(folder_item_id, "text"))
            file_name = self._strip_all(self.tree.item(item_id, "text"))
            entries = self.parse_python_file(folder_name, file_name, payload)
            for e in entries:
                self._add_entry(e)
            for child in self.tree.get_children(item_id):
                txt = self.tree.item(child, "text")
                if txt.startswith("☐"):
                    clean = self._strip_checkbox(txt)
                    tags = list(self.tree.item(child, "tags"))
                    if "checked_tag" not in tags:
                        tags.append("checked_tag")
                    self.tree.item(child, text=self._checked(clean), tags=tuple(tags))
        elif node_type == "folder":
            folder_name = self._strip_all(self.tree.item(item_id, "text"))
            folder_path = payload

            entries = self.collect_folder_entries(folder_name, folder_path)
            for e in entries:
                self._add_entry(e)

            def mark_children(parent_id):
                for child in self.tree.get_children(parent_id):
                    text = self.tree.item(child, "text")
                    node_type, payload = self.get_node_info(child)

                    if text.startswith("☐"):
                        clean = self._strip_checkbox(text)
                        tags = list(self.tree.item(child, "tags"))
                        if "checked_tag" not in tags:
                            tags.append("checked_tag")
                        self.tree.item(child, text=self._checked(clean), tags=tuple(tags))

                    if node_type == "file":
                        self._clear_dummy(child)
                        self.populate_file_methods(child, payload)
                        mark_children(child)
                    elif node_type == "folder":
                        self._clear_dummy(child)
                        self.populate_folder(child, payload)
                        mark_children(child)

            mark_children(item_id)

    def uncheck_node(self, item_id, node_type, payload):
        if node_type == "method":
            entry = json.loads(payload)
            key = entry["test_step_definition"]
            self.checked_steps.pop(key, None)
            self.step_sources.pop(key, None)   # <— ADD
            return


        def unmark_children(parent_id):
            for child in self.tree.get_children(parent_id):
                text = self.tree.item(child, "text")
                ctype, cpayload = self.get_node_info(child)

                if ctype == "method":
                    entry = json.loads(cpayload)
                    key = entry["test_step_definition"]
                    self.checked_steps.pop(key, None)
                    self.step_sources.pop(key, None)   # <— ADD


                if text.startswith("☑"):
                    clean = self._strip_checkbox(text)
                    tags = list(self.tree.item(child, "tags"))
                    if "checked_tag" in tags:
                        tags.remove("checked_tag")
                    self.tree.item(child, text=self._unchecked(clean), tags=tuple(tags))

                unmark_children(child)

        if node_type == "file":
            folder_item_id = self.tree.parent(item_id)
            folder_name = self._strip_all(self.tree.item(folder_item_id, "text"))
            file_name = self._strip_all(self.tree.item(item_id, "text"))
            entries = self.parse_python_file(folder_name, file_name, payload)
            for e in entries:
                self.checked_steps.pop(e["test_step_definition"], None)
                self.step_sources.pop(e["test_step_definition"], None)   # <— ADD

            unmark_children(item_id)

            text = self.tree.item(item_id, "text")
            if text.startswith("☑"):
                clean = self._strip_checkbox(text)
                tags = list(self.tree.item(item_id, "tags"))
                if "checked_tag" in tags:
                    tags.remove("checked_tag")
                self.tree.item(item_id, text=self._unchecked(clean), tags=tuple(tags))

            return

        if node_type == "folder":
            folder_name = self._strip_all(self.tree.item(item_id, "text"))
            folder_path = payload

            entries = self.collect_folder_entries(folder_name, folder_path)
            for e in entries:
                self.checked_steps.pop(e["test_step_definition"], None)
                self.step_sources.pop(e["test_step_definition"], None)   # <— ADD


            unmark_children(item_id)

            text = self.tree.item(item_id, "text")
            if text.startswith("☑"):
                clean = self._strip_checkbox(text)
                tags = list(self.tree.item(item_id, "tags"))
                if "checked_tag" in tags:
                    tags.remove("checked_tag")
                self.tree.item(item_id, text=self._unchecked(clean), tags=tuple(tags))

    def _has_diagnosis_selection(self) -> bool:
        """
        Return True if any selected step comes from a file
        inside a 'Diagnosis' folder.
        """
        for step, src in self.step_sources.items():
            if not src:
                continue
            parts = [p.lower() for p in src.split(os.sep)]
            if "diagnosis" in parts:
                return True
        return False


    # preview / export ------------------------------------------

    def _is_in_diagnosis_folder(self) -> bool:
        """
        Return True if the currently focused tree item is under the 'Diagnosis' folder.
        """
        item_id = self.tree.focus()
        if not item_id:
            return False

        # Walk up the tree to see if any parent is the 'Diagnosis' folder
        while item_id:
            text = self._strip_all(self.tree.item(item_id, "text"))
            if text == "Diagnosis":
                return True
            item_id = self.tree.parent(item_id)

        return False

    def refresh_preview(self):
        self.preview.delete("1.0", "end")

        steps = sorted(self.checked_steps.values(), key=lambda x: x["Test Step"])

        # ✅ Show diagnosis info ONLY if at least one selected step is from Diagnosis
        if self._has_diagnosis_selection():
            diag_info = self._get_diag_description()
            self.preview.insert("end", diag_info + "\n\n")

        for e in steps:
            self.preview.insert("end", f"{e['Test Step']}\n")
            desc = e["Description"] or "-"

            pretty = desc
            pretty = pretty.replace(" @param", "\n        @param")
            pretty = pretty.replace(" @return", "\n        @return")
            pretty = pretty.replace(" Example:", "\n        Example:")

            self.preview.insert("end", "    Description:\n")
            self.preview.insert("end", f"        {pretty.strip()}\n\n")

        self.status_label.configure(text=f"{len(steps)} steps selected")

    def export_json(self):
        steps = sorted(self.checked_steps.values(), key=lambda x: x["Test Step"])
        if not steps:
            messagebox.showwarning("No data", "No test steps selected.")
            return
        out = filedialog.asksaveasfilename(
            title="Save JSON",
            defaultextension=".json",
            initialfile="test_steps.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not out:
            return
        try:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(steps, f, indent=4, ensure_ascii=False)
            self.status_label.configure(text=f"✅ Exported {len(steps)} steps")
            messagebox.showinfo("Export Complete", f"JSON file successfully saved to:\n\n{out}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # small helpers ---------------------------------------------
    def _checked(self, text: str) -> str:
        return f"☑ {text}"

    def _unchecked(self, text: str) -> str:
        return f"☐ {text}"

    def _strip_checkbox(self, text: str) -> str:
        if text.startswith("☑ "):
            return text[2:].strip()
        if text.startswith("☐ "):
            return text[2:].strip()
        return text

    def _strip_emoji(self, text: str) -> str:
        for emoji in ("🧱", "📁", "📄", "⚙️", "❗", "🛠️"):
            if text.startswith(emoji + " "):
                return text[len(emoji) + 1:].strip()
        return text

    def _strip_all(self, text: str) -> str:
        return self._strip_emoji(self._strip_checkbox(text))

    def get_node_info(self, item_id):
        vals = self.tree.item(item_id, "values")
        if not vals:
            return None, None
        return vals[0], vals[1]

    # add entry ----------------------------------------------
    def _add_entry(self, entry_dict):
        step = entry_dict.get("test_step_definition", "")
        raw_doc = entry_dict.get("test_step_description", "") or ""
        raw_doc = raw_doc.strip()

        # remove leading "!" if present
        if raw_doc.startswith("!"):
            raw_doc = raw_doc[1:].strip()

        if raw_doc:
            parts = [line.strip() for line in raw_doc.splitlines() if line.strip()]
            desc_val = " ".join(parts)

            lower = desc_val.lower()
            if lower.startswith("description:"):
                desc_val = desc_val[len("description:"):].strip()
            elif lower.startswith("description"):
                after = desc_val[len("Description"):].lstrip(" :-–").strip()
                desc_val = after
        else:
            desc_val = "-"

        # ✅ keep description as before
        self.checked_steps[step] = {"Test Step": step, "Description": desc_val}
        # ✅ NEW: remember where it came from
        self.step_sources[step] = entry_dict.get("source_path", "")

    # parsing -------------------------------------------------
    def collect_folder_entries(self, folder_name, folder_path):
        all_entries = []
        for fname in sorted(os.listdir(folder_path)):
            if not fname.endswith(".py") or fname.startswith("__init__"):
                continue
            fpath = os.path.join(folder_path, fname)
            entries = self.parse_python_file(folder_name, fname, fpath)
            all_entries.extend(entries)
        return all_entries

    def parse_python_file(self, folder, file_name, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
        except Exception:
            return []

        try:
            tree = ast.parse(src)
        except SyntaxError:
            return []

        tal_imports = {}
        proj_imports = {}
        util_imports = {}  # <— add

        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("tal"):
                    for alias in node.names:
                        tal_imports[alias.asname or alias.name] = (node.module, alias.name)
                elif node.module.startswith("ProjectComponents."):
                    for alias in node.names:
                        proj_imports[alias.asname or alias.name] = (node.module, alias.name)
                elif node.module.startswith("Utility."):  # <— NEW
                    for alias in node.names:
                        util_imports[alias.asname or alias.name] = (node.module, alias.name)


        results = []
        module = os.path.splitext(file_name)[0]

        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                # keep only CamelCase / PascalCase style
                if self._is_dunder(node.name):
                    continue
                if not self._is_camel_step(node.name):
                    continue
                results.append(self._entry(folder, module, node, path))
            elif isinstance(node, ast.ClassDef):
                for func in node.body:
                    if isinstance(func, ast.FunctionDef) and not self._is_dunder(func.name):
                        if not self._is_camel_step(func.name):
                            continue
                        results.append(self._entry(folder, module, func, path))

                # inside: for node in tree.body: if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bname = base.id
                        if bname in tal_imports:
                            mod, cls = tal_imports[bname]
                            results.extend(self._load_tal_class_methods_recursive(mod, cls, folder, module, visited=set()))
                        elif bname in proj_imports:
                            mod, cls = proj_imports[bname]
                            results.extend(self._load_project_class_methods_recursive(mod, cls, folder, module, visited=set()))
                        elif bname in util_imports:
                            mod, cls = util_imports[bname]
                            results.extend(self._load_utility_class_methods_recursive(mod, cls, folder, module, visited=set()))
                        elif bname == "DiagnosisInterface":  # <<< special-case
                            resolved = self._resolve_diag_impl_from_cfg()
                            if resolved:
                                mod, cls = resolved  # ('tal.FunctionalComponents.Diagnosis.DiagnosisInterface', 'UdsSymbolic', ...)
                                results.extend(
                                    self._load_tal_class_methods_recursive(
                                        mod, cls, folder, module, visited=set()
                                    )
                                )



        return results

    def _load_utility_class_methods_recursive(self, module_name, class_name, folder, module, visited):
        """
        Resolve Utility.* modules to file paths under the workspace root and load methods recursively.
        Example module_name: 'Utility.SupportingScripts.ParallelTestSteps.ParallelExecution'
        """
        if not self.workspace_root:
            return []

        # Map module path to file path under the workspace root
        rel = module_name.replace(".", os.sep) + ".py"  # Utility/SupportingScripts/.../ParallelExecution.py
        file_path = os.path.join(self.workspace_root, rel)
        return self._load_class_methods_recursive(file_path, class_name, folder, module, visited)


    def _load_tal_class_methods_recursive(self, module_name, class_name, folder, module, visited):
        if module_name.startswith("tal."):
            rel = module_name[len("tal."):].replace(".", os.sep) + ".py"
        elif module_name == "tal":
            rel = class_name + ".py"
        else:
            rel = module_name.replace(".", os.sep) + ".py"
        file_path = os.path.join(EXTRA_LIB_ROOT, rel)
        return self._load_class_methods_recursive(file_path, class_name, folder, module, visited)

    def _load_project_class_methods_recursive(self, module_name, class_name, folder, module, visited):
        if not self.project_root:
            return []
        rel = module_name[len("ProjectComponents.") :].replace(".", os.sep) + ".py"
        file_path = os.path.join(self.project_root, rel)
        return self._load_class_methods_recursive(file_path, class_name, folder, module, visited)

    def _load_class_methods_recursive(self, file_path, class_name, folder, module, visited):
        key = (os.path.abspath(file_path), class_name)
        if key in visited:
            return []
        visited.add(key)

        if not os.path.isfile(file_path):
            return []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                src = f.read()
        except Exception:
            return []

        try:
            tree = ast.parse(src)
        except SyntaxError:
            return []

        tal_imports = {}
        proj_imports = {}
        util_imports = {}   # <<< REQUIRED

        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("tal"):
                    for alias in node.names:
                        tal_imports[alias.asname or alias.name] = (node.module, alias.name)
                elif node.module.startswith("ProjectComponents."):
                    for alias in node.names:
                        proj_imports[alias.asname or alias.name] = (node.module, alias.name)

        results = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for func in node.body:
                    if isinstance(func, ast.FunctionDef) and not self._is_dunder(func.name):
                        if not self._is_camel_step(func.name):
                            continue
                        params = self._param_string(func)
                        # ⬇️ remove folder from here too
                        full = f"{module}.{func.name}{params}"
                        doc = ast.get_docstring(func) or ""
                        results.append(
                            {
                                "test_step_definition": full,
                                "test_step_description": doc,
                                "source_path": file_path,
                            }
                        )
                # after building tal_imports / proj_imports / util_imports
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bname = base.id
                        if bname in tal_imports:
                            mod, cls = tal_imports[bname]
                            results.extend(self._load_tal_class_methods_recursive(mod, cls, folder, module, visited))
                        elif bname in proj_imports:
                            mod, cls = proj_imports[bname]
                            results.extend(self._load_project_class_methods_recursive(mod, cls, folder, module, visited))
                        elif bname in util_imports:
                            mod, cls = util_imports[bname]
                            results.extend(self._load_utility_class_methods_recursive(mod, cls, folder, module, visited))
                        elif bname == "DiagnosisInterface":  # <<< special-case
                            resolved = self._resolve_diag_impl_from_cfg()
                            if resolved:
                                mod, cls = resolved
                                results.extend(
                                    self._load_tal_class_methods_recursive(
                                        mod, cls, folder, module, visited
                                    )
                                )


        return results

    def _entry(self, folder, module, node, source_path):
        doc = ast.get_docstring(node) or ""
        params = self._param_string(node)
        # ⬇️ here we remove the folder from the final name
        full = f"{module}.{node.name}{params}"
        return {
            "test_step_definition": full,
            "test_step_description": doc,
            "source_path": source_path,
        }

    def _is_dunder(self, name):
        return name.startswith("__") and name.endswith("__")

    def _param_string(self, node):
        args = node.args
        parts = []

        pos_args = args.args[:]
        if pos_args and pos_args[0].arg in ("self", "cls"):
            pos_args = pos_args[1:]

        defaults = args.defaults or []
        num_pos = len(pos_args)
        num_def = len(defaults)

        for i, arg in enumerate(pos_args):
            name = arg.arg
            default_str = None
            if i >= num_pos - num_def:
                default_node = defaults[i - (num_pos - num_def)]
                default_str = self._expr_to_str(default_node)
            if default_str:
                parts.append(f"{name}={default_str}")
            else:
                parts.append(name)

        if args.vararg:
            parts.append(f"*{args.vararg.arg}")

        for kwarg, default in zip(args.kwonlyargs, args.kw_defaults):
            name = kwarg.arg
            if default is not None:
                parts.append(f"{name}={self._expr_to_str(default)}")
            else:
                parts.append(name)

        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")

        return "(" + ", ".join(parts) + ")"

    def _expr_to_str(self, node):
        if not node:
            return ""
        try:
            if hasattr(ast, "unparse"):
                return ast.unparse(node)
        except Exception:
            pass
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._expr_to_str(node.value)}.{node.attr}"
        return "<expr>"


if __name__ == "__main__":
    app = TestStepTreeApp()
    app.mainloop()
