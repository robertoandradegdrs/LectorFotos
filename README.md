# DRS | LectorFotos — Extractor Inteligente de Texto (OCR)

Aplicación de escritorio corporativa **DRS** desarrollada en Python (`tkinter` + `Pillow`) que permite seleccionar fotografías o pegar capturas desde el portapapeles e identificar automáticamente todo el texto contenido en ellas.

## Características

- **Identidad corporativa DRS**: encabezado ejecutivo `#0B192C` con logotipo oficial **DRS** (`#2FCEE6`), ícono personalizado en ventana y barra de tareas de Windows, marca de agua en el visor y resaltado OCR en cyan corporativo.
- **Dos paneles interactivos**: vista previa adaptable de la fotografía a la izquierda y texto extraído editable a la derecha.
- **OCR sin dependencias pesadas**: utiliza el motor nativo de Windows (`Windows.Media.Ocr`) y detecta automáticamente **Tesseract OCR** si está instalado en el sistema.
- **Herramientas integradas**: rotación de imagen en 90°, mejora opcional de contraste, pegado rápido desde el portapapeles (`Ctrl + V`), copiado con un clic y exportación a `.txt`.

## Requisitos

- Windows 10 / 11
- Python 3.10+
- `Pillow` (`pip install -r requirements.txt`)

## Uso

Ejecuta desde la terminal:

```bash
python main.py
```

O haz doble clic sobre `iniciar.bat` en Windows.
