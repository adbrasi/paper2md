from datetime import date
import os
import re
import time
import xml.etree.ElementTree as ET

from .models import Paper, deduplicate
from .sources import direct_source
from .transport import PaperError

# OpenAlex also indexes datasets, software releases and other non-paper records.
NON_PAPER_TYPES = {"dataset", "software", "paratext", "libguides", "other", "erratum", "grant", "peer-review",
                   "retraction", "supplementary-materials", "editorial", "standard"}
ATOM = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}


def two_years_ago(today=None):
    today = today or date.today()
    try:
        return today.replace(year=today.year - 2)
    except ValueError:
        return today.replace(year=today.year - 2, day=28)


def openalex_paper(record):
    def invalid():
        raise PaperError("OpenAlex: registro de paper malformado.")
    if not isinstance(record, dict) or not isinstance(record.get("id"), str):
        invalid()
    if not re.fullmatch(r"https://openalex.org/W\d+", record["id"]):
        invalid()
    for name in ("primary_location", "best_oa_location", "abstract_inverted_index"):
        if record.get(name) is not None and not isinstance(record[name], dict):
            invalid()
    for name in ("authorships", "locations"):
        if record.get(name) is not None and (not isinstance(record[name], list) or any(not isinstance(x, dict) for x in record[name])):
            invalid()
    for author in record.get("authorships") or []:
        if not isinstance(author.get("author"), dict) or not isinstance(author["author"].get("display_name"), str):
            invalid()
    for name in ("doi", "title", "display_name", "publication_date"):
        if record.get(name) is not None and not isinstance(record[name], str):
            invalid()
    location = record.get("primary_location") or {}
    locations = [record.get("best_oa_location") or {}, location, *(record.get("locations") or [])]
    for loc in locations:
        if loc.get("source") is not None and not isinstance(loc["source"], dict):
            invalid()
        for name in ("landing_page_url", "pdf_url"):
            if loc.get(name) is not None and not isinstance(loc[name], str):
                invalid()
    doi = (record.get("doi") or "").removeprefix("https://doi.org/") or None
    identifier = "openalex:" + record["id"].rsplit("/", 1)[-1]
    aliases = ["doi:" + doi] if doi else []
    for loc in locations:
        for link in (loc.get("landing_page_url"), loc.get("pdf_url")):
            if link and "arxiv.org/" in link:
                try:
                    arxiv = direct_source(link)
                    aliases.append(identifier)
                    identifier = arxiv.id
                    break
                except ValueError:
                    pass
    abstract = None
    index = record.get("abstract_inverted_index")
    if isinstance(index, dict):
        if any(not isinstance(word, str) or not isinstance(positions, list) or any(type(i) is not int or i < 0 for i in positions) for word, positions in index.items()):
            invalid()
        words = {position: word for word, positions in index.items() for position in positions}
        abstract = " ".join(words[p] for p in sorted(words))
    return Paper(id=identifier, title=record.get("title") or record.get("display_name") or identifier,
                 authors=[a.get("author", {}).get("display_name", "") for a in record.get("authorships") or []],
                 published=record.get("publication_date"), doi=doi, abstract=abstract,
                 venue=(location.get("source") or {}).get("display_name"),
                 citations=record.get("cited_by_count"), sources=["openalex"], aliases=list(dict.fromkeys(aliases)),
                 url=next((l["landing_page_url"] for l in locations if l.get("landing_page_url")), record.get("doi")),
                 pdf_url=next((l["pdf_url"] for l in locations if l.get("pdf_url")), None))


def lexical_query(text):
    words = re.findall(r"[\w-]+", text)
    stop = {"the", "a", "an", "and", "or", "of", "for", "with", "to", "on", "in", "papers", "recent", "sobre", "de", "e", "para", "um", "uma", "quero"}
    words = [w for w in words if w.lower() not in stop][:12]
    return " AND ".join(f'all:"{w}"' for w in words) or 'all:"research"'


