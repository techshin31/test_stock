"""Key-free official major-issue disclosures for the dilution risk policy.

This covers the five source report codes below, not every DART disclosure.
"""
from __future__ import annotations

from datetime import date
import hashlib
import re

from bs4 import BeautifulSoup

from data.collectors.public_dart_xbrl import PublicDartClient, PublicDartError

REPORT_TYPES = {
    "11306": ("PAID_IN_CAPITAL_INCREASE", "유상증자결정"),
    "11308": ("PAID_IN_CAPITAL_INCREASE", "유무상증자결정"),
    "11324": ("CONVERTIBLE_BOND", "전환사채권발행결정"),
    "11325": ("BOND_WITH_WARRANT", "신주인수권부사채권발행결정"),
    "11326": ("EXCHANGE_BOND", "교환사채권발행결정"),
}


def parse_events_page(raw: bytes, report_code: str, start: date, end: date):
    soup = BeautifulSoup(raw, "html.parser")
    total = re.search(r"total\s+([\d,]+)\s+items?\b", soup.get_text(" ", strip=True))
    if total is None or soup.find("table") is None:
        raise PublicDartError("PUBLIC_DART_RISK_INVALID_PAGE")
    subtype, name = REPORT_TYPES[report_code]
    records = []
    for tr in soup.select("tbody tr"):
        links = tr.find_all("a", onclick=re.compile("openReportViewerDetail"))
        if not links:
            continue
        owner = tr.find(onclick=re.compile("openCorpInfo"))
        identity = re.search(r"openCorpInfo\('(\d{8})'\)", owner["onclick"]) if owner else None
        cells = tr.find_all("td", recursive=False)
        if identity is None or len(cells) < 2 or not tr.select_one(".tagCom_kospi"):
            raise PublicDartError("PUBLIC_DART_RISK_IDENTITY")
        receipts = set()
        for link in links:
            match = re.search(r"openReportViewerDetail\('(\d{14})'.*,'(\d{5})'\)", link["onclick"])
            if match is None or match[2] != report_code:
                raise PublicDartError("PUBLIC_DART_RISK_RECEIPT")
            receipts.add(match[1])
        if len(receipts) != 1:
            raise PublicDartError("PUBLIC_DART_RISK_RECEIPT")
        receipt = receipts.pop()
        try:
            received = date.fromisoformat(cells[1].get_text(strip=True).replace(".", "-"))
            numbered = date(int(receipt[:4]), int(receipt[4:6]), int(receipt[6:8]))
        except ValueError:
            raise PublicDartError("PUBLIC_DART_RISK_DATE") from None
        if not start <= received <= end or numbered > received:
            raise PublicDartError("PUBLIC_DART_RISK_DATE")
        records.append({"corp_code": identity[1], "rcept_no": receipt, "rcept_dt": received,
                        "report_nm": name, "pblntf_ty": "B", "event_category_code": "CAPITAL_CHANGE",
                        "event_subtype_code": subtype, "corp_cls": "Y",
                        "rm": "DART_PUBLIC_MAJOR_ISSUES; POLICY_SCOPE_ONLY; REPORT_CODE="+report_code})
    return records, int(total[1].replace(",", ""))


class PublicDartEventsClient(PublicDartClient):
    def events(self, start: date, end: date):
        if start > end or start.year < 2015:
            raise ValueError("Public major issues require a valid period starting in 2015 or later")
        records = {}
        counts = {}
        self.source_pages = []
        for code in REPORT_TYPES:
            fetched = 0
            expected_total = None
            for page in range(1, 101):
                params = {"textCrpCik": "", "bgnDe": start.strftime("%Y.%m.%d"),
                          "endDe": end.strftime("%Y.%m.%d"), "startDate": start.strftime("%Y.%m.%d"),
                          "endDate": end.strftime("%Y.%m.%d"), "reportCode": code, "corpType": "P",
                          "pageIndex": str(page), "pageSize": "10", "pageUnit": "10",
                          "recordCountPerPage": "100", "sortStdr": "crp", "sortOrdr": "asc"}
                raw = self.request("/disclosureinfo/mainMatter/list.do", params, post=True, refresh=True)
                rows, total = parse_events_page(raw, code, start, end)
                self.source_pages.append({"report_code": code, "page": page,
                                          "sha256": hashlib.sha256(raw).hexdigest(),
                                          "bytes": len(raw), "total_rows": total})
                if expected_total is not None and total != expected_total:
                    raise PublicDartError("PUBLIC_DART_RISK_PAGINATION_CHANGED")
                expected_total = total
                if (len(rows) != min(100, max(total - fetched, 0))):
                    raise PublicDartError("PUBLIC_DART_RISK_PAGINATION_INCOMPLETE")
                for row in rows:
                    previous = records.get(row["rcept_no"])
                    if previous is not None and previous != row:
                        raise PublicDartError("PUBLIC_DART_RISK_CONFLICTING_RECEIPT")
                    records[row["rcept_no"]] = row
                fetched += len(rows)
                if fetched == total:
                    counts[code] = total
                    break
            else:
                raise PublicDartError("PUBLIC_DART_RISK_PAGINATION_LIMIT")
        return sorted(records.values(), key=lambda row: (row["rcept_dt"], row["rcept_no"])), counts
