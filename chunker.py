# chunker.py -- documents ko tukdon mein todna
def chunk_fixed(text: str, size: int = 300, overlap: int = 50) -> list[str]:
    """Naive: fixed number of characters, ignoring meaning."""
    chunks = []
    start = 0
    step = size - overlap

    while start < len(text):
        chunks.append(text[start:start + size])
        start += step

    return chunks


def chunk_by_paragraph(text: str, max_size: int = 400) -> list[str]:
    """Better: keep paragraphs whole, pack them up to max_size."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para

        if len(candidate) <= max_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = para

    if current:
        chunks.append(current)

    return chunks

def split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (section_title, section_body) pairs on '## ' headings."""
    sections: list[tuple[str, list[str]]] = []
    current_title = "General"
    current_body: list[str] = []

    for line in text.split("\n"):
        if line.startswith("## "):
            if current_body:
                sections.append((current_title, current_body))
            current_title = line[3:].strip()
            current_body = []
        elif line.startswith("# "):
            continue                      # document title -- skip
        else:
            current_body.append(line)

    if current_body:
        sections.append((current_title, current_body))

    return [(title, "\n".join(body).strip()) for title, body in sections]


def _make_chunk(body: str, source: str, section: str) -> dict:
    """One chunk = its text plus the metadata we will need later."""
    return {
        "text": f"[{source} > {section}]\n{body}",
        "source": source,
        "section": section,
        "chars": len(body),
    }


def chunk_document(text: str, source: str, max_size: int = 400) -> list[dict]:
    """Chunk a markdown document without ever crossing a section boundary."""
    chunks: list[dict] = []

    for section, body in split_sections(text):
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        buffer = ""

        for para in paragraphs:
            candidate = f"{buffer}\n\n{para}" if buffer else para

            if len(candidate) <= max_size:
                buffer = candidate
                continue

            if buffer:
                chunks.append(_make_chunk(buffer, source, section))
            buffer = para

        if buffer:
            chunks.append(_make_chunk(buffer, source, section))

    return chunks

if __name__ == "__main__":
    with open("docs/shopkart_policies.md", encoding="utf-8") as f:
        document = f.read()

    print(f"document length: {len(document)} chars\n")

    for name, chunks in [
        ("FIXED (300 chars)", chunk_fixed(document)),
        ("BY PARAGRAPH (max 400)", chunk_by_paragraph(document)),
    ]:
        print("=" * 60)
        print(f"{name}  ->  {len(chunks)} chunks")
        print("=" * 60)
        for i, chunk in enumerate(chunks[:4]):
            print(f"\n[{i}] ({len(chunk)} chars)")
            print(chunk)
        print()

    print("=" * 60)
    print("STRUCTURE-AWARE")
    print("=" * 60)

    smart = chunk_document(document, source="shopkart_policies.md")
    print(f"-> {len(smart)} chunks\n")

    for i, chunk in enumerate(smart):
        print(f"[{i}] section={chunk['section']!r} chars={chunk['chars']}")
        print(chunk["text"])
        print()