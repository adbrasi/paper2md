import base64
import binascii
import html
import json
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from markdown_it import MarkdownIt

from .transport import PaperError


def annotation_text(value):
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value
    if isinstance(value, dict):
        return str(value.get("description") or value.get("summary") or value.get("short_description") or "")
    return ""


def render_document(response, directory, images=True, describe_images=True):
    directory = Path(directory)
    pages, warnings = [], []
    extensions = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
    for page in response["pages"]:
        markdown = page["markdown"]
        for position, image in enumerate(page.get("images") or [], 1):
            if not isinstance(image, dict) or not isinstance(image.get("id"), str):
                raise PaperError("Imagem OCR sem identificador válido.")
            identifier = image["id"]
            description = annotation_text(image.get("image_annotation")) if describe_images else ""
            caption = "\n\n> Descrição gerada por IA: " + description.replace("\n", " ") + "\n\n" if description else ""
            replacement = "[Figura extraída]"
            encoded = image.get("image_base64")
            if images and encoded:
                if not isinstance(encoded, str):
                    raise PaperError("Imagem OCR com codificação inválida.")
                match = re.fullmatch(r"data:([^;]+);base64,(.*)", encoded, re.S)
                media, payload = (match[1], match[2]) if match else ("image/jpeg", encoded)
                if media not in extensions:
                    raise PaperError("Formato de imagem OCR não suportado.")
                try:
                    decoded = base64.b64decode(payload, validate=True)
                except (ValueError, binascii.Error):
                    raise PaperError("Imagem OCR em Base64 inválido.") from None
                name = f"p{page['index'] + 1}-{position}.{extensions[media]}"
                assets = directory / "assets"
                assets.mkdir(exist_ok=True)
                (assets / name).write_bytes(decoded)
                replacement = f"![Figura {position} da página {page['index'] + 1}](assets/{name})"
            elif images:
                warnings.append(f"Imagem {position} da página {page['index'] + 1} sem dados Base64.")
            if describe_images and not description:
                warnings.append(f"Figura {position} da página {page['index'] + 1} sem descrição retornada pela API.")
            pattern = r"!\[[^\]]*\]\(<?" + re.escape(identifier) + r">?\)"
            markdown, count = re.subn(pattern, lambda _: replacement + caption, markdown)
            if not count:
                markdown += "\n\n" + replacement + caption
        pages.append(f"<!-- Página {page['index'] + 1} -->\n\n{markdown.strip()}")
    return "\n\n".join(pages) + "\n", warnings


def markdown_to_text(markdown):
    parser = MarkdownIt("commonmark").enable("table")
    output = []
    links = []
    def inline(tokens):
        for token in tokens or []:
            if token.type in ("text", "code_inline", "math_inline", "math_block"):
                output.append(token.content)
            elif token.type in ("softbreak", "hardbreak"):
                output.append("\n")
            elif token.type == "image":
                output.append(token.content)
            elif token.type == "link_open":
                links.append(token.attrGet("href"))
            elif token.type == "link_close":
                href = links.pop() if links else None
                if href:
                    output.append(f" ({href})")
            elif token.type == "html_inline":
                output.append(html.unescape(re.sub(r"<[^>]+>", "", token.content.replace("<br>", "\n").replace("<br/>", "\n"))))
            elif token.children:
                inline(token.children)
    for token in parser.parse(markdown):
        if token.type == "inline":
            inline(token.children)
        elif token.type in ("fence", "code_block"):
            output.append(token.content + "\n")
        elif token.type == "html_block":
            cleaned = re.sub(r"<!--[\s\S]*?-->", "", token.content)
            output.append(html.unescape(re.sub(r"<[^>]+>", "", cleaned)))
        elif token.type in ("paragraph_close", "heading_close", "tr_close", "blockquote_close"):
            output.append("\n\n")
        elif token.type in ("td_close", "th_close"):
            output.append("\t")
        elif token.type == "list_item_open":
            output.append("- ")
    return re.sub(r"\n{3,}", "\n\n", "".join(output)).strip() + "\n"


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def publish_bundle(target, pdf, response, manifest, options):
    target = Path(target)
    root = target.parent.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.resolve().parent != root:
        raise PaperError("Destino inválido ou link simbólico.")
    if target.exists() and not options.force:
        raise PaperError("Destino já existe; use --force para substituir.")
    staging = Path(tempfile.mkdtemp(prefix=".paper2md-", dir=root))
    backup = None
    try:
        markdown, warnings = render_document(response, staging, options.images, options.describe_images)
        (staging / "paper.pdf").write_bytes(pdf)
        (staging / "paper.md").write_text(markdown, encoding="utf-8")
        write_json(staging / "ocr.json", response)
        if options.format == "txt":
            (staging / "paper.txt").write_text(markdown_to_text(markdown), encoding="utf-8")
        manifest["warnings"] = warnings
        write_json(staging / "manifest.json", manifest)
        if target.exists():
            backup = root / (".paper2md-backup-" + uuid.uuid4().hex)
            target.rename(backup)
        try:
            staging.rename(target)
        except OSError:
            if backup:
                backup.rename(target)
                backup = None
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup and backup.exists():
            if backup.is_dir():
                shutil.rmtree(backup)
            else:
                backup.unlink()
    return warnings
