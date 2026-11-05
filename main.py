"""
Interfaz gráfica corporativa DRS para LectorFotos.

Permite seleccionar una fotografía desde el equipo (o pegar desde el portapapeles),
visualizarla con resaltado corporativo de las zonas detectadas y obtener en un
segundo recuadro todo el texto identificado mediante OCR.
"""

from __future__ import annotations

import ctypes
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageGrab, ImageTk

from brand_assets import (
    BRAND_DEEP_ACCENT,
    BRAND_NAVY,
    BRAND_PRIMARY,
    BRAND_SLATE,
    get_drs_ico_path,
    load_drs_app_icon,
    load_drs_logo,
)
from ocr_engine import (
    DetectedLine,
    OcrExtractionResult,
    extract_text_from_image,
    load_oriented_image,
)


def _configure_windows_shell_identity() -> None:
    """Activa High-DPI y registra AppUserModelID propio para mostrar el ícono DRS en la barra de tareas."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("drs.lectorfotos.ocr.1")
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def _composite_logo_on_bg(
    logo_rgba: Image.Image,
    target_height: int,
    bg_hex: str,
    opacity: float = 1.0,
) -> Image.Image:
    """Redimensiona el logo DRS con antialiasing LANCZOS y lo compone sobre el color de fondo exacto."""
    scale = target_height / float(max(1, logo_rgba.height))
    target_width = max(1, int(round(logo_rgba.width * scale)))
    resized = logo_rgba.resize((target_width, target_height), Image.Resampling.LANCZOS)

    if opacity < 1.0:
        r, g, b, a = resized.split()
        a = a.point(lambda px: int(round(px * opacity)))
        resized = Image.merge("RGBA", (r, g, b, a))

    bg = Image.new("RGBA", (target_width, target_height), _hex_to_rgba(bg_hex, 255))
    return Image.alpha_composite(bg, resized).convert("RGB")


class LectorFotosApp:
    """Aplicación de escritorio con identidad corporativa DRS para identificar texto en fotografías."""

    # Paleta Corporativa DRS
    COLOR_HEADER_BG = BRAND_NAVY          # #0B192C
    COLOR_CANVAS_BG = BRAND_SLATE         # #10233B
    COLOR_BRAND = BRAND_PRIMARY           # #2FCEE6
    COLOR_BRAND_HOVER = "#5CE0F2"
    COLOR_BRAND_DEEP = BRAND_DEEP_ACCENT  # #0B8499
    COLOR_WORKSPACE_BG = "#EDF3F8"
    COLOR_CARD_BG = "#FFFFFF"
    COLOR_CARD_BORDER = "#D4E1EC"
    COLOR_TEXT_MAIN = "#0F172A"
    COLOR_TEXT_MUTED = "#64748B"

    # Resaltado OCR sobre la foto en Cyan DRS
    HIGHLIGHT_FILL = (47, 206, 230, 52)
    HIGHLIGHT_OUTLINE = (47, 206, 230, 240)

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
        self.root.title("DRS  |  Lector de Fotos — Identificador de Texto (OCR)")
        self.root.geometry("1180x720")
        self.root.minsize(880, 560)
        self.root.configure(bg=self.COLOR_WORKSPACE_BG)

        # Cargar recursos gráficos corporativos DRS
        self._raw_logo = load_drs_logo()
        self._apply_window_icon()

        # Referencias persistentes para imágenes Tkinter
        self._header_logo_tk: Optional[ImageTk.PhotoImage] = None
        self._footer_logo_tk: Optional[ImageTk.PhotoImage] = None
        self._canvas_watermark_tk: Optional[ImageTk.PhotoImage] = None
        self._tk_preview_ref: Optional[ImageTk.PhotoImage] = None

        # Estado de negocio
        self.current_image_path: Optional[Path] = None
        self.current_image: Optional[Image.Image] = None
        self.detected_lines: List[DetectedLine] = []
        self._is_processing = False
        self._resize_job: Optional[str] = None
        self._ocr_request_id = 0

        # Variables reactivas UI
        self.enhance_var = tk.BooleanVar(value=False)
        self.highlight_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Sistema listo — Selecciona una fotografía para identificar su texto.")
        self.photo_meta_var = tk.StringVar(value="Sin imagen seleccionada")
        self.stats_var = tk.StringVar(value="0 palabras  •  0 caracteres")

        self._configure_styles()
        self._build_ui()
        self._bind_shortcuts()

    def _apply_window_icon(self) -> None:
        ico_path = get_drs_ico_path()
        if ico_path is not None:
            try:
                self.root.iconbitmap(default=str(ico_path))
            except Exception:
                pass
        try:
            icon_img = load_drs_app_icon()
            self._app_icon_tk = ImageTk.PhotoImage(icon_img)
            self.root.iconphoto(True, self._app_icon_tk)
        except Exception:
            pass

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("Workspace.TFrame", background=self.COLOR_WORKSPACE_BG)
        style.configure("Card.TFrame", background=self.COLOR_CARD_BG)
        style.configure("Header.TFrame", background=self.COLOR_HEADER_BG)

        # Botón Principal Corporativo DRS (Cyan #2FCEE6 sobre Navy)
        style.configure(
            "BrandPrimary.TButton",
            background=self.COLOR_BRAND,
            foreground="#051926",
            borderwidth=0,
            focusthickness=0,
            padding=(16, 8),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "BrandPrimary.TButton",
            background=[("active", self.COLOR_BRAND_HOVER), ("disabled", "#1E4E5F")],
            foreground=[("disabled", "#7FA6B5")],
        )

        # Botones Secundarios en el Header Oscuro
        style.configure(
            "HeaderGhost.TButton",
            background="#162B46",
            foreground="#E2E8F0",
            bordercolor="#264366",
            lightcolor="#162B46",
            darkcolor="#162B46",
            borderwidth=1,
            focusthickness=0,
            padding=(12, 7),
            font=("Segoe UI", 9),
        )
        style.map(
            "HeaderGhost.TButton",
            background=[("active", "#213E63"), ("disabled", "#102036")],
            foreground=[("disabled", "#526985")],
        )

        # Botón de Acción Acento en Tarjeta Clara (Copiar texto)
        style.configure(
            "CardAccent.TButton",
            background="#E6FAFD",
            foreground="#075E6E",
            bordercolor="#8BE4F2",
            lightcolor="#E6FAFD",
            darkcolor="#E6FAFD",
            borderwidth=1,
            focusthickness=0,
            padding=(13, 6),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "CardAccent.TButton",
            background=[("active", "#CCF4FA"), ("disabled", "#F1F5F9")],
            foreground=[("disabled", "#94A3B8")],
        )

        # Botones Secundarios en Tarjeta Clara
        style.configure(
            "CardSecondary.TButton",
            background="#F1F5F9",
            foreground=self.COLOR_TEXT_MAIN,
            bordercolor="#CBD5E1",
            lightcolor="#F1F5F9",
            darkcolor="#F1F5F9",
            borderwidth=1,
            focusthickness=0,
            padding=(12, 6),
            font=("Segoe UI", 9),
        )
        style.map(
            "CardSecondary.TButton",
            background=[("active", "#E2E8F0"), ("disabled", "#F8FAFC")],
            foreground=[("disabled", "#94A3B8")],
        )

        # Checkbuttons en la barra de opciones
        style.configure(
            "Toolbar.TCheckbutton",
            background="#FFFFFF",
            foreground=self.COLOR_TEXT_MAIN,
            focusthickness=0,
            font=("Segoe UI", 9),
        )
        style.map("Toolbar.TCheckbutton", background=[("active", "#FFFFFF")])

        # Barra de progreso Cyan DRS
        style.configure(
            "DRS.Horizontal.TProgressbar",
            troughcolor="#E2E8F0",
            background=self.COLOR_BRAND,
            bordercolor="#E2E8F0",
            lightcolor=self.COLOR_BRAND,
            darkcolor=self.COLOR_BRAND,
        )

    def _build_ui(self) -> None:
        # ==================================================================
        # 1. HEADER CORPORATIVO DRS (#0B192C + línea inferior #2FCEE6)
        # ==================================================================
        header_wrap = tk.Frame(self.root, bg=self.COLOR_HEADER_BG)
        header_wrap.pack(fill=tk.X, side=tk.TOP)

        header_inner = tk.Frame(header_wrap, bg=self.COLOR_HEADER_BG, padx=22, pady=13)
        header_inner.pack(fill=tk.X, side=tk.TOP)

        # Franja luminosa corporativa DRS de 3 px
        tk.Frame(header_wrap, bg=self.COLOR_BRAND, height=3).pack(fill=tk.X, side=tk.BOTTOM)

        # Bloque Izquierdo: Logo DRS + Separador + Título
        brand_left = tk.Frame(header_inner, bg=self.COLOR_HEADER_BG)
        brand_left.pack(side=tk.LEFT)

        header_logo_img = _composite_logo_on_bg(self._raw_logo, target_height=42, bg_hex=self.COLOR_HEADER_BG)
        self._header_logo_tk = ImageTk.PhotoImage(header_logo_img)
        lbl_logo = tk.Label(brand_left, image=self._header_logo_tk, bg=self.COLOR_HEADER_BG, bd=0)
        lbl_logo.pack(side=tk.LEFT, padx=(0, 16))

        # Línea divisoria vertical cyan/navy
        tk.Frame(brand_left, bg="#234369", width=1, height=38).pack(side=tk.LEFT, padx=(0, 16))

        title_stack = tk.Frame(brand_left, bg=self.COLOR_HEADER_BG)
        title_stack.pack(side=tk.LEFT)

        title_row = tk.Frame(title_stack, bg=self.COLOR_HEADER_BG)
        title_row.pack(anchor="w")
        tk.Label(
            title_row,
            text="Lector de Fotos",
            bg=self.COLOR_HEADER_BG,
            fg="#FFFFFF",
            font=("Segoe UI", 15, "bold"),
        ).pack(side=tk.LEFT)

        badge = tk.Label(
            title_row,
            text=" OCR ",
            bg="#123854",
            fg=self.COLOR_BRAND,
            font=("Segoe UI", 8, "bold"),
            padx=5,
            pady=1,
        )
        badge.pack(side=tk.LEFT, padx=(9, 0), pady=(2, 0))

        tk.Label(
            title_stack,
            text="Sistema inteligente de identificación y extracción de texto en imágenes",
            bg=self.COLOR_HEADER_BG,
            fg="#94A3B8",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(1, 0))

        # Bloque Derecho: Botones principales de captura/imagen
        header_actions = tk.Frame(header_inner, bg=self.COLOR_HEADER_BG)
        header_actions.pack(side=tk.RIGHT)

        self.btn_select = ttk.Button(
            header_actions,
            text="📂  Seleccionar foto...",
            style="BrandPrimary.TButton",
            command=self.select_photo,
        )
        self.btn_select.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_paste = ttk.Button(
            header_actions,
            text="📋 Pegar captura",
            style="HeaderGhost.TButton",
            command=self.paste_from_clipboard,
        )
        self.btn_paste.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_rotate = ttk.Button(
            header_actions,
            text="↻ Rotar 90°",
            style="HeaderGhost.TButton",
            command=self.rotate_image,
            state=tk.DISABLED,
        )
        self.btn_rotate.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_reanalyze = ttk.Button(
            header_actions,
            text="🔍 Re-analizar",
            style="HeaderGhost.TButton",
            command=self.run_ocr_on_current,
            state=tk.DISABLED,
        )
        self.btn_reanalyze.pack(side=tk.LEFT)

        # ==================================================================
        # 2. SUB-BARRA DE AJUSTES VISUALES Y PREPROCESAMIENTO
        # ==================================================================
        subbar_border = tk.Frame(self.root, bg=self.COLOR_CARD_BORDER)
        subbar_border.pack(fill=tk.X, side=tk.TOP)

        subbar = tk.Frame(subbar_border, bg="#FFFFFF", padx=22, pady=7)
        subbar.pack(fill=tk.X, side=tk.TOP, pady=(0, 1))

        tk.Label(
            subbar,
            text="OPCIONES DE LECTURA:",
            bg="#FFFFFF",
            fg=self.COLOR_BRAND_DEEP,
            font=("Segoe UI", 8, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Checkbutton(
            subbar,
            text="Mejorar contraste (ideal para documentos oscuros o con sombras)",
            variable=self.enhance_var,
            style="Toolbar.TCheckbutton",
            command=self._on_enhance_toggled,
        ).pack(side=tk.LEFT, padx=(0, 20))

        ttk.Checkbutton(
            subbar,
            text="Resaltar texto detectado sobre la fotografía",
            variable=self.highlight_var,
            style="Toolbar.TCheckbutton",
            command=self._render_canvas_preview,
        ).pack(side=tk.LEFT)

        tk.Label(
            subbar,
            text="Atajos: Ctrl+O abrir  •  Ctrl+V pegar captura  •  Ctrl+S guardar",
            bg="#FFFFFF",
            fg=self.COLOR_TEXT_MUTED,
            font=("Segoe UI", 8),
        ).pack(side=tk.RIGHT)

        # ==================================================================
        # 3. FOOTER CORPORATIVO DRS
        # ==================================================================
        footer_border = tk.Frame(self.root, bg=self.COLOR_CARD_BORDER)
        footer_border.pack(fill=tk.X, side=tk.BOTTOM)

        footer = tk.Frame(footer_border, bg="#FFFFFF", padx=20, pady=8)
        footer.pack(fill=tk.X, side=tk.TOP, pady=(1, 0))

        self.status_dot = tk.Label(
            footer,
            text="●",
            bg="#FFFFFF",
            fg=self.COLOR_BRAND_DEEP,
            font=("Segoe UI", 10),
        )
        self.status_dot.pack(side=tk.LEFT, padx=(0, 6))

        tk.Label(
            footer,
            textvariable=self.status_var,
            bg="#FFFFFF",
            fg=self.COLOR_TEXT_MAIN,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT)

        # Sello DRS a la derecha del footer
        footer_brand = tk.Frame(footer, bg="#FFFFFF")
        footer_brand.pack(side=tk.RIGHT)

        footer_logo_img = _composite_logo_on_bg(self._raw_logo, target_height=18, bg_hex="#FFFFFF")
        self._footer_logo_tk = ImageTk.PhotoImage(footer_logo_img)
        tk.Label(footer_brand, image=self._footer_logo_tk, bg="#FFFFFF", bd=0).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(
            footer_brand,
            text="DRS  •  Extractor OCR",
            bg="#FFFFFF",
            fg=self.COLOR_TEXT_MUTED,
            font=("Segoe UI", 8, "bold"),
        ).pack(side=tk.LEFT)

        self.progress = ttk.Progressbar(
            footer,
            style="DRS.Horizontal.TProgressbar",
            mode="indeterminate",
            length=160,
        )

        # ==================================================================
        # 4. ÁREA PRINCIPAL DIVIDIDA EN DOS RECUADROS
        # ==================================================================
        body = ttk.Frame(self.root, style="Workspace.TFrame", padding=(18, 14))
        body.pack(fill=tk.BOTH, expand=True)

        paned = tk.PanedWindow(
            body,
            orient=tk.HORIZONTAL,
            sashwidth=12,
            bg=self.COLOR_WORKSPACE_BG,
            bd=0,
            opaqueresize=True,
        )
        paned.pack(fill=tk.BOTH, expand=True)

        # --- RECUADRO 1: FOTOGRAFÍA SELECCIONADA ---
        left_outer = tk.Frame(paned, bg=self.COLOR_CARD_BORDER, padx=1, pady=1)
        left_top_accent = tk.Frame(left_outer, bg=self.COLOR_BRAND, height=3)
        left_top_accent.pack(fill=tk.X, side=tk.TOP)

        left_card = ttk.Frame(left_outer, style="Card.TFrame", padding=14)
        left_card.pack(fill=tk.BOTH, expand=True)

        left_header = tk.Frame(left_card, bg=self.COLOR_CARD_BG)
        left_header.pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            left_header,
            text="01",
            bg="#E6FAFD",
            fg=self.COLOR_BRAND_DEEP,
            font=("Segoe UI", 9, "bold"),
            padx=6,
            pady=2,
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Label(
            left_header,
            text="Fotografía seleccionada",
            bg=self.COLOR_CARD_BG,
            fg=self.COLOR_TEXT_MAIN,
            font=("Segoe UI", 11, "bold"),
        ).pack(side=tk.LEFT)

        tk.Label(
            left_header,
            textvariable=self.photo_meta_var,
            bg=self.COLOR_CARD_BG,
            fg=self.COLOR_TEXT_MUTED,
            font=("Segoe UI", 9),
        ).pack(side=tk.RIGHT)

        self.canvas = tk.Canvas(
            left_card,
            bg=self.COLOR_CANVAS_BG,
            highlightthickness=1,
            highlightbackground="#CBD5E1",
            cursor="hand2",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # Preparar emblema DRS para el estado vacío del lienzo
        wm_img = _composite_logo_on_bg(
            self._raw_logo,
            target_height=56,
            bg_hex=self.COLOR_CANVAS_BG,
            opacity=0.92,
        )
        self._canvas_watermark_tk = ImageTk.PhotoImage(wm_img)

        # --- RECUADRO 2: TEXTO IDENTIFICADO EN LA FOTO ---
        right_outer = tk.Frame(paned, bg=self.COLOR_CARD_BORDER, padx=1, pady=1)
        right_top_accent = tk.Frame(right_outer, bg=self.COLOR_BRAND, height=3)
        right_top_accent.pack(fill=tk.X, side=tk.TOP)

        right_card = ttk.Frame(right_outer, style="Card.TFrame", padding=14)
        right_card.pack(fill=tk.BOTH, expand=True)

        right_header = tk.Frame(right_card, bg=self.COLOR_CARD_BG)
        right_header.pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            right_header,
            text="02",
            bg="#E6FAFD",
            fg=self.COLOR_BRAND_DEEP,
            font=("Segoe UI", 9, "bold"),
            padx=6,
            pady=2,
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Label(
            right_header,
            text="Texto identificado en la foto",
            bg=self.COLOR_CARD_BG,
            fg=self.COLOR_TEXT_MAIN,
            font=("Segoe UI", 11, "bold"),
        ).pack(side=tk.LEFT)

        tk.Label(
            right_header,
            textvariable=self.stats_var,
            bg="#F1F5F9",
            fg=self.COLOR_TEXT_MUTED,
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=3,
        ).pack(side=tk.RIGHT)

        text_container = tk.Frame(right_card, bg="#CBD5E1", padx=1, pady=1)
        text_container.pack(fill=tk.BOTH, expand=True)

        text_inner = tk.Frame(text_container, bg="#F8FBFD")
        text_inner.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(text_inner, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text_box = tk.Text(
            text_inner,
            wrap=tk.WORD,
            font=("Segoe UI", 11),
            bg="#F8FBFD",
            fg=self.COLOR_TEXT_MAIN,
            insertbackground=self.COLOR_BRAND_DEEP,
            selectbackground="#A5F0FC",
            selectforeground=self.COLOR_TEXT_MAIN,
            relief=tk.FLAT,
            padx=16,
            pady=14,
            spacing1=2,
            spacing3=4,
            undo=True,
            yscrollcommand=scrollbar.set,
        )
        self.text_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.text_box.yview)
        self.text_box.bind("<<Modified>>", self._on_text_modified)

        # Acciones del recuadro de texto
        right_actions = tk.Frame(right_card, bg=self.COLOR_CARD_BG)
        right_actions.pack(fill=tk.X, pady=(12, 0))

        self.btn_copy = ttk.Button(
            right_actions,
            text="📋 Copiar texto",
            style="CardAccent.TButton",
            command=self.copy_text,
        )
        self.btn_copy.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_save = ttk.Button(
            right_actions,
            text="💾 Guardar .txt",
            style="CardSecondary.TButton",
            command=self.save_text_file,
        )
        self.btn_save.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_clear = ttk.Button(
            right_actions,
            text="🧹 Limpiar vista",
            style="CardSecondary.TButton",
            command=self.clear_all,
        )
        self.btn_clear.pack(side=tk.RIGHT)

        paned.add(left_outer, minsize=380, stretch="always")
        paned.add(right_outer, minsize=380, stretch="always")

        self._set_placeholder_text()

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _e: self.select_photo())
        self.root.bind("<Control-O>", lambda _e: self.select_photo())
        self.root.bind("<Control-s>", lambda _e: self.save_text_file())
        self.root.bind("<Control-S>", lambda _e: self.save_text_file())
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
            title="DRS Lector de Fotos — Seleccionar imagen",
            filetypes=self.SUPPORTED_FILETYPES,
        )
        if not file_path:
            return

        path_obj = Path(file_path)
        try:
            img = load_oriented_image(path_obj)
        except Exception as exc:
            messagebox.showerror(
                "Archivo no válido",
                f"No se pudo abrir la imagen seleccionada:\n\n{exc}",
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
            self._set_loaded_image(img, source_label="Captura pegada")
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
                "El portapapeles no contiene una imagen compatible.",
                parent=self.root,
            )
        else:
            messagebox.showinfo(
                "Sin imagen en el portapapeles",
                "Copia primero una foto o captura de pantalla (por ejemplo con Win + Shift + S) y pulsa «Pegar captura».",
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
            pad_w = min(410, max(240, cw - 64))
            pad_h = 215
            self.canvas.create_rectangle(
                cx - pad_w // 2,
                cy - pad_h // 2,
                cx + pad_w // 2,
                cy + pad_h // 2,
                outline="#23577A",
                dash=(7, 5),
                width=2,
            )
            if self._canvas_watermark_tk is not None:
                self.canvas.create_image(cx, cy - 46, image=self._canvas_watermark_tk, anchor=tk.CENTER)

            self.canvas.create_text(
                cx,
                cy + 14,
                text="Haz clic aquí para seleccionar una fotografía",
                fill="#FFFFFF",
                font=("Segoe UI", 11, "bold"),
                justify=tk.CENTER,
                width=pad_w - 28,
            )
            self.canvas.create_text(
                cx,
                cy + 56,
                text="Compatible con JPG, PNG, WEBP, BMP y TIFF\nTambién puedes pegar una imagen directamente con Ctrl + V",
                fill="#8BA3BE",
                font=("Segoe UI", 9),
                justify=tk.CENTER,
                width=pad_w - 28,
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

        self._set_processing_state(True, "Analizando fotografía e identificando texto...")

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
            self.status_dot.configure(fg="#10B981")
            self.status_var.set(
                f"Lectura completada ({result.engine_name} • {result.language}) — "
                f"{len(result.lines) or len(result.text.splitlines())} líneas identificadas."
            )
        else:
            self._set_result_text("")
            self.text_box.insert(
                "1.0",
                "(No se detectó texto legible en esta fotografía.\n"
                "Sugerencia: activa «Mejorar contraste» en la barra superior o rota la imagen si está orientada de lado.)",
            )
            self.text_box.tag_add("muted", "1.0", tk.END)
            self.text_box.tag_configure("muted", foreground=self.COLOR_TEXT_MUTED, font=("Segoe UI", 10, "italic"))
            self.stats_var.set("0 palabras  •  0 caracteres")
            self.status_dot.configure(fg="#F59E0B")
            self.status_var.set("Análisis finalizado — No se identificó texto en la imagen.")

    def _on_ocr_error(self, req_id: int, error_msg: str) -> None:
        if req_id != self._ocr_request_id:
            return

        self._set_processing_state(False)
        self.status_dot.configure(fg="#EF4444")
        self.status_var.set("Error al procesar la imagen.")
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
            self.status_dot.configure(fg=self.COLOR_BRAND)
            self.btn_select.configure(state=tk.DISABLED)
            self.btn_paste.configure(state=tk.DISABLED)
            self.btn_rotate.configure(state=tk.DISABLED)
            self.btn_reanalyze.configure(state=tk.DISABLED)
            self.progress.pack(side=tk.RIGHT, padx=(12, 16))
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
            "El texto identificado en tu fotografía se mostrará aquí automáticamente...",
        )
        self.text_box.tag_add("placeholder", "1.0", tk.END)
        self.text_box.tag_configure("placeholder", foreground=self.COLOR_TEXT_MUTED, font=("Segoe UI", 10, "italic"))
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
            self.status_var.set("Aún no hay texto identificado para copiar.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.root.update_idletasks()
        self.status_dot.configure(fg="#10B981")
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
            f"{self.current_image_path.stem}_DRS_OCR.txt"
            if self.current_image_path
            else "texto_DRS_OCR.txt"
        )
        out_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="DRS — Guardar texto extraído",
            initialfile=default_name,
            defaultextension=".txt",
            filetypes=[("Archivo de texto UTF-8", "*.txt"), ("Todos los archivos", "*.*")],
        )
        if not out_path:
            return

        try:
            Path(out_path).write_text(content, encoding="utf-8")
            self.status_dot.configure(fg="#10B981")
            self.status_var.set(f"✔ Archivo guardado correctamente: {Path(out_path).name}")
        except Exception as exc:
            messagebox.showerror(
                "Error al guardar",
                f"No se pudo escribir el archivo:\n{exc}",
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
        self.photo_meta_var.set("Sin imagen seleccionada")
        self._render_canvas_preview()
        self._set_placeholder_text()
        self.status_dot.configure(fg=self.COLOR_BRAND_DEEP)
        self.status_var.set("Sistema listo — Selecciona una fotografía para identificar su texto.")


def main() -> None:
    _configure_windows_shell_identity()
    root = tk.Tk()
    LectorFotosApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
