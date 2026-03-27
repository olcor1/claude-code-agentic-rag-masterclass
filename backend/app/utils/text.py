def normalize_text(content: str) -> str:
    return " ".join(content.replace("\ufeff", "").split())


def chunk_text(content: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    cleaned = normalize_text(content)
    if not cleaned:
        return []

    step = max(chunk_size - chunk_overlap, 1)
    chunks: list[str] = []
    for start in range(0, len(cleaned), step):
        chunk = cleaned[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= len(cleaned):
            break
    return chunks
