"""Extract locally referenced PDF and image assets for knowledge-base indexing."""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree

from loguru import logger

_ASSET_LINK = re.compile(
    r"(?P<image>!?)\[(?P<label>[^\]]*)\]\((?:<(?P<angle>[^>]+)>|(?P<bare>[^\s)]+))(?:\s+\"[^\"]*\")?\)"
)
_IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"}
)
_DOCUMENT_SUFFIXES = frozenset({".pdf", ".docx", ".pptx"})
_MAX_ASSETS = 64
_MAX_ASSET_CHARS = 40_000
_MAX_TOTAL_CHARS = 1_500_000


@dataclass(frozen=True)
class KnowledgeAssetReport:
    """Details of supplementary local assets added to an indexed Markdown document."""

    discovered: int = 0
    indexed: int = 0
    skipped: tuple[str, ...] = field(default_factory=tuple)


class KnowledgeAssetService:
    """Turn Markdown-linked PDF and image assets into searchable text blocks."""

    def enrich_markdown(
        self,
        content: str,
        *,
        source_path: str | Path | None,
        include_unreferenced_assets: bool = True,
    ) -> tuple[str, KnowledgeAssetReport]:
        source = Path(source_path).resolve() if source_path else None
        if source is None or not source.is_file():
            return content, KnowledgeAssetReport()

        assets = list(
            self._referenced_assets(
                content, source, include_unreferenced_assets=include_unreferenced_assets
            )
        )[:_MAX_ASSETS]
        blocks: list[str] = []
        skipped: list[str] = []
        remaining = _MAX_TOTAL_CHARS
        for path, label in assets:
            try:
                suffix = path.suffix.lower()
                if suffix == ".pdf":
                    asset_text = self._extract_pdf(path)
                    kind = "PDF"
                elif suffix == ".docx":
                    asset_text = self._extract_office_xml(path, "word/document.xml")
                    kind = "DOCX"
                elif suffix == ".pptx":
                    asset_text = self._extract_pptx(path)
                    kind = "PPTX"
                else:
                    asset_text = self._extract_image(path, label)
                    kind = "图片"
            except Exception as exc:  # noqa: BLE001 - a bad asset must not block indexing
                logger.warning("知识库附件解析失败，已跳过 {}: {}", path, exc)
                skipped.append(path.name)
                continue
            if not asset_text:
                skipped.append(path.name)
                continue
            asset_text = asset_text[: min(_MAX_ASSET_CHARS, remaining)].strip()
            if not asset_text:
                break
            static_url = self._static_url(path)
            source_line = f"来源：{static_url}\n" if static_url else ""
            blocks.append(f"## 附件{kind}：{path.name}\n{source_line}{asset_text}")
            remaining -= len(asset_text)
            if remaining <= 0:
                break

        if not blocks:
            return content, KnowledgeAssetReport(discovered=len(assets), skipped=tuple(skipped))
        enriched = f"{content.rstrip()}\n\n<!-- knowledge-assets -->\n\n" + "\n\n".join(blocks)
        return enriched, KnowledgeAssetReport(
            discovered=len(assets), indexed=len(blocks), skipped=tuple(skipped)
        )

    def _referenced_assets(
        self, content: str, source: Path, *, include_unreferenced_assets: bool
    ) -> Iterable[tuple[Path, str]]:
        seen: set[Path] = set()
        for match in _ASSET_LINK.finditer(content):
            target = (match.group("angle") or match.group("bare") or "").strip()
            path = self._resolve_local_asset(target, source)
            if path is None or path in seen:
                continue
            suffix = path.suffix.lower()
            if suffix not in _DOCUMENT_SUFFIXES and suffix not in _IMAGE_SUFFIXES:
                continue
            seen.add(path)
            yield path, (match.group("label") or "").strip()
        if include_unreferenced_assets:
            for path in sorted(source.parent.iterdir(), key=lambda item: item.name.casefold()):
                if not path.is_file() or path in seen:
                    continue
                if (
                    path.suffix.lower() in _DOCUMENT_SUFFIXES
                    or path.suffix.lower() in _IMAGE_SUFFIXES
                ):
                    yield path, ""

    @staticmethod
    def _resolve_local_asset(target: str, source: Path) -> Path | None:
        if not target or target.startswith(("#", "data:", "http://", "https://", "mailto:")):
            return None
        parsed = urlparse(target)
        target_path = unquote(parsed.path)
        if not target_path:
            return None
        if target_path.startswith("/docs-static/"):
            docs_root = next((parent for parent in source.parents if parent.name == "docs"), None)
            if docs_root is None:
                return None
            candidate = docs_root / target_path.removeprefix("/docs-static/")
        elif target_path.startswith("/"):
            return None
        else:
            candidate = source.parent / target_path
        try:
            resolved = candidate.resolve()
            knowledge_root = next(
                (parent / "knowledge" for parent in source.parents if parent.name == "docs"),
                source.parent,
            ).resolve()
            resolved.relative_to(knowledge_root)
        except ValueError:
            return None
        return resolved if resolved.is_file() else None

    @staticmethod
    def _extract_pdf(path: Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("未安装 pypdf，无法提取知识库 PDF 文本: {}", path)
            return ""
        reader = PdfReader(str(path))
        pages: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"[第 {page_number} 页]\n{text}")
        return "\n\n".join(pages)

    @staticmethod
    def _extract_office_xml(path: Path, member: str) -> str:
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read(member))
        values = [
            node.text.strip() for node in root.iter() if node.tag.endswith("}t") and node.text
        ]
        return "\n".join(value for value in values if value)

    @staticmethod
    def _extract_pptx(path: Path) -> str:
        sections: list[str] = []
        with zipfile.ZipFile(path) as archive:
            slide_names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
            for index, slide_name in enumerate(slide_names, start=1):
                root = ElementTree.fromstring(archive.read(slide_name))
                values = [
                    node.text.strip()
                    for node in root.iter()
                    if node.tag.endswith("}t") and node.text
                ]
                text = "\n".join(value for value in values if value)
                if text:
                    sections.append(f"[第 {index} 页]\n{text}")
        return "\n\n".join(sections)

    @staticmethod
    def _static_url(path: Path) -> str:
        docs_root = next((parent for parent in path.parents if parent.name == "docs"), None)
        if docs_root is None:
            return ""
        relative = path.relative_to(docs_root)
        return "/docs-static/" + "/".join(quote(part) for part in relative.parts)

    @staticmethod
    def _extract_image(path: Path, label: str) -> str:
        details = [f"文件名：{path.name}"]
        if label:
            details.append(f"图像说明：{label}")
        try:
            from PIL import Image

            with Image.open(path) as image:
                details.append(f"尺寸：{image.width}×{image.height}")
        except Exception:  # noqa: BLE001 - SVG and damaged images still retain metadata
            pass
        ocr_text = KnowledgeAssetService._ocr(path)
        if ocr_text:
            details.append(f"OCR 文本：\n{ocr_text}")
        return "\n".join(details)

    @staticmethod
    def _ocr(path: Path) -> str:
        executable = shutil.which("tesseract")
        if not executable:
            return ""
        try:
            result = subprocess.run(
                [executable, str(path), "stdout", "-l", "chi_sim+eng"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return result.stdout.strip()[:_MAX_ASSET_CHARS] if result.returncode == 0 else ""
