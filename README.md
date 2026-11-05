# LectorFotos — Extractor de Texto en Imágenes (OCR)

Aplicación de escritorio en Python con interfaz gráfica (`tkinter` + `Pillow`) que permite seleccionar fotografías o pegar capturas desde el portapapeles e identificar automáticamente el texto contenido en ellas.

## Características

- **Dos paneles interactivos**: vista previa adaptable de la fotografía a la izquierda y texto extraído editable a la derecha.
- **Resaltado visual**: dibuja recuadros sobre las líneas de texto detectadas directamente en la imagen.
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
