#!/usr/bin/env python3
"""
ETF 持仓抓取脚本
-----------------

给定中国市场 ETF 的六位代码，使用东方财富网 F10 披露接口抓取最新披露的股票持仓，
并输出所有股票代码（保持披露顺序）。

使用方法：
    python3 fetch_etf_holdings.py 562590
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Iterable, List, Optional, Sequence, Tuple

import requests
from bs4 import BeautifulSoup

FUND_ARCHIVES_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


@dataclass
class TableData:
    headers: List[str]
    rows: List[List[str]]


@dataclass
class QuarterHolding:
    label: str
    entries: List[Tuple[str, str]]
    fund_name: str


class FirstTableParser(HTMLParser):
    """简单 HTML 表格解析器，只抓取第一张表格的数据。"""

    def __init__(self) -> None:
        super().__init__()
        self._table_depth = 0
        self._capture = False
        self._in_cell = False
        self._current_cell: List[str] = []
        self._current_row: List[str] = []
        self._rows: List[List[str]] = []
        self._headers: List[str] = []
        self._seen_body_row = False

    def handle_starttag(self, tag: str, attrs):
        if tag == "table":
            if self._table_depth == 0:
                self._capture = True
            self._table_depth += 1
        if not self._capture:
            return
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._current_cell = []

    def handle_data(self, data: str):
        if self._capture and self._in_cell:
            self._current_cell.append(data.strip())

    def handle_endtag(self, tag: str):
        if tag == "table":
            if self._capture:
                self._capture = False
            self._table_depth = max(0, self._table_depth - 1)
        if not self._capture and self._table_depth == 0:
            return
        if tag in ("td", "th") and self._in_cell:
            cell_text = "".join(self._current_cell).strip()
            self._current_row.append(cell_text)
            self._in_cell = False
        elif tag == "tr" and self._current_row:
            if not self._headers:
                self._headers = self._current_row
            else:
                # 某些表头可能重复在 tbody，需要根据是否遇到过正文行判断
                if all(not cell for cell in self._current_row):
                    return
                if not self._seen_body_row and self._current_row == self._headers:
                    return
                self._rows.append(self._current_row)
                self._seen_body_row = True

    def table(self) -> Optional[TableData]:
        if not self._headers or not self._rows:
            return None
        return TableData(headers=self._headers, rows=self._rows)


def decode_eastmoney_payload(raw: str) -> str:
    """将东方财富接口返回的 content 字段反转义成 HTML。"""
    step1 = raw.encode("utf-8").decode("unicode_escape")
    # 解码后编码集为 latin-1，再转为 utf-8
    return step1.encode("latin1").decode("utf-8")


def extract_content_field(payload: str) -> Optional[str]:
    marker = 'content:"'
    start = payload.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = payload.find('",arryear', start)
    if end == -1:
        end = payload.find('",curyear', start)
    if end == -1:
        return None
    return payload[start:end]


def fetch_holdings_html(etf_code: str) -> str:
    params = {
        "type": "jjcc",
        "code": etf_code,
        "topline": "1000",
        "year": "",
        "month": "",
    }
    referer = f"https://fundf10.eastmoney.com/ccmx_{etf_code}.html"
    headers = {**HEADERS, "Referer": referer}
    resp = requests.get(FUND_ARCHIVES_URL, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    content = extract_content_field(resp.text)
    if not content:
        raise ValueError("未能在接口响应中找到持仓数据。")
    html = decode_eastmoney_payload(content)
    return unescape(html)


def _deduplicate_entries(entries: Iterable[Tuple[str, str]]) -> List[Tuple[str, str]]:
    seen = set()
    ordered: List[Tuple[str, str]] = []
    for code, name in entries:
        if code not in seen:
            seen.add(code)
            ordered.append((code, name))
    return ordered


def _normalize_code(token: str) -> Optional[str]:
    code = token.strip().replace("\u3000", "").replace(" ", "")
    if not code:
        return None
    if "." in code:
        # 形如 1.688012，取最后 6 位数字
        parts = code.split(".")
        code = parts[-1]
    code = code[-6:] if len(code) > 6 and code[-6:].isdigit() else code
    if re.fullmatch(r"\d{6}", code):
        return code
    return None


def _parse_hidden_codes(raw_list: str) -> List[str]:
    tokens = (item.strip() for item in raw_list.split(","))
    codes = [
        (normalized, "")
        for token in tokens
        if (normalized := _normalize_code(token))
    ]
    return _deduplicate_entries(codes)


def _parse_table_codes(table_html: str) -> List[str]:
    parser = FirstTableParser()
    parser.feed(table_html)
    table = parser.table()
    if not table:
        return []
    headers = [header.replace(" ", "") for header in table.headers]
    preferred_header_candidates = ("股票代码", "证券代码", "代码")
    code_idx = -1
    for candidate in preferred_header_candidates:
        for idx, header in enumerate(headers):
            if candidate in header:
                code_idx = idx
                break
        if code_idx != -1:
            break
    if code_idx == -1:
        return []
    parsed_codes: List[Tuple[str, str]] = []
    for row in table.rows:
        if code_idx >= len(row):
            continue
        token = row[code_idx]
        name_token = row[code_idx + 1] if code_idx + 1 < len(row) else ""
        normalized = _normalize_code(token)
        if normalized:
            parsed_codes.append((normalized, name_token.strip()))
    return _deduplicate_entries(parsed_codes)


def parse_quarter_holdings(html: str) -> List[QuarterHolding]:
    soup = BeautifulSoup(html, "html.parser")
    holdings: List[QuarterHolding] = []
    box_items = soup.select("div.box > div.boxitem")
    if not box_items:
        raise ValueError("未解析到任何季度持仓数据，请稍后再试。")
    for box in box_items:
        header = box.find("h4", class_="t")
        if not header:
            continue
        label = header.get_text(strip=True)
        fund_name = ""
        name_node = header.find("a")
        if name_node:
            fund_name = (name_node.get("title") or name_node.get_text(strip=True) or "").strip()
        if not fund_name:
            fund_name = label
        entries: List[Tuple[str, str]] = []
        table_entries: List[Tuple[str, str]] = []
        hidden = box.find("div", id="gpdmList")
        if hidden and hidden.text:
            entries = _parse_hidden_codes(hidden.text)
        table = box.find("table")
        if table:
            table_entries = _parse_table_codes(str(table))
            if not entries:
                entries = table_entries
        if entries and table_entries:
            name_lookup = {code: name for code, name in table_entries if name}
            enriched: List[Tuple[str, str]] = []
            for code, name in entries:
                if not name:
                    name = name_lookup.get(code, "")
                enriched.append((code, name))
            entries = enriched
        if entries:
            holdings.append(QuarterHolding(label=label, entries=entries, fund_name=fund_name))
    if not holdings:
        raise ValueError("未能从页面提取到任何持仓股票代码。")
    return holdings


def sanitize_filename(value: str) -> str:
    sanitized = re.sub(r'[\\/:*?"<>|]+', "_", value)
    sanitized = sanitized.strip().strip(".")
    return sanitized or "etf_holdings"


def choose_quarter(
    holdings: Sequence[QuarterHolding],
    min_count: int,
    preferred_keyword: Optional[str] = None,
) -> QuarterHolding:
    if not holdings:
        raise ValueError("持仓列表为空。")
    if preferred_keyword:
        for item in holdings:
            if preferred_keyword in item.label:
                return item
    for item in holdings:
        if len(item.entries) >= min_count:
            return item
    return holdings[0]


def fetch_etf_holdings(etf_code: str) -> List[str]:
    html = fetch_holdings_html(etf_code)
    holdings = parse_quarter_holdings(html)
    chosen = choose_quarter(holdings, min_count=1)
    return [code for code, _ in chosen.entries]


def select_holdings_with_preferences(
    etf_code: str,
    min_count: int,
    quarter_keyword: Optional[str] = None,
) -> Tuple[QuarterHolding, List[QuarterHolding]]:
    html = fetch_holdings_html(etf_code)
    holdings = parse_quarter_holdings(html)
    selected = choose_quarter(
        holdings, min_count=min_count, preferred_keyword=quarter_keyword
    )
    return selected, holdings


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="获取中国 ETF 最新披露的股票持仓代码列表。"
    )
    parser.add_argument(
        "etf_code",
        help="ETF 的六位数字代码，例如 512170。"
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=20,
        help="期望至少包含的股票数量，若不足仅提示并输出全部可用持仓（默认：20）。",
    )
    parser.add_argument(
        "--quarter",
        help="优先选择的季度标签关键字，例如“2025年2季度”。",
    )
    parser.add_argument(
        "--list-quarters",
        action="store_true",
        help="仅列出可用季度及股票数量，不输出代码。",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    etf_code = args.etf_code.strip()
    if not re.fullmatch(r"\d{6}", etf_code):
        print("错误：ETF 代码应为 6 位数字。", file=sys.stderr)
        return 1
    min_count = max(args.min_count, 1)
    try:
        selected, holdings = select_holdings_with_preferences(
            etf_code=etf_code,
            min_count=min_count,
            quarter_keyword=args.quarter.strip() if args.quarter else None,
        )
    except Exception as exc:  # pylint: disable=broad-except
        print(f"获取持仓失败：{exc}", file=sys.stderr)
        return 2
    if args.list_quarters:
        for item in holdings:
            print(f"{item.label}\t{len(item.codes)}")
        return 0
    latest = holdings[0]
    latest_label = latest.label
    if args.quarter and args.quarter not in selected.label:
        print(
            f"提示：未找到包含“{args.quarter}”的季度标签，改用 {selected.label}。",
            file=sys.stderr,
        )
    if not args.quarter and selected.label != latest_label and len(latest.entries) < min_count:
        print(
            f"提示：最新披露的 {latest_label} 仅包含 {len(latest.entries)} 只股票，"
            f"已改用 {selected.label}（共 {len(selected.entries)} 只）。",
            file=sys.stderr,
        )
    if min_count > len(selected.entries):
        print(
            f"提示：{selected.label} 仅披露 {len(selected.entries)} 只股票，"
            f"低于设定的最少数量 {min_count}，已输出全部可用持仓。",
            file=sys.stderr,
        )
    fund_name = selected.fund_name or selected.label
    output_filename = sanitize_filename(f"{etf_code}_{fund_name}") + ".txt"
    pairs = selected.entries
    codes = [code for code, _ in pairs]
    with open(output_filename, "w", encoding="utf-8") as fh:
        fh.write(" ".join(codes))
    print(f"结果已保存到 {output_filename}", file=sys.stderr)
    enriched_filename = sanitize_filename(f"{etf_code}_{fund_name}_with_names") + ".txt"
    with open(enriched_filename, "w", encoding="utf-8") as fh:
        formatted_pairs = []
        for code, name in pairs:
            clean_name = name or ""
            clean_name = clean_name.replace(" ", "")
            if clean_name:
                formatted_pairs.append(f"{code}:{clean_name}")
            else:
                formatted_pairs.append(code)
        fh.write(" ".join(formatted_pairs))
    print(f"结果已保存到 {enriched_filename}", file=sys.stderr)
    for code in codes:
        print(code)
    return 0


if __name__ == "__main__":
    sys.exit(main())

