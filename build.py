#!/usr/bin/env python3
"""Static multi-page builder for the 2026 로아온 가이드.

Single source of truth:
  templates/template.html   common page skeleton (head + sidebar + main + footer)
  templates/_scripts.html   shared footer (progress bar, scripts, fixed UI)
  style.css                 shared styles
  content/intro.md          landing intro block
  content/sectionN.md       one body fragment per top-level section

Output (flat, at dist/):
  dist/index.html           landing = intro + section TOC grid
  dist/sectionN.html        one page per section, with a 2-depth in-page index
  dist/style.css            copied
  dist/images/              copied from ./images
  dist/.nojekyll            disables Jekyll on GitHub Pages
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import struct
import sys
import markdown

ROOT = pathlib.Path(__file__).resolve().parent
CONTENT = ROOT / "content"
TEMPLATES = ROOT / "templates"
DIST = ROOT / "dist"
BG_DIR = ROOT / "images" / "bg"
BG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def list_background_images() -> list[str]:
    """images/bg/ 안의 이미지 파일 목록을 dist 기준 상대경로로 반환.
       폴더가 없거나 비어있으면 빈 리스트 (JS 쪽에서 빈 리스트면 아무 것도
       안 하고 조용히 넘어가도록 처리되어 있음)."""
    if not BG_DIR.exists():
        return []
    names = sorted(p.name for p in BG_DIR.iterdir() if p.suffix.lower() in BG_EXTS)
    return [f"images/bg/{n}" for n in names]


# Top-level navigation / page table. Order = display order.
# (page_id, output filename, short nav label, content fragment, <title>)
SITE_TITLE = "2026 로아온 윈터 뉴비/복귀 가이드"
SECTIONS = [
    ("section0", "section0.html", "0. 뉴비용 게임 소개", "section0.md", "0. 뉴비용 게임 소개"),
    ("section1", "section1.html", "1. 과금 요소", "section1.md", "1. 과금 요소"),
    ("section2", "section2.html", "2. 공식 게임 가이드", "section2.md", "2. 공식 게임 가이드"),
    ("section3", "section3.html", "3. 인게임 설정", "section3.md", "3. 인게임 설정"),
    ("section4", "section4.html", "4. 일일 콘텐츠", "section4.md", "4. 일일 콘텐츠"),
    ("section5", "section5.html", "5. 주간 콘텐츠", "section5.md", "5. 주간 콘텐츠"),
    ("section6", "section6.html", "6. 캘린더 콘텐츠", "section6.md", "6. 캘린더 콘텐츠"),
    ("section7", "section7.html", "7. 골드 수급처", "section7.md", "7. 골드 수급처"),
    ("section8", "section8.html", "8. 스펙업", "section8.md", "8. 스펙업"),
    ("section9", "section9.html", "9. 내실", "section9.md", "9. 내실"),
    ("section10", "section10.html", "10. 외부 사이트", "section10.md", "10. 외부 사이트"),
]
LANDING_ID = "index"
LANDING_FILE = "index.html"

RAW_IMG_RE = re.compile(
    r"https?://raw\.githubusercontent\.com/[^/]+/[^/]+/[^/]+/images/",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
ATTR_ID_RE = re.compile(r'\bid="([^"]+)"')
HEADING_RE = re.compile(
    r'<(h[23])\b([^>]*)>(.*?)</\1>',
    re.IGNORECASE | re.DOTALL,
)
EXISTING_ID_RE = re.compile(r'\bid="([^"]+)"')
HREF_ANCHOR_RE = re.compile(r'href="#([^"]+)"')
INLINE_LINK_STYLE_RE = re.compile(r'\s*style="color:\s*#3b82f6;[^"]*"')
NUM_PREFIX_RE = re.compile(r'^\s*\d+\.\s*')
MAIN_TITLE_RE = re.compile(
    r'<h1\b([^>]*)>(.*?)</h1>',
    re.IGNORECASE | re.DOTALL,
)


def section_num(pid: str) -> int | None:
    m = re.match(r"section(\d+)$", pid)
    return int(m.group(1)) if m else None


def short_label(label: str) -> str:
    """Drop a leading 'N. ' so the number lives only in the badge/chip."""
    return NUM_PREFIX_RE.sub("", label).strip()


SPINE_TIERS = [
    "common", "uncommon", "rare", "heroic", "legendary",
    "relic", "ancient", "esther", "legendary", "ancient",
]


CHUNK_HEADING_RE = re.compile(
    r'<(h[123])\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</\1>',
    re.IGNORECASE | re.DOTALL,
)
WS_RE = re.compile(r"\s+")
PLACEHOLDER_RE = re.compile(
    r'<div class="image-placeholder">.*?</div>', re.IGNORECASE | re.DOTALL
)


def _plain(segment: str) -> str:
    import html as _html
    segment = PLACEHOLDER_RE.sub(" ", segment)
    return WS_RE.sub(" ", _html.unescape(TAG_RE.sub(" ", segment))).strip()


def build_chunks(page_html: str, fname: str, page_title: str) -> list[dict]:
    heads = list(CHUNK_HEADING_RE.finditer(page_html))
    chunks: list[dict] = []
    if heads and heads[0].start() > 0:
        pre = _plain(page_html[: heads[0].start()])
        if pre:
            chunks.append({"file": fname, "anchor": "", "page": page_title,
                           "heading": page_title, "text": pre})
    for i, m in enumerate(heads):
        anchor = m.group(2)
        heading = _plain(m.group(3))
        end = heads[i + 1].start() if i + 1 < len(heads) else len(page_html)
        text = _plain(page_html[m.end():end])
        chunks.append({"file": fname, "anchor": anchor, "page": page_title,
                       "heading": heading or page_title, "text": text})
    return chunks


INLINE_RADIUS_RE = re.compile(r"border-radius:\s*\d+px")


def theme_inline_styles(html: str) -> str:
    html = html.replace("#fef3c7", "var(--accent-weak)")
    html = html.replace("color: #111", "color: var(--text)")
    html = html.replace("color:#e4bd61", "color: var(--tier-legendary)")
    html = html.replace("color:#28c6ff", "color: var(--tier-rare)")
    html = html.replace("color:#20e500", "color: var(--tier-uncommon)")
    html = INLINE_RADIUS_RE.sub("border-radius: 2px", html)
    return html


def slugify(text: str, seen: set[str]) -> str:
    text = TAG_RE.sub("", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w가-힣]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        text = "sec"
    base = text
    i = 2
    while text in seen:
        text = f"{base}-{i}"
        i += 1
    seen.add(text)
    return text


def rewrite_images(html: str) -> str:
    return RAW_IMG_RE.sub("images/", html)


# ---------- 이미지 CLS(레이아웃 시프트) 방지: width/height 자동 삽입 ----------
# 외부 의존성(Pillow) 없이 PNG/JPEG/GIF 헤더에서 픽셀 크기만 읽는다.
# img{}에 height:auto가 걸려있는 한, width/height 속성만 있어도 브라우저가
# 로딩 전부터 올바른 종횡비 공간을 미리 확보해준다.
IMG_TAG_RE = re.compile(r'<img\b([^>]*?)src="([^"]+)"([^>]*?)/?>', re.IGNORECASE)
_IMG_SIZE_CACHE: dict[str, tuple[int, int] | None] = {}


def _read_png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return None
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def _read_gif_size(data: bytes) -> tuple[int, int] | None:
    if data[:6] not in (b"GIF87a", b"GIF89a") or len(data) < 10:
        return None
    w, h = struct.unpack("<HH", data[6:10])
    return w, h


def _read_jpeg_size(data: bytes) -> tuple[int, int] | None:
    if data[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # SOF0/1/2/3/5/6/7/9/10/11/13/14/15 (SOF 마커, DHT/JPG 계열 제외)
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + seg_len
    return None


def _get_image_size(rel_src: str) -> tuple[int, int] | None:
    """dist 기준 상대경로(images/xxx.ext)의 실제 픽셀 크기를 읽는다. 실패 시 None."""
    if rel_src in _IMG_SIZE_CACHE:
        return _IMG_SIZE_CACHE[rel_src]
    size: tuple[int, int] | None = None
    if rel_src.startswith("images/"):
        path = ROOT / rel_src
        try:
            data = path.read_bytes()
            size = (_read_png_size(data) or _read_jpeg_size(data)
                    or _read_gif_size(data))
        except OSError:
            size = None
    _IMG_SIZE_CACHE[rel_src] = size
    return size


def add_image_dimensions(html: str) -> str:
    """로컬 이미지 <img> 태그에 width/height를 주입해 로딩 중 레이아웃 시프트를 방지한다."""
    def _inject(m: re.Match) -> str:
        pre, src, post = m.group(1), m.group(2), m.group(3)
        if "width=" in pre or "width=" in post:
            return m.group(0)  # 이미 크기 지정된 이미지는 건너뜀
        size = _get_image_size(src)
        if not size:
            return m.group(0)  # 크기를 못 읽으면(원격 URL 등) 원본 그대로 유지
        w, h = size
        return f'<img{pre}src="{src}"{post.rstrip()} width="{w}" height="{h}">'
    return IMG_TAG_RE.sub(_inject, html)


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def read_fragment(frag: str, pid: str) -> str:
    """Read target fragment, fallback to .html if .md doesn't exist, or placeholder."""
    p = CONTENT / frag
    if p.exists():
        return read(p)
    
    # .md 파일이 없으면 기존 .html 파일이 있는지 확인
    alt_p = CONTENT / (p.stem + ".html") if p.suffix == ".md" else CONTENT / (p.stem + ".md")
    if alt_p.exists():
        return read(alt_p)
        
    # 둘 다 없으면 임시 내용 생성
    return f"# {pid}\n\n내용 준비 중입니다."


