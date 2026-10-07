from dataclasses import asdict, dataclass, field
import re


@dataclass
class Paper:
    id: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    published: str | None = None
    updated: str | None = None
    abstract: str | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    citations: int | None = None
    sources: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def identity_keys(paper):
    keys = {paper.id, *paper.aliases}
    if paper.doi:
        keys.add("doi:" + paper.doi.lower().removeprefix("https://doi.org/"))
    title = re.sub(r"[^\w]", "", paper.title.lower())
    if title:
        keys.add("title:" + title)
    return keys


def deduplicate(papers):
    result = []
    for paper in papers:
        matches = [p for p in result if identity_keys(p) & identity_keys(paper)]
        if not matches:
            result.append(paper)
            continue
        target = matches[0]
        for other in [paper, *matches[1:]]:
            target.sources = list(dict.fromkeys(target.sources + other.sources))
            target.aliases = list(dict.fromkeys(target.aliases + [other.id] + other.aliases))
            for name in ("doi", "pdf_url", "url", "abstract", "venue", "published", "updated", "authors", "citations"):
                if not getattr(target, name) and getattr(other, name):
                    setattr(target, name, getattr(other, name))
            if other in result and other is not target:
                result.remove(other)
    return result
