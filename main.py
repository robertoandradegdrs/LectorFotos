"""
Interfaz gráfica principal para LectorFotos.

Permite seleccionar una fotografía desde el equipo (o pegar desde el portapapeles),
visualizarla con resaltado opcional de las zonas detectadas y obtener en un segundo
recuadro todo el texto identificado mediante OCR.
"""

from __future__ import annotations

import ctypes
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from PIL import Image, ImageDraw, ImageGrab, ImageTk

from ocr_engine import (
    DetectedLine,
    OcrExtractionResult,
    extract_text_from_image,
    load_oriented_image,
)


def _enable_windows_dpi_awareness() -> None:
    """Activa escalado nítido (High-DPI) en pantallas modernas de Windows."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class LectorFotosApp:
    """Aplicación de escritorio para identificar texto en fotografías."""

    BG_MAIN = "#F3F5F9"
    BG_CARD = "#FFFFFF"
    BG_CANVAS = "#1E2430"
    BORDER_COLOR = "#D8DEE9"
    ACCENT = "#2563EB"
    ACCENT_HOVER = "#1D4ED8"
    TEXT_PRIMARY = "#111827"
    TEXT_MUTED = "#6B7280"
    HIGHLIGHT_FILL = (16, 185, 129, 55)
    HIGHLIGHT_OUTLINE = (16, 185, 129, 235)

    SUPPORTED_FILETYPES = [
        ("Imágenes soportadas", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff *.gif"),
        ("JPEG", "*.jpg *.jpeg"),
        ("PNG", "*.png"),
        ("WebP", "*.webp"),
        ("Mapa de bits / TIFF", "*.bmp *.tif *.tiff"),
        ("Todos los archivos", "*.*"),
    ]

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Lector de Fotos — Identificador de Texto (OCR)")
        self.root.geometry("1120x680")
        self.root.minsize(820, 520)
        self.root.configure(bg=self.BG_MAIN)

        self.current_image_path: Optional[Path] = None
        self.current_image: Optional[Image.Image] = None
        self.detected_lines: List[DetectedLine] = []
        self._tk_preview_ref: Optional[ImageTk.PhotoImage] = None
        self._is_processing = False
        self._resize_job: Optional[str] = None
        self._ocr_request_id = 0

        self.enhance_var = tk.BooleanVar(value=False)
        self.highlight_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Listo — Selecciona una foto para identificar su texto.")
        self.photo_meta_var = tk.StringVar(value="Ninguna foto cargada")
        self.stats_var = tk.StringVar(value="0 palabras  •  0 caracteres")

        self._configure_styles()
        self._build_ui()
        self._bind_shortcuts()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("Main.TFrame", background=self.BG_MAIN)
        style.configure("Card.TFrame", background=self.BG_CARD)
        style.configure(
            "Title.TLabel",
            background=self.BG_CARD,
            foreground=self.TEXT_PRIMARY,
            font=("Segoe UI", 14, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=self.BG_CARD,
            foreground=self.TEXT_MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Section.TLabel",
            background=self.BG_CARD,
            foreground=self.TEXT_PRIMARY,
            font=("Segoe UI", 11, "bold"),
        )
        style.configure(
            "Meta.TLabel",
            background=self.BG_CARD,
            foreground=self.TEXT_MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Status.TLabel",
            background=self.BG_CARD,
            foreground=self.TEXT_PRIMARY,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Primary.TButton",
            background=self.ACCENT,
            foreground="#FFFFFF",
            borderwidth=0,
            focusthickness=0,
            padding=(14, 7),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", self.ACCENT_HOVER), ("disabled", "#93C5FD")],
            foreground=[("disabled", "#F8FAFC")],
        )
        style.configure(
            "Secondary.TButton",
            background="#EEF2F7",
            foreground=self.TEXT_PRIMARY,
            borderwidth=1,
            relief="flat",
            padding=(11, 6),
            font=("Segoe UI", 9),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#E2E8F0"), ("disabled", "#F1F5F9")],
            foreground=[("disabled", "#94A3B8")],
        )
        style.configure(
            "Card.TCheckbutton",
            background=self.BG_CARD,
            foreground=self.TEXT_PRIMARY,
            font=("Segoe UI", 9),
        )
        style.map("Card.TCheckbutton", background=[("active", self.BG_CARD)])
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor="#E5E7EB",
            background=self.ACCENT,
            bordercolor="#E5E7EB",
            lightcolor=self.ACCENT,
            darkcolor=self.ACCENT,
        )

    def _build_ui(self) -> None:
        # Barra superior de herramientas
        header_border = tk.Frame(self.root, bg=self.BORDER_COLOR)
        header_border.pack(fill=tk.X, side=tk.TOP)

        header = ttk.Frame(header_border, style="Card.TFrame", padding=(18, 12))
        header.pack(fill=tk.X, side=tk.TOP, pady=(0, 1))

        title_box = ttk.Frame(header, style="Card.TFrame")
        title_box.pack(side=tk.LEFT)
        ttk.Label(title_box, text="Lector de Fotos", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="Selecciona una imagen para detectar y extraer su texto automáticamente",
            style="Subtitle.TLabel",
        ).pack(anchor="w")

        controls = ttk.Frame(header, style="Card.TFrame")
        controls.pack(side=tk.RIGHT)

        self.btn_select = ttk.Button(
            controls,
            text="📂 Seleccionar foto...",
            style="Primary.TButton",
            command=self.select_photo,
        )
        self.btn_select.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_paste = ttk.Button(
            controls,
            text="📋 Pegar imagen",
            style="Secondary.TButton",
            command=self.paste_from_clipboard,
        )
        self.btn_paste.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_rotate = ttk.Button(
            controls,
            text="↻ Rotar 90°",
            style="Secondary.TButton",
            command=self.rotate_image,
            state=tk.DISABLED,
        )
        self.btn_rotate.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_reanalyze = ttk.Button(
            controls,
            text="🔍 Re-analizar",
            style="Secondary.TButton",
            command=self.run_ocr_on_current,
            state=tk.DISABLED,
        )
        self.btn_reanalyze.pack(side=tk.LEFT, padx=(0, 12))

        opts_box = ttk.Frame(controls, style="Card.TFrame")
        opts_box.pack(side=tk.LEFT)
        ttk.Checkbutton(
            opts_box,
            text="Mejorar contraste",
            variable=self.enhance_var,
            style="Card.TCheckbutton",
            command=self._on_enhance_toggled,
        ).pack(anchor="w")
        ttk.Checkbutton(
            opts_box,
            text="Resaltar zonas de texto",
            variable=self.highlight_var,
            style="Card.TCheckbutton",
            command=self._render_canvas_preview,
        ).pack(anchor="w")

        # Barra de estado inferior
        footer_border = tk.Frame(self.root, bg=self.BORDER_COLOR)
        footer_border.pack(fill=tk.X, side=tk.BOTTOM)

        footer = ttk.Frame(footer_border, style="Card.TFrame", padding=(16, 8))
        footer.pack(fill=tk.X, side=tk.TOP, pady=(1, 0))

        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT)

        self.progress = ttk.Progressbar(
            footer,
            style="Accent.Horizontal.TProgressbar",
            mode="indeterminate",
            length=170,
        )

        # Contenedor central dividido en dos recuadros redimensionables
        body = ttk.Frame(self.root, style="Main.TFrame", padding=(16, 14))
        body.pack(fill=tk.BOTH, expand=True)

        paned = tk.PanedWindow(
            body,
            orient=tk.HORIZONTAL,
            sashwidth=10,
            bg=self.BG_MAIN,
            bd=0,
            opaqueresize=True,
        )
        paned.pack(fill=tk.BOTH, expand=True)

        # --- RECUADRO IZQUIERDO: FOTO SELECCIONADA ---
        left_outer = tk.Frame(paned, bg=self.BORDER_COLOR, padx=1, pady=1)
        left_card = ttk.Frame(left_outer, style="Card.TFrame", padding=14)
        left_card.pack(fill=tk.BOTH, expand=True)

        left_header = ttk.Frame(left_card, style="Card.TFrame")
        left_header.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(left_header, text="1. Fotografía seleccionada", style="Section.TLabel").pack(side=tk.LEFT)
        ttk.Label(left_header, textvariable=self.photo_meta_var, style="Meta.TLabel").pack(side=tk.RIGHT)

        self.canvas = tk.Canvas(
            left_card,
            bg=self.BG_CANVAS,
            highlightthickness=1,
            highlightbackground="#CBD5E1",
            cursor="hand2",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # --- RECUADRO DERECHO: TEXTO IDENTIFICADO ---
        right_outer = tk.Frame(paned, bg=self.BORDER_COLOR, padx=1, pady=1)
        right_card = ttk.Frame(right_outer, style="Card.TFrame", padding=14)
        right_card.pack(fill=tk.BOTH, expand=True)

        right_header = ttk.Frame(right_card, style="Card.TFrame")
        right_header.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(right_header, text="2. Texto identificado en la foto", style="Section.TLabel").pack(side=tk.LEFT)
        ttk.Label(right_header, textvariable=self.stats_var, style="Meta.TLabel").pack(side=tk.RIGHT)

        text_container = tk.Frame(right_card, bg="#CBD5E1", padx=1, pady=1)
        text_container.pack(fill=tk.BOTH, expand=True)

        text_inner = tk.Frame(text_container, bg="#F8FAFC")
        text_inner.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(text_inner, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text_box = tk.Text(
            text_inner,
            wrap=tk.WORD,
            font=("Segoe UI", 11),
            bg="#F8FAFC",
            fg=self.TEXT_PRIMARY,
            insertbackground=self.TEXT_PRIMARY,
            selectbackground="#BFDBFE",
            selectforeground=self.TEXT_PRIMARY,
            relief=tk.FLAT,
            padx=14,
            pady=12,
            spacing1=2,
            spacing3=4,
            undo=True,
            yscrollcommand=scrollbar.set,
        )
        self.text_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.text_box.yview)
        self.text_box.bind("<<Modified>>", self._on_text_modified)

        # Acciones del recuadro de texto
        right_actions = ttk.Frame(right_card, style="Card.TFrame")
        right_actions.pack(fill=tk.X, pady=(10, 0))

        self.btn_copy = ttk.Button(
            right_actions,
            text="📋 Copiar texto",
            style="Secondary.TButton",
            command=self.copy_text,
        )
        self.btn_copy.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_save = ttk.Button(
            right_actions,
            text="💾 Guardar como .txt",
            style="Secondary.TButton",
            command=self.save_text_file,
        )
        self.btn_save.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_clear = ttk.Button(
            right_actions,
            text="🧹 Limpiar",
            style="Secondary.TButton",
            command=self.clear_all,
        )
        self.btn_clear.pack(side=tk.RIGHT)

        paned.add(left_outer, minsize=340, stretch="always")
        paned.add(right_outer, minsize=340, stretch="always")

        self._set_placeholder_text()

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _e: self.select_photo())
        self.root.bind("<Control-O>", lambda _e: self.select_photo())
        self.root.bind("<Control-s>", lambda _e: self.save_text_file())
        self.root.bind("<Control-S>", lambda _e: self.save_text_file())
        # Permitir pegar imagen desde portapapeles con Ctrl+V cuando el foco no está editando texto
        self.root.bind("<Control-v>", self._handle_ctrl_v)
        self.root.bind("<Control-V>", self._handle_ctrl_v)

    def _handle_ctrl_v(self, event: tk.Event) -> Optional[str]:
        if event.widget is self.text_box:
            return None
        self.paste_from_clipboard()
        return "break"

    # ------------------------------------------------------------------
    # Gestión de carga, rotación y vista previa de la foto
    # ------------------------------------------------------------------

    def _on_canvas_click(self, _event: tk.Event) -> None:
        if self.current_image is None and not self._is_processing:
            self.select_photo()

    def _on_canvas_configure(self, _event: tk.Event) -> None:
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(40, self._render_canvas_preview)

    def select_photo(self) -> None:
        if self._is_processing:
            return

        file_path = filedialog.askopenfilename(
            parent=self.root,
            title="Seleccionar fotografía para leer texto",
            filetypes=self.SUPPORTED_FILETYPES,
        )
        if not file_path:
            return

        path_obj = Path(file_path)
        try:
            img = load_oriented_image(path_obj)
        except Exception as exc:
            messagebox.showerror(
                "No se pudo abrir la imagen",
                f"El archivo seleccionado no pudo abrirse como imagen válida:\n\n{exc}",
                parent=self.root,
            )
            return

        self.current_image_path = path_obj
        self._set_loaded_image(img, source_label=path_obj.name)

    def paste_from_clipboard(self) -> None:
        if self._is_processing:
            return

        try:
            clip = ImageGrab.grabclipboard()
        except Exception as exc:
            messagebox.showwarning(
                "Portapapeles no disponible",
                f"No se pudo leer una imagen del portapapeles:\n{exc}",
                parent=self.root,
            )
            return

        if isinstance(clip, Image.Image):
            if clip.mode in ("RGBA", "LA"):
                rgba = clip.convert("RGBA")
                bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                img = Image.alpha_composite(bg, rgba).convert("RGB")
            else:
                img = clip.convert("RGB")
            self.current_image_path = None
            self._set_loaded_image(img, source_label="Portapapeles")
        elif isinstance(clip, list) and clip:
            first_file = Path(clip[0])
            if first_file.is_file():
                try:
                    img = load_oriented_image(first_file)
                    self.current_image_path = first_file
                    self._set_loaded_image(img, source_label=first_file.name)
                    return
                except Exception:
                    pass
            messagebox.showinfo(
                "Sin imagen en el portapapeles",
                "El portapapeles no contiene una imagen compatible en este momento.",
                parent=self.root,
            )
        else:
            messagebox.showinfo(
                "Sin imagen en el portapapeles",
                "Copia primero una foto o captura de pantalla (por ejemplo con Win + Shift + S) y vuelve a pulsar «Pegar imagen».",
                parent=self.root,
            )

    def rotate_image(self) -> None:
        if self.current_image is None or self._is_processing:
            return
        self.current_image = self.current_image.rotate(-90, expand=True)
        self.detected_lines = []
        label = self.current_image_path.name if self.current_image_path else "Imagen"
        w, h = self.current_image.size
        self.photo_meta_var.set(f"{label}  •  {w} × {h} px")
        self._render_canvas_preview()
        self.run_ocr_on_current()

    def _on_enhance_toggled(self) -> None:
        if self.current_image is not None and not self._is_processing:
            self.run_ocr_on_current()

    def _set_loaded_image(self, img: Image.Image, source_label: str) -> None:
        self.current_image = img
        self.detected_lines = []
        w, h = img.size
        self.photo_meta_var.set(f"{source_label}  •  {w} × {h} px")
        self.canvas.configure(cursor="arrow")
        self.btn_rotate.configure(state=tk.NORMAL)
        self.btn_reanalyze.configure(state=tk.NORMAL)
        self._render_canvas_preview()
        self.run_ocr_on_current()

    def _render_canvas_preview(self) -> None:
        self.canvas.delete("all")
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())

        if self.current_image is None:
            cx, cy = cw // 2, ch // 2
            pad_w = min(380, max(220, cw - 60))
            pad_h = 150
            self.canvas.create_rectangle(
                cx - pad_w // 2,
                cy - pad_h // 2,
                cx + pad_w // 2,
                cy + pad_h // 2,
                outline="#475569",
                dash=(6, 4),
                width=2,
            )
            self.canvas.create_text(
                cx,
                cy - 22,
                text="📷  Haz clic aquí para elegir una foto",
                fill="#F8FAFC",
                font=("Segoe UI", 12, "bold"),
                justify=tk.CENTER,
                width=pad_w - 24,
            )
            self.canvas.create_text(
                cx,
                cy + 24,
                text="Formatos compatibles: JPG, PNG, WEBP, BMP, TIFF\nTambién puedes pegar una captura con Ctrl + V",
                fill="#94A3B8",
                font=("Segoe UI", 9),
                justify=tk.CENTER,
                width=pad_w - 24,
            )
            return

        base_img = self.current_image
        if self.highlight_var.get() and self.detected_lines:
            overlay_base = base_img.convert("RGBA")
            overlay = Image.new("RGBA", overlay_base.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            stroke = max(2, int(round(max(overlay_base.size) / 420)))
            for ln in self.detected_lines:
                x1, y1, x2, y2 = ln.bbox
                pad = max(2, stroke)
                box = (
                    max(0, x1 - pad),
                    max(0, y1 - pad),
                    min(overlay_base.width, x2 + pad),
                    min(overlay_base.height, y2 + pad),
                )
                draw.rectangle(box, fill=self.HIGHLIGHT_FILL, outline=self.HIGHLIGHT_OUTLINE, width=stroke)
            display_source = Image.alpha_composite(overlay_base, overlay).convert("RGB")
        else:
            display_source = base_img

        iw, ih = display_source.size
        margin = 18
        avail_w = max(20, cw - margin * 2)
        avail_h = max(20, ch - margin * 2)
        scale = min(avail_w / float(iw), avail_h / float(ih))
        new_w = max(1, int(round(iw * scale)))
        new_h = max(1, int(round(ih * scale)))

        resized = display_source.resize((new_w, new_h), Image.Resampling.LANCZOS)
        self._tk_preview_ref = ImageTk.PhotoImage(resized)
        self.canvas.create_image(cw // 2, ch // 2, image=self._tk_preview_ref, anchor=tk.CENTER)

    # ------------------------------------------------------------------
    # Ejecución asíncrona del OCR y actualización del texto
    # ------------------------------------------------------------------

    def run_ocr_on_current(self) -> None:
        if self.current_image is None or self._is_processing:
            return

        self._ocr_request_id += 1
        req_id = self._ocr_request_id
        img_copy = self.current_image.copy()
        enhance = self.enhance_var.get()

        self._set_processing_state(True, "Identificando texto en la fotografía, espera un momento...")

        worker = threading.Thread(
            target=self._ocr_worker,
            args=(req_id, img_copy, enhance),
            daemon=True,
        )
        worker.start()

    def _ocr_worker(self, req_id: int, img: Image.Image, enhance: bool) -> None:
        try:
            result = extract_text_from_image(img, enhance_contrast=enhance)
            self.root.after(0, self._on_ocr_success, req_id, result)
        except Exception as exc:
            self.root.after(0, self._on_ocr_error, req_id, str(exc))

    def _on_ocr_success(self, req_id: int, result: OcrExtractionResult) -> None:
        if req_id != self._ocr_request_id:
            return

        self._set_processing_state(False)
        self.detected_lines = result.lines
        self._render_canvas_preview()

        if result.text:
            self._set_result_text(result.text)
            self.status_var.set(
                f"Texto identificado con {result.engine_name} ({result.language}) — "
                f"{len(result.lines) or len(result.text.splitlines())} líneas encontradas."
            )
        else:
            self._set_result_text("")
            self.text_box.insert(
                "1.0",
                "(No se identificó texto legible en esta fotografía.\n"
                "Prueba activando «Mejorar contraste» o rotando la imagen si está girada.)",
            )
            self.text_box.tag_add("muted", "1.0", tk.END)
            self.text_box.tag_configure("muted", foreground=self.TEXT_MUTED, font=("Segoe UI", 10, "italic"))
            self.stats_var.set("0 palabras  •  0 caracteres")
            self.status_var.set("Análisis finalizado — No se detectó texto en la imagen.")

    def _on_ocr_error(self, req_id: int, error_msg: str) -> None:
        if req_id != self._ocr_request_id:
            return

        self._set_processing_state(False)
        self.status_var.set("Ocurrió un error al analizar la imagen.")
        messagebox.showerror(
            "Error en el reconocimiento de texto",
            f"No fue posible completar la lectura de la imagen:\n\n{error_msg}",
            parent=self.root,
        )

    def _set_processing_state(self, active: bool, message: Optional[str] = None) -> None:
        self._is_processing = active
        if message:
            self.status_var.set(message)

        if active:
            self.btn_select.configure(state=tk.DISABLED)
            self.btn_paste.configure(state=tk.DISABLED)
            self.btn_rotate.configure(state=tk.DISABLED)
            self.btn_reanalyze.configure(state=tk.DISABLED)
            self.progress.pack(side=tk.RIGHT, padx=(10, 0))
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()
            self.btn_select.configure(state=tk.NORMAL)
            self.btn_paste.configure(state=tk.NORMAL)
            has_img = self.current_image is not None
            self.btn_rotate.configure(state=tk.NORMAL if has_img else tk.DISABLED)
            self.btn_reanalyze.configure(state=tk.NORMAL if has_img else tk.DISABLED)

    # ------------------------------------------------------------------
    # Utilidades del recuadro de texto (copiar, guardar, limpiar)
    # ------------------------------------------------------------------

    def _set_placeholder_text(self) -> None:
        self.text_box.delete("1.0", tk.END)
        self.text_box.insert(
            "1.0",
            "Aquí aparecerá todo el texto identificado cuando selecciones una foto...",
        )
        self.text_box.tag_add("placeholder", "1.0", tk.END)
        self.text_box.tag_configure("placeholder", foreground=self.TEXT_MUTED, font=("Segoe UI", 10, "italic"))
        self.text_box.edit_modified(False)
        self.stats_var.set("0 palabras  •  0 caracteres")

    def _set_result_text(self, content: str) -> None:
        self.text_box.delete("1.0", tk.END)
        for tag in ("placeholder", "muted"):
            self.text_box.tag_delete(tag)
        if content:
            self.text_box.insert("1.0", content)
        self.text_box.edit_modified(False)
        self._update_text_stats()

    def _get_clean_text(self) -> str:
        if self.text_box.tag_ranges("placeholder") or self.text_box.tag_ranges("muted"):
            return ""
        return self.text_box.get("1.0", "end-1c").strip()

    def _on_text_modified(self, _event: tk.Event) -> None:
        if self.text_box.edit_modified():
            self._update_text_stats()
            self.text_box.edit_modified(False)

    def _update_text_stats(self) -> None:
        content = self._get_clean_text()
        words = len(content.split()) if content else 0
        chars = len(content)
        self.stats_var.set(f"{words} palabras  •  {chars} caracteres")

    def copy_text(self) -> None:
        content = self._get_clean_text()
        if not content:
            self.status_var.set("No hay texto para copiar todavía.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.root.update_idletasks()
        self.status_var.set("✔ Texto copiado al portapapeles.")

    def save_text_file(self) -> None:
        content = self._get_clean_text()
        if not content:
            messagebox.showinfo(
                "Sin texto para guardar",
                "Primero selecciona una fotografía que contenga texto.",
                parent=self.root,
            )
            return

        default_name = (
            f"{self.current_image_path.stem}_texto.txt"
            if self.current_image_path
            else "texto_extraido.txt"
        )
        out_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Guardar texto extraído",
            initialfile=default_name,
            defaultextension=".txt",
            filetypes=[("Archivo de texto UTF-8", "*.txt"), ("Todos los archivos", "*.*")],
        )
        if not out_path:
            return

        try:
            Path(out_path).write_text(content, encoding="utf-8")
            self.status_var.set(f"✔ Texto guardado en: {Path(out_path).name}")
        except Exception as exc:
            messagebox.showerror(
                "Error al guardar",
                f"No se pudo guardar el archivo:\n{exc}",
                parent=self.root,
            )

    def clear_all(self) -> None:
        if self._is_processing:
            return
        self._ocr_request_id += 1
        self.current_image_path = None
        self.current_image = None
        self.detected_lines = []
        self._tk_preview_ref = None
        self.canvas.configure(cursor="hand2")
        self.btn_rotate.configure(state=tk.DISABLED)
        self.btn_reanalyze.configure(state=tk.DISABLED)
        self.photo_meta_var.set("Ninguna foto cargada")
        self._render_canvas_preview()
        self._set_placeholder_text()
        self.status_var.set("Listo — Selecciona una foto para identificar su texto.")


def main() -> None:
    _enable_windows_dpi_awareness()
    root = tk.Tk()
    LectorFotosApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
