"""Extract research-relevant facts from untrusted social text.

Input is treated purely as data: we pull out contract addresses, chain hints
from well-known URLs, cashtags, referral links and promotional disclosures.
Nothing in the text is ever interpreted as an instruction.

Conservative by design: a bare base58 string is accepted as a Solana mint only
if it decodes to exactly 32 bytes, and generic words are never treated as
addresses.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from cit.chains import BY_DEXSCREENER, BY_GECKO

EVM_RE = re.compile(r"(?<![0-9a-fA-Fx])0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
B58_RE = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
CASHTAG_RE = re.compile(r"(?<![\w$])\$([A-Za-z][A-Za-z0-9]{1,14})\b")

B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# URL host -> chain resolution from the path.
EXPLORER_HOSTS = {
    "bscscan.com": "bsc",
    "etherscan.io": "ethereum",
    "basescan.org": "base",
    "solscan.io": "solana",
    "explorer.solana.com": "solana",
    "pump.fun": "solana",
    "birdeye.so": None,
}
REFERRAL_PARAMS = {"ref", "referral", "refcode", "r", "invite", "inviter", "aff", "affiliate", "code"}
REFERRAL_PATH_HINTS = ("/ref/", "/invite/", "/r/", "/referral/", "/join/")
REFERRAL_HOSTS = {"t.me"}  # t.me/<bot>?start=<code> is a referral-style deep link

DISCLOSURE_RE = re.compile(
    r"(#ad\b|#sponsored|\bsponsored\b|\bpaid (promo|promotion|post|partnership)\b|\bpartnered\b|"
    r"\bad\s*[:|]|\bthis is an ad\b|\bpromoted\b)",
    re.IGNORECASE,
)
WARNING_RE = re.compile(r"\b(scam|rug(ged|pull)?|honeypot|avoid|warning|exploit(ed)?|hacked|drained)\b", re.I)
CALL_RE = re.compile(r"\b(buy(ing)?|entry|ape(d)?|gem|100x|1000x|moon(ing)?|send(ing)? it|low ?cap|early)\b", re.I)
ANNOUNCE_RE = re.compile(r"\b(launch(ing|ed)?|presale|whitelist|listing|tge|airdrop|announce(ment|s|d)?)\b", re.I)
NEWS_RE = re.compile(r"\b(report(s|ed)?|according to|breaking)\b", re.I)


@dataclass(frozen=True)
class ContractRef:
    address: str
    chain: str | None  # None when the format fits several chains (EVM) and no URL says which
    via: str  # "url" | "text"


@dataclass
class Extraction:
    contracts: list[ContractRef] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    referral_links: list[str] = field(default_factory=list)
    promo_disclosure: str = "unknown"  # disclosed | unknown  (absence of a tag is NOT proof of no payment)
    category: str = "other"
    content_hash: str = ""


def b58_decoded_len(s: str) -> int | None:
    n = 0
    for ch in s:
        i = B58_ALPHABET.find(ch)
        if i < 0:
            return None
        n = n * 58 + i
    leading = len(s) - len(s.lstrip("1"))
    return leading + (n.bit_length() + 7) // 8


def is_solana_mint(s: str) -> bool:
    return 32 <= len(s) <= 44 and b58_decoded_len(s) == 32


def normalise_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = URL_RE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalise_text(text).encode()).hexdigest()[:32]


def _contracts_from_url(url: str) -> list[ContractRef]:
    try:
        u = urlparse(url)
    except ValueError:
        return []
    host = (u.hostname or "").lower().removeprefix("www.")
    parts = [p for p in u.path.split("/") if p]
    out: list[ContractRef] = []
    chain: str | None = None
    if host == "dexscreener.com" and parts:
        c = BY_DEXSCREENER.get(parts[0])
        chain = c.slug if c else None
    elif host == "geckoterminal.com" and parts:
        c = BY_GECKO.get(parts[0])
        chain = c.slug if c else None
    elif host in EXPLORER_HOSTS:
        chain = EXPLORER_HOSTS[host]
    else:
        return []
    for p in parts:
        if EVM_RE.fullmatch(p) and chain != "solana":
            out.append(ContractRef(p.lower(), chain, "url"))
        elif chain in ("solana", None) and is_solana_mint(p):
            out.append(ContractRef(p, "solana", "url"))
    return out


def _is_referral(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    q = {k.lower() for k in parse_qs(u.query)}
    host = (u.hostname or "").lower()
    if q & REFERRAL_PARAMS:
        return True
    if host in REFERRAL_HOSTS and "start" in q:
        return True
    return any(h in u.path.lower() for h in REFERRAL_PATH_HINTS)


def classify(text: str, has_contract: bool) -> str:
    if WARNING_RE.search(text):
        return "warning"
    if DISCLOSURE_RE.search(text):
        return "promotion"
    if ANNOUNCE_RE.search(text):
        return "announcement"
    if CALL_RE.search(text) and has_contract:
        return "call"
    if NEWS_RE.search(text):
        return "news"
    return "other"


def extract(text: str) -> Extraction:
    text = text or ""
    ex = Extraction(content_hash=content_hash(text))
    seen: dict[str, ContractRef] = {}
    ex.urls = list(dict.fromkeys(u.rstrip(".,;:!?") for u in URL_RE.findall(text)))
    for url in ex.urls:
        for ref in _contracts_from_url(url):
            seen.setdefault(ref.address, ref)
        if _is_referral(url):
            ex.referral_links.append(url)
    stripped = URL_RE.sub(" ", text)
    for m in EVM_RE.findall(stripped):
        seen.setdefault(m.lower(), ContractRef(m.lower(), None, "text"))
    for m in B58_RE.findall(stripped):
        if is_solana_mint(m):
            seen.setdefault(m, ContractRef(m, "solana", "text"))
    ex.contracts = list(seen.values())[:10]
    ex.symbols = list(dict.fromkeys(s.upper() for s in CASHTAG_RE.findall(stripped)))[:10]
    ex.promo_disclosure = "disclosed" if DISCLOSURE_RE.search(text) else "unknown"
    ex.category = classify(text, bool(ex.contracts))
    return ex


def excerpt(text: str, limit: int = 280) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"
