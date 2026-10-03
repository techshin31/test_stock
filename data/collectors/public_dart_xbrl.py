"""Original DART XBRL archives from the official, unauthenticated public viewer.

This is an explicit alternative financial source, not an API-host override.
No API key is read or sent. Raw archives retain receipt identity and units.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
import time
import threading
import zipfile

from bs4 import BeautifulSoup
from lxml import etree
import requests

BASE = "https://engopendart.fss.or.kr"
NS = {"i": "http://www.xbrl.org/2003/instance", "d": "http://xbrl.org/2006/xbrldi",
      "l": "http://www.xbrl.org/2003/linkbase", "x": "http://www.w3.org/1999/xlink"}
XML_PARSER = dict(resolve_entities=False, no_network=True, load_dtd=False)


class PublicDartError(RuntimeError):
    pass


@dataclass(frozen=True)
class Filing:
    stock_code: str
    corp_code: str
    receipt: str
    received: date
    period_end: date
    title: str

    @property
    def report_code(self):
        return {3: "11013", 6: "11012", 9: "11014", 12: "11011"}[self.period_end.month]


class PublicDartClient:
    _request_lock = threading.Lock()
    _last_request_at = 0.0

    def __init__(self, cache_dir: Path, delay: float = 0.25):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.delay = delay

    def request(self, path, params=None, *, post=False, refresh=False):
        signature = json.dumps([path, params, post], sort_keys=True)
        key = hashlib.sha256(signature.encode()).hexdigest()
        target = self.cache_dir / (key + ".bin")
        if target.exists() and not refresh:
            return target.read_bytes()
        with self._request_lock:
            remaining = self.delay - (time.monotonic() - PublicDartClient._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
            PublicDartClient._last_request_at = time.monotonic()
        for attempt in range(3):
            try:
                response = (self.session.post(BASE + path, data=params, timeout=(10, 40)) if post
                            else self.session.get(BASE + path, params=params, timeout=(10, 40)))
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = status in (429, 502, 503, 504) or isinstance(
                    exc, (requests.Timeout, requests.ConnectionError)
                )
                if attempt == 2 or not retryable:
                    suffix = f": HTTP {status}" if status is not None else ""
                    raise PublicDartError("PUBLIC_DART_TRANSPORT: " + type(exc).__name__ + suffix) from None
                time.sleep(2 ** (attempt + 1))
        if not response.content:
            raise PublicDartError("PUBLIC_DART_EMPTY_RESPONSE")
        # Failed responses must not become persistent successful cache entries.
        if b"Please check" in response.content and b"URL" in response.content:
            raise PublicDartError("PUBLIC_DART_INVALID_RESPONSE")
        temp = target.with_suffix(".tmp")
        temp.write_bytes(response.content)
        temp.replace(target)
        (self.cache_dir / (key + ".json")).write_text(signature, encoding="utf-8")
        return response.content

    def company(self, stock_code: str) -> dict:
        html = self.request("/cmm/searchCorp.do", {"textCrpNm": stock_code})
        soup = BeautifulSoup(html, "html.parser")
        matches = []
        for tr in soup.select("tbody tr"):
            cells = tr.find_all("td", recursive=False)
            if len(cells) < 3 or cells[2].get_text(strip=True) != stock_code:
                continue
            cik = tr.select_one('input[name^="hiddenCikCD"]')
            name = tr.select_one('input[name^="hiddenCikNM"]')
            if cik is None or name is None:
                continue
            market = "KOSPI" if tr.select_one(".tagCom_kospi") else (
                "KOSDAQ" if tr.select_one(".tagCom_kosdaq") else "KONEX"
                if tr.select_one(".tagCom_konex") else None)
            matches.append(dict(stock_code=stock_code, corp_code=cik["value"],
                                company_name=name["value"], market_type_code=market,
                                status_code="ACTIVE"))
        if (len(matches) != 1 or not re.fullmatch(r"\d{8}", matches[0]["corp_code"])
                or matches[0]["market_type_code"] is None):
            raise PublicDartError("PUBLIC_DART_COMPANY_IDENTITY")
        return matches[0]

    def filings(self, company: dict, start: date, end: date) -> list[Filing]:
        results = []
        for page in range(1, 101):
            html = self.request("/disclosureinfo/fnltt/xbrl/list.do", {
                "textCrpCik": company["corp_code"], "startDate": start.strftime("%Y.%m.%d"),
                "endDate": end.strftime("%Y.%m.%d"), "rptType": ["11011", "11012", "11013"],
                "pageIndex": str(page), "recordCountPerPage": "100", "rcpp": "100",
                "sortStdr": "date", "sortOrdr": "desc",
            }, post=True, refresh=True)
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("tbody tr")
            found = 0
            for tr in rows:
                link = tr.find("a", onclick=re.compile("openXbrlReportViewerElementPop"))
                if link is None:
                    continue
                receipt = re.search(r"'(\d{14})'", link["onclick"])
                owner = tr.find(onclick=re.compile("openCorpInfo"))
                if receipt is None or owner is None or company["corp_code"] not in owner["onclick"]:
                    raise PublicDartError("PUBLIC_DART_FILING_IDENTITY")
                title = link.get_text(" ", strip=True)
                period = re.search(r"\((\d{4})\.(\d{2})\)", title)
                cells = tr.find_all("td", recursive=False)
                if period is None or len(cells) < 4:
                    raise PublicDartError("PUBLIC_DART_FILING_PERIOD")
                received = date.fromisoformat(cells[3].get_text(strip=True).replace(".", "-"))
                year, month = map(int, period.groups())
                report_type = title.split("(", 1)[0].lower()
                annual = "annual" in report_type and "semi" not in report_type
                semi = "semi" in report_type
                quarterly = "quarter" in report_type
                if (month not in (3, 6, 9, 12) or (annual and month != 12)
                        or (semi and month != 6) or (quarterly and month not in (3, 9))
                        or not (annual or semi or quarterly)):
                    # Non-December fiscal years need a separate validated fiscal calendar.
                    continue
                period_end = date(year, month, calendar.monthrange(year, month)[1])
                number = receipt[1]
                numbered_date = date.fromisoformat(f"{number[:4]}-{number[4:6]}-{number[6:8]}")
                # A receipt created late in the day may be listed the next day.
                # Use the later official public filing date as availability.
                if numbered_date > received or not start <= received <= end or period_end > received:
                    raise PublicDartError("PUBLIC_DART_FILING_DATE")
                results.append(Filing(company["stock_code"], company["corp_code"], number, received, period_end, title))
                found += 1
            pagination = re.search(r"total\s+([\d,]+)\s+items?\b", soup.get_text(" ", strip=True))
            if pagination is None:
                raise PublicDartError("PUBLIC_DART_FILING_PAGINATION")
            total = int(pagination[1].replace(",", ""))
            if page * 100 >= total or found == 0:
                if total and not results:
                    raise PublicDartError("PUBLIC_DART_FILING_LIST_EMPTY")
                break
        else:
            raise PublicDartError("PUBLIC_DART_FILING_PAGINATION_LIMIT")
        return sorted({f.receipt: f for f in results}.values(), key=lambda f: (f.received, f.receipt))

    def archive(self, filing: Filing) -> bytes:
        html = self.request("/xbrl/viewer/main.do", {"rcpNo": filing.receipt, "lang": "en"})
        sequences = set(re.findall(r"viewDoc\('(\d+)'", html.decode("utf-8")))
        if len(sequences) != 1:
            raise PublicDartError("PUBLIC_DART_XBRL_SEQUENCE_UNAVAILABLE")
        archive = self.request("/xbrl/download/xbrl/origin.do", {
            "xbrlExtSeq": sequences.pop(), "rcpNo": filing.receipt, "lang": "ko",
        })
        if not zipfile.is_zipfile(io.BytesIO(archive)):
            raise PublicDartError("PUBLIC_DART_INVALID_XBRL_ARCHIVE")
        return archive


def _xml(raw: bytes):
    # Older official files use a Korean accounting-firm name as an unused
    # namespace URI. Permit that URI warning only, never malformed XML recovery.
    parser = etree.XMLParser(**XML_PARSER, recover=True)
    root = etree.fromstring(raw, parser=parser)
    if root is None or any(error.type_name not in {"WAR_NS_URI", "WAR_NS_URI_RELATIVE"} for error in parser.error_log):
        raise PublicDartError("XBRL_INVALID_XML")
    if root.getroottree().docinfo.doctype:
        raise PublicDartError("XBRL_DTD_FORBIDDEN")
    return root


def archive_labels(z) -> dict[str, str]:
    """Use standard Korean labels embedded in the original filing, not guesses."""
    labels = {}
    for name in z.namelist():
        if not name.endswith("_lab-ko.xml"):
            continue
        for link in _xml(z.read(name)).findall("l:labelLink", NS):
            locs = {e.get("{"+NS["x"]+"}label"): e.get("{"+NS["x"]+"}href", "").split("#")[-1]
                    for e in link.findall("l:loc", NS)}
            resources = {e.get("{"+NS["x"]+"}label"): e for e in link.findall("l:label", NS)}
            for arc in link.findall("l:labelArc", NS):
                account = locs.get(arc.get("{"+NS["x"]+"}from"))
                resource = resources.get(arc.get("{"+NS["x"]+"}to"))
                if account and resource is not None and resource.text:
                    if resource.get("{"+NS["x"]+"}role") == "http://www.xbrl.org/2003/role/label":
                        labels[account] = resource.text.strip()
                    elif account not in labels:
                        labels[account] = resource.text.strip()
    return labels


def parse_archive(raw: bytes, filing: Filing) -> tuple[list[dict], dict]:
    """Select original CFS facts with an exact period, entity, unit and statement."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if sum(i.file_size for i in z.infolist()) > 128 * 1024 * 1024:
            raise PublicDartError("XBRL_ARCHIVE_TOO_LARGE")
        names = z.namelist()
        expected = f"entity{filing.corp_code}_{filing.period_end.isoformat()}.xbrl"
        instances = [name for name in names if Path(name).name == expected]
        if len(instances) != 1:
            raise PublicDartError("XBRL_ENTITY_PERIOD_MISMATCH")
        root = _xml(z.read(instances[0]))
        labels = archive_labels(z)
        concepts = {}
        for name in names:
            if not name.endswith("_pre.xml"):
                continue
            for link in _xml(z.read(name)).findall("l:presentationLink", NS):
                role = link.get("{" + NS["x"] + "}role", "").split("role-")[-1]
                # Consolidated primary statements only; never notes or OFS roles.
                if not re.fullmatch(r"D(?:B|I|S|X)?[2345]\d{4}0", role):
                    continue
                kind = {"2": "BS", "3": "IS", "4": "CIS", "5": "CF"}[re.search(r"[2345]", role)[0]]
                for loc in link.findall("l:loc", NS):
                    account = loc.get("{" + NS["x"] + "}href", "").split("#")[-1]
                    concepts.setdefault(account, set()).add(kind)
        contexts = {}
        for context in root.findall("i:context", NS):
            identifier = context.findtext("i:entity/i:identifier", namespaces=NS)
            if identifier != filing.corp_code:
                continue
            members = context.findall(".//d:explicitMember", NS)
            if context.findall(".//d:typedMember", NS) or len(members) != 1:
                continue
            dimension = members[0].get("dimension", "").split(":")[-1]
            if dimension != "ConsolidatedAndSeparateFinancialStatementsAxis" or (members[0].text or "").split(":")[-1] != "ConsolidatedMember":
                continue
            period = context.find("i:period", NS)
            instant = period.findtext("i:instant", namespaces=NS)
            end = period.findtext("i:endDate", namespaces=NS)
            start = period.findtext("i:startDate", namespaces=NS)
            if (instant or end) != filing.period_end.isoformat():
                continue
            if start is not None:
                start = date.fromisoformat(start)
                if start.year != filing.period_end.year or start > filing.period_end:
                    continue
            contexts[context.get("id")] = (instant is not None, start)
        units = {}
        for unit in root.findall("i:unit", NS):
            measures = unit.findall("i:measure", NS)
            units[unit.get("id")] = (len(measures) == 1 and measures[0].text == "iso4217:KRW")
        values = {}
        precisions = []
        for fact in root:
            if not isinstance(fact.tag, str) or fact.get("contextRef") not in contexts:
                continue
            account = str(fact.prefix) + "_" + etree.QName(fact).localname
            if account not in concepts or fact.get("{http://www.w3.org/2001/XMLSchema-instance}nil") in ("true", "1"):
                continue
            if not units.get(fact.get("unitRef")):
                continue
            try:
                amount = Decimal(fact.text)
                if not amount.is_finite() or amount != amount.to_integral_value():
                    raise PublicDartError("XBRL_INVALID_KRW_AMOUNT")
            except (InvalidOperation, TypeError):
                raise PublicDartError("XBRL_INVALID_KRW_AMOUNT") from None
            instant, start = contexts[fact.get("contextRef")]
            for statement in concepts[account]:
                if (statement == "BS") != instant:
                    continue
                key = (statement, account, start)
                if key in values and values[key] != int(amount):
                    raise PublicDartError("XBRL_CONFLICTING_DUPLICATE_FACT")
                values[key] = int(amount)
            if etree.QName(fact).localname in {"Assets", "Liabilities", "Equity"}:
                decimals = fact.get("decimals", "0")
                precisions.append(10 ** max(-int(decimals), 0) if decimals != "INF" else 1)
        rows = []
        for statement, account in sorted({(k[0], k[1]) for k in values}):
            candidates = {k[2]: v for k, v in values.items() if k[:2] == (statement, account)}
            if statement == "BS":
                current, cumulative, period_start = candidates[None], None, None
            else:
                annual_start = date(filing.period_end.year, 1, 1)
                if annual_start not in candidates:
                    continue
                quarter_start = date(filing.period_end.year, filing.period_end.month - 2, 1)
                cumulative = candidates[annual_start]
                current = candidates.get(quarter_start)
                # CF often only supplies YTD: leave the single-quarter hint empty.
                # Q4 must be computed from FY minus Q3, never take FY as Q4.
                period_start = annual_start
            rows.append(dict(stock_code=filing.stock_code, corp_code=filing.corp_code,
                bsns_year=filing.period_end.year, reprt_code=filing.report_code, fs_div="CFS",
                sj_div=statement, account_id=account, account_nm=labels.get(account, account),
                source_rcept_no=filing.receipt, rcept_dt=filing.received, available_date=filing.received,
                period_start=period_start, period_end=filing.period_end,
                thstrm_amount=current, thstrm_add_amount=cumulative, revision_no=0))
        bs = {r["account_id"].split("_")[-1]: r["thstrm_amount"] for r in rows if r["sj_div"] == "BS"}
        if not {"Assets", "Liabilities", "Equity"} <= bs.keys():
            raise PublicDartError("XBRL_CFS_BALANCE_MISSING")
        residual = bs["Assets"] - bs["Liabilities"] - bs["Equity"]
        tolerance = max(precisions or [1]) * 3
        if abs(residual) > tolerance:
            raise PublicDartError("XBRL_BALANCE_IDENTITY_FAILED")
        statements = {r["sj_div"] for r in rows}
        if not {"BS", "CF"} <= statements or not statements & {"IS", "CIS"}:
            raise PublicDartError("XBRL_PRIMARY_STATEMENTS_MISSING")
        return rows, dict(receipt=filing.receipt, stock_code=filing.stock_code,
            source="DART_PUBLIC_ORIGINAL_XBRL", archive_sha256=hashlib.sha256(raw).hexdigest(),
            period_end=filing.period_end.isoformat(), available_date=filing.received.isoformat(),
            currency="KRW", fs_div="CFS", rows=len(rows), balance_residual=residual,
            balance_tolerance=tolerance, point_in_time=True)