def main() -> int:
    registry: dict[str, str] = {LANDING_ID: LANDING_FILE}
    for pid, fname, _label, _frag, _title in SECTIONS:
        registry[pid] = fname

    fragments = [("intro", "intro.md", LANDING_FILE)] + [
        (pid, frag, fname) for pid, fname, _label, frag, _title in SECTIONS
    ]

    raw_by_id: dict[str, str] = {}
    index_by_id: dict[str, list[tuple[str, str, str]]] = {}

    md_converter = markdown.Markdown(extensions=['md_in_html', 'attr_list', 'tables', 'fenced_code', 'toc', 'nl2br'])
    
    for pid, frag, fname in fragments:
        raw_text = read_fragment(frag, pid)
        html = md_converter.convert(raw_text)
        md_converter.reset()

    # === [추가] H2 기준으로 자동으로 div.card 감싸기 ===
        if pid != "intro": # intro가 아닌 일반 섹션 페이지일 때
            parts = re.split(r'(?=<h[2]\b)', html, flags=re.IGNORECASE)
            wrapped_parts = []
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if re.match(r'<h[2]\b', part, re.IGNORECASE):
                    wrapped_parts.append(f'<div class="card">\n{part}\n</div>')
                else:
                    wrapped_parts.append(part)
            html = "\n\n".join(wrapped_parts)
        # ===================================================
        
        seen: set[str] = set()

        for existing in EXISTING_ID_RE.findall(html):
            if existing in registry:
                continue
            slug = slugify(existing, seen)
            html = html.replace(f'id="{existing}"', f'id="{slug}"', 1)
            registry[existing] = f"{fname}#{slug}"

        entries: list[tuple[str, str, str]] = []

        def _inject(m: re.Match) -> str:
            tag, attrs, inner = m.groups()
            label = TAG_RE.sub("", inner).strip()
            existing = ATTR_ID_RE.search(attrs)
            if existing:
                slug = existing.group(1)
                entries.append((tag.lower(), slug, label))
                return m.group(0)
            slug = slugify(label, seen)
            entries.append((tag.lower(), slug, label))
            return f'<{tag}{attrs} id="{slug}">{inner}</{tag}>'

        html = HEADING_RE.sub(_inject, html)
        raw_by_id[pid] = html
        index_by_id[pid] = entries

    def finalize(html: str) -> str:
        def _href(m: re.Match) -> str:
            target = m.group(1)
            if target in registry:
                return f'href="{registry[target]}"'
            return m.group(0)
        html = HREF_ANCHOR_RE.sub(_href, html)
        html = INLINE_LINK_STYLE_RE.sub("", html)
        html = theme_inline_styles(html)
        html = rewrite_images(html)
        return add_image_dimensions(html)

    template = read(TEMPLATES / "template.html")
    scripts = read(TEMPLATES / "_scripts.html")
    bg_images_json = json.dumps(list_background_images(), ensure_ascii=False)

    DIST.mkdir(exist_ok=True)

    def spine(active: str) -> str:
        rows = []
        for i, (pid, fname, label, *_) in enumerate(SECTIONS):
            n = section_num(pid)
            badge = f"{n:02d}"
            tier = SPINE_TIERS[i % len(SPINE_TIERS)]
            is_active = active == pid
            cls = "spine-row active" if is_active else "spine-row"
            row = (
                f'<a class="{cls}" href="{fname}" style="--tier: var(--tier-{tier})">'
                f'<span class="spine-badge">{badge}</span>'
                f'<span class="spine-label">{short_label(label)}</span></a>'
            )
            sub = ""
            if is_active:
                h2s = [(slug, lbl) for level, slug, lbl in index_by_id.get(pid, []) if level == "h2"]
                if h2s:
                    links = "".join(
                        f'<a class="page-toc-link" href="#{slug}">{lbl}</a>'
                        for slug, lbl in h2s
                    )
                    sub = f'<div class="spine-subitems">{links}</div>'
            rows.append(f'<div class="spine-item">{row}{sub}</div>')
        return "\n                ".join(rows)

    def breadcrumb(pid: str) -> str:
        n = section_num(pid)
        if n is None:
            return '<span class="crumb-section">목차</span>'
        label = next(short_label(l) for p, _f, l, *_ in SECTIONS if p == pid)
        return (
            f'<span class="crumb-section">{label}</span>'
            f'<span class="crumb-sep" style="visibility:hidden">›</span>'
            f'<span class="crumb-current"></span>'
        )

    def with_chapter_chip(html: str, pid: str) -> str:
        n = section_num(pid)
        if n is None:
            return html

        def _wrap(m: re.Match) -> str:
            attrs, inner = m.group(1), m.group(2)
            text = short_label(TAG_RE.sub("", inner).strip())
            m_id = ATTR_ID_RE.search(attrs)
            hid = m_id.group(1) if m_id else f"sec-{n}"
            return (
                '<div class="chapter-head">'
                f'<span class="chapter-chip" aria-hidden="true">{n:02d}</span>'
                f'<h1 class="main-title" id="{hid}">{text}</h1>'
                '</div>'
            )
        return MAIN_TITLE_RE.sub(_wrap, html, count=1)

    def render(active: str, title: str, content: str, kind: str) -> str:
        page = template
        page = page.replace("{{TITLE}}", title)
        page = page.replace("{{PAGEKIND}}", kind)
        page = page.replace("{{BG_IMAGES}}", bg_images_json)
        page = page.replace("{{BREADCRUMB}}", breadcrumb(active))
        page = page.replace("{{SPINE}}", spine(active))
        page = page.replace("{{CONTENT}}", content)
        page = page.replace("{{SCRIPTS}}", scripts)
        return page

    cards = ['<div class="card"><div class="section-container">',
             '<h1 class="main-title">전체 목차</h1>',
             '<div class="landing-toc">']
    for i, (pid, fname, label, *_) in enumerate(SECTIONS):
        n = section_num(pid)
        tier = SPINE_TIERS[i % len(SPINE_TIERS)]
        cards.append(
            f'<a class="spine-row" href="{fname}" style="--tier: var(--tier-{tier})">'
            f'<span class="spine-badge">{n:02d}</span>'
            f'<span class="spine-label">{short_label(label)}</span></a>'
        )
    cards.append("</div></div></div>")
    landing_content = finalize(raw_by_id["intro"]) + "\n            " + "\n            ".join(cards)
    (DIST / LANDING_FILE).write_text(
        render(LANDING_ID, SITE_TITLE, landing_content, "landing"), encoding="utf-8"
    )

    for pid, fname, _label, _frag, title in SECTIONS:
        content = with_chapter_chip(finalize(raw_by_id[pid]), pid)
        (DIST / fname).write_text(
            render(pid, f"{title} | {SITE_TITLE}", content, "section"), encoding="utf-8"
        )

    # 404 페이지 — GitHub Pages가 저장소 루트의 404.html을 자동으로 인식해서 씀.
    # 실제 게임 이미지 대신, 사이트 accent 색을 그대로 쓰는 SVG(닻이 파도에
    # 떠내려가는 모양)를 그려서 테마 전환에도 자동으로 색이 맞게 했다.
    not_found_content = '''
<div class="card">
<div class="chapter-head">
<span class="chapter-chip" aria-hidden="true">404</span>
<h1 class="main-title">페이지를 찾을 수 없어요</h1>
</div>
</div>
<div class="card" style="text-align:center; padding: var(--sp-12) var(--sp-6);">
<svg width="200" height="200" viewBox="0 0 200 200" fill="none" aria-hidden="true" style="margin-bottom: var(--sp-6);">
  <circle cx="100" cy="40" r="18" stroke="var(--accent)" stroke-width="6"/>
  <line x1="100" y1="58" x2="100" y2="150" stroke="var(--accent)" stroke-width="6"/>
  <line x1="65" y1="85" x2="135" y2="85" stroke="var(--accent)" stroke-width="6"/>
  <path d="M 100 150 Q 40 150 40 100" stroke="var(--accent)" stroke-width="6" stroke-linecap="round"/>
  <path d="M 100 150 Q 160 150 160 100" stroke="var(--accent)" stroke-width="6" stroke-linecap="round"/>
  <path d="M 20 175 Q 45 165 70 175 T 120 175 T 170 175" stroke="var(--border)" stroke-width="4" stroke-linecap="round"/>
  <path d="M 10 190 Q 35 180 60 190 T 110 190 T 180 190" stroke="var(--border)" stroke-width="4" stroke-linecap="round" opacity="0.6"/>
</svg>
<p style="color: var(--text-muted); margin-bottom: var(--sp-6);">요청하신 페이지가 존재하지 않거나 다른 곳으로 이동했어요.</p>
<a href="index.html">홈으로 돌아가기</a>
</div>
'''
    (DIST / "404.html").write_text(
        render("", f"페이지를 찾을 수 없어요 | {SITE_TITLE}", not_found_content, "section"),
        encoding="utf-8",
    )

    search_index = []
    for src_pid, page_title in [("intro", SITE_TITLE)] + [
            (pid, title) for pid, _f, _l, _frag, title in SECTIONS]:
        fname = LANDING_FILE if src_pid == "intro" else f"{src_pid}.html"
        search_index.extend(build_chunks(raw_by_id[src_pid], fname, page_title))
    (DIST / "search-index.json").write_text(
        json.dumps(search_index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    shutil.copyfile(ROOT / "style.css", DIST / "style.css")
    dist_images = DIST / "images"
    if dist_images.exists():
        shutil.rmtree(dist_images)
    shutil.copytree(ROOT / "images", dist_images)
    (DIST / ".nojekyll").write_text("", encoding="utf-8")

    pages_n = 1 + len(SECTIONS)
    print(f"built {pages_n} pages into {DIST}/ (+ style.css, images/, .nojekyll)")
    return 0


if __name__ == "__main__":
    sys.exit(main())