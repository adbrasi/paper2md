import pymupdf


def make_pdf(pages=1, label="example"):
    with pymupdf.open() as document:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 72), f"{label} page {index + 1}")
        return document.tobytes()