class Searcher:
    def __init__(self, store, transport, openalex_key=None, rate_limit=True):
        self.store, self.transport = store, transport
        self.openalex_key = openalex_key if openalex_key is not None else os.getenv("OPENALEX_API_KEY")
        self.rate_limit = rate_limit

    def gate(self, provider, seconds):
        if not self.rate_limit:
            return
        with self.store.lock("rate:" + provider):
            path = self.store.home / (provider + "-request-time")
            previous = float(path.read_text()) if path.exists() else 0
            wait = seconds - (time.time() - previous)
            if wait > 0:
                time.sleep(min(wait, seconds))
            path.write_text(str(time.time()))

    def openalex(self, query, since, limit):
        self.gate("openalex", 1)
        headers = {"Authorization": "Bearer " + self.openalex_key} if self.openalex_key else None
        # search.semantic only accepts publication_year; exact dates are filtered after deduplication.
        data = self.transport.json_get("https://api.openalex.org/works", params={
            "search.semantic": query, "filter": f"publication_year:{since[:4]}-{date.today().year}",
            "per_page": min(limit * 2, 50)}, headers=headers, service="OpenAlex")
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise PaperError("OpenAlex: formato de resposta inválido.")
        return [openalex_paper(r) for r in data["results"] if not (isinstance(r, dict) and r.get("type") in NON_PAPER_TYPES)]

    def arxiv(self, query, since, limit):
        self.gate("arxiv", 3)
        start = since.replace("-", "") + "0000"
        end = date.today().strftime("%Y%m%d") + "2359"
        content, _, _ = self.transport.get("https://export.arxiv.org/api/query", params={
            "search_query": f"({lexical_query(query)}) AND submittedDate:[{start} TO {end}]",
            "start": 0, "max_results": min(limit * 2, 50), "sortBy": "relevance", "sortOrder": "descending"}, service="arXiv")
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            raise PaperError("arXiv: feed inválido.") from None
        papers = []
        for item in root.findall("a:entry", ATOM):
            identifier = item.findtext("a:id", "", ATOM)
            if "api/errors" in identifier:
                raise PaperError("arXiv: consulta recusada.")
            paper = direct_source(identifier)
            paper.title = " ".join(item.findtext("a:title", "", ATOM).split())
            paper.abstract = " ".join(item.findtext("a:summary", "", ATOM).split())
            paper.authors = [x.findtext("a:name", "", ATOM) for x in item.findall("a:author", ATOM)]
            paper.published = item.findtext("a:published", "", ATOM)[:10] or None
            paper.updated = item.findtext("a:updated", "", ATOM)[:10] or None
            paper.doi = item.findtext("x:doi", None, ATOM)
            paper.venue = item.findtext("x:journal_ref", None, ATOM) or "arXiv (preprint)"
            papers.append(paper)
        return papers

    def search_papers(self, queries, since=None, limit=10, sort="relevance"):
        # The caller (usually an LLM agent) writes the English technical queries; each one runs on
        # both providers and the rankings are fused, so no extra LLM call is needed here.
        queries = list(dict.fromkeys(q.strip() for q in ([queries] if isinstance(queries, str) else queries)))
        if not 1 <= len(queries) <= 5 or any(not q or len(q) > 2000 for q in queries):
            raise PaperError("Informe de 1 a 5 consultas, cada uma com 1 a 2000 caracteres.")
        if not 1 <= limit <= 50:
            raise PaperError("Limite deve estar entre 1 e 50.")
        if sort not in ("relevance", "recent"):
            raise PaperError("Ordenação inválida.")
        since = since or two_years_ago().isoformat()
        try:
            start = date.fromisoformat(since)
            if start > date.today():
                raise ValueError()
        except ValueError:
            raise PaperError("--since deve ser YYYY-MM-DD e não estar no futuro.") from None
        warnings, candidates, succeeded, scores = [], [], [], {}
        calls = [(provider, query) for query in queries for provider in ("OpenAlex", "arXiv")]
        for provider, query in calls:
            try:
                papers = (self.openalex if provider == "OpenAlex" else self.arxiv)(query, since, limit)
                succeeded.append(provider)
                for rank, p in enumerate(papers, 1):
                    scores[p.id] = scores.get(p.id, 0) + 1 / (60 + rank)
                candidates.extend(papers)
            except (ValueError, KeyError, TypeError) as exc:
                warnings.append(str(exc) if isinstance(exc, PaperError) else f"{provider}: resposta incompatível.")
        if not succeeded:
            raise PaperError("Busca indisponível em todas as fontes. " + " ".join(warnings))
        papers = [p for p in deduplicate(candidates) if p.published and since <= p.published[:10] <= date.today().isoformat()]
        if sort == "recent":
            papers.sort(key=lambda p: p.published or "", reverse=True)
        else:
            papers.sort(key=lambda p: sum(scores.get(i, 0) for i in {p.id, *p.aliases}), reverse=True)
        if not papers:
            warnings.append("Nenhum resultado na janela informada; use --since para ampliá-la ou consultas mais curtas.")
        return self.store.save_search({"queries": queries,
            "filters": {"since": since, "until": date.today().isoformat(), "limit": limit, "sort": sort},
            "providers": list(dict.fromkeys(succeeded)), "warnings": list(dict.fromkeys(warnings))}, papers[:limit])
