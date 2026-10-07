from __future__ import annotations
import json, logging, os, re, sys, subprocess, platform
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from copy import deepcopy
import random
import time

# --------- Εξαρτήσεις ---------
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None  # type: ignore

try:
    import requests
except ImportError:
    print("Λείπει το 'requests'. Τρέξε: pip install requests", file=sys.stderr)
    raise

try:
    import customtkinter as ctk
    import tkinter as tk
    from tkinter import filedialog, messagebox
except ImportError:
    print("Λείπει το 'customtkinter'. Τρέξε: pip install customtkinter", file=sys.stderr)
    raise
#---------------Google Drive-----------------------#

try:
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
except ImportError:
    GoogleAuth = None
    GoogleDrive = None

# --------- Σταθερές / Ρυθμίσεις ---------
APP_NAME = "FnB Open Orders"
BASE_URLS = [
    ("IMPACT PROD API", "https://einvoiceapi.impact.gr"),
    ("IMPACT DEMO API", "https://einvoiceapiuat.impact.gr"),
    ("IMPACT DEMO PORTAL API", "https://einvoiceportaluat.impact.gr"),
]
OPEN_ENDPOINT = "/FnBDocuments/{issuerVatNumber}/open/"
CLEARANCE_ENDPOINT = "/automationsapi/fnb/clearance"  # endpoint για κλείσιμο δελτίων (clearance)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

try:
    GR_TZ = ZoneInfo("Europe/Athens")
except Exception:
    GR_TZ = None  # type: ignore

LOG_DIR = Path.home() / ".moonhard" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "fnb_open_orders.log"
AFM_FILE = LOG_DIR.parent / "fnb_afm_keys.txt"         # π.χ. C:\Users\...\ .moonhard\fnb_afm_keys.txt
SELECTED_AFMS_FILE = LOG_DIR.parent / "fnb_afm_selected.json"   # για το checklist
COMMENTS_FILE = LOG_DIR.parent / "fnb_comments.json"   # σχόλια ανά MARK
COMPANY_COMMENTS_FILE = LOG_DIR.parent / "fnb_company_comments.json"   # σχόλια ανά εταιρεία/ΑΦΜ
LAYOUT_FILE = LOG_DIR.parent / "fnb_layout.json"   # αποθήκευση layout παραθύρου
PINS_FILE = LOG_DIR.parent / "fnb_pins.json"       # αποθήκευση pinned MARKs
APP_DIR = Path(__file__).resolve().parent

def resource_path(relative_path: str) -> Path:
    """Επιστρέφει σωστό path για κανονικό Python run και για PyInstaller exe."""
    try:
        base_path = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    except Exception:
        base_path = Path(__file__).resolve().parent

    return base_path / relative_path


def executable_dir() -> Path:
    """Επιστρέφει τον πραγματικό φάκελο του exe ή του .py."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent


GOOGLE_CLIENT_SECRETS_FILE = resource_path("client_secrets.json")

GOOGLE_CREDS_DIR = Path.home() / ".moonhard" / "google_drive"
GOOGLE_CREDS_DIR.mkdir(parents=True, exist_ok=True)

GOOGLE_CREDS_FILE = GOOGLE_CREDS_DIR / "mycreds.txt"
# --------- Google Drive Cloud Sync ---------
GOOGLE_DRIVE_FOLDER_ID = "16edPUhz6NZbAi52jfliwYPxD1l6iSpJE"

GDRIVE_CACHE_DIR = LOG_DIR.parent / "gdrive_cache"

GDRIVE_FILES = {
    "afm_keys": {
        "filename": "fnb_afm_keys.txt",
        "cache": GDRIVE_CACHE_DIR / "fnb_afm_keys.txt",
        "local": AFM_FILE,
    },
    "comments": {
        "filename": "fnb_comments.json",
        "cache": GDRIVE_CACHE_DIR / "fnb_comments.json",
        "local": COMMENTS_FILE,
    },
    "company_comments": {
        "filename": "fnb_company_comments.json",
        "cache": GDRIVE_CACHE_DIR / "fnb_company_comments.json",
        "local": COMPANY_COMMENTS_FILE,
    },
    "layout": {
        "filename": "fnb_layout.json",
        "cache": GDRIVE_CACHE_DIR / "fnb_layout.json",
        "local": LAYOUT_FILE,
    },
    "pins": {
        "filename": "fnb_pins.json",
        "cache": GDRIVE_CACHE_DIR / "fnb_pins.json",
        "local": PINS_FILE,
    },
}

# --------- JSON Template για ΕΙΔΙΚΟ ΑΚΥΡΩΤΙΚΟ (Python dict, ΟΧΙ JSON string) ---------
CLOSE_DOC_BASE = {
    "IntegritySignature": "",
    "IAPRSignPolicy": 2,
    "CancelDeliveryOrders": True,
    "CurrencyCode": "EUR",
    "InvoiceType": "ΕΙΔΙΚΟ ΑΚΥΡΩΤΙΚΟ ΣΤΟΙΧΕΙΟ(ΠΑ)",
    "InvoiceTypeCode": "8.6",
    "SpecialInvoiceCategory": 12,
    "VariationType": 0,
    "DocumentType": "ΕΙΔΙΚΟ ΑΚΥΡΩΤΙΚΟ ΣΤΟΙΧΕΙΟ(ΠΑ)",
    "DocumentTypeCode": "INVOICE",
    "IsDeliveryNote": False,
    "Series": "13",
    "Number": "{random}",
    "DateIssued": "{date}",
    "CorrelatedInvoices": [],
    "MultipleConnectedMarks": [],
    "Issuer": {
        "RegisteredName": "{RegisteredName}",
        "BrandName": "{BrandName}",
        "Vat": "EL{CompanyAFM}",
        "TaxOffice": "{CompanyDoy}",
        "Activities": [None],
        "Address": {
            "CountryCode": "GR",
            "City": "{City}",
            "Street": "{Street}",
            "Number": "{Number}",
            "Postal": "{Postal}",
        },
        "Branch": "{Branch}",
        "BranchCode": "{Branch}",
    },
    "AllowancesCharges": [],
    "DistributionDetails": {
        "InternalDocumentId": "AMVtest-13-{random}",
        "MovePurposeCode": 0,
        "DispatchDate": "{date}",
        "Salesman": "SUNSOFT .",
        "DeliveryOriginDetails": {"Address": {}},
        "DeliveryDestinationDetails": {"Address": {}},
    },
    "PaymentDetails": {
        "PaymentMethods": [
            {
                "PaymentMethodType": "ΜΕΤΡΗΤΟΙΣ",
                "PaymentMethodTypeCode": 3,
                "Amount": 0,
                "ApplicationLabel": "AMV",
                "Contactless": False,
                "TipAmount": 0,
            }
        ],
        "ExchangeCurrency": "EUR",
    },
    "AdditionalDetails": {
        "AccountingDepartmentEmails": [],
        "TransmissionMethod": "A",
        "AvoidEmailGrouping": False,
    },
    "Details": [
        {
            "LineNo": 1,
            "Code": "500",
            "Descriptions": ["Γραμμή Ακύρωσης"],
            "MeasurementUnit": "ΜΕΡΙΔΑ",
            "MeasurementUnitCode": 1,
            "Quantity": 1,
            "UnitPrice": 0,
            "NetTotal": 0,
            "Total": 0,
            "VATTotal": 0,
            "VatCategory": "0",
            "VatCategoryCode": 8,
            "FeesPercentCategoryCode": 0,
            "IsInformative": False,
            "IsHidden": False,
            "RecordTypeCode": 0,
            "IncomeClassification": {
                "Id": 0,
                "ClassificationCategoryCode": "category1_95",
                "Amount": 0,
            },
            "OtherMeasurementUnitQuantity": 0,
            "NoVat": False,
        }
    ],
    "Summaries": {
        "TotalNetAmount": 0,
        "TotalVATAmount": 0,
        "TotalOtherTaxesAmount": 0,
        "TotalGrossValue": 0,
        "TotalAllowances": 0,
    },
    "VatAnalysis": [
        {
            "Percentage": 0,
            "VatAmount": 0,
            "UnderlyingValue": 0,
            "VatExemptionCode": 0,
        }
    ],
    "SelfPricing": False,
    "IsDelayed": False,
    "IsDelayedCode": 0,
    "AadeXml": "",
    "TableId": "2",
    "IsRetail": False,
}

# --------- Logging ---------
def setup_logger(level=logging.INFO) -> logging.Logger:
    """Ρύθμιση logger εφαρμογής."""
    lg = logging.getLogger(APP_NAME)
    lg.setLevel(level)
    lg.propagate = False
    if not lg.handlers:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
        fh = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        lg.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        lg.addHandler(ch)
    return lg


LOGGER = setup_logger()

# --------- Ημερομηνίες ---------
class DateUtils:
    """Βοηθητικές συναρτήσεις για ημερομηνίες."""

    @staticmethod
    def parse(d: Optional[str]) -> Optional[date]:
        """Μετατροπή string YYYY-MM-DD σε date, με έλεγχο εγκυρότητας."""
        if not d:
            return None
        if not DATE_RE.match(d):
            raise ValueError("Μη έγκυρη μορφή ημερομηνίας (YYYY-MM-DD).")
        y, m, dd = map(int, d.split("-"))
        return date(y, m, dd)

    @staticmethod
    def defaults() -> Tuple[str, str]:
        """Προεπιλογή (σήμερα, αύριο)."""
        t = date.today()
        return t.isoformat(), (t + timedelta(days=1)).isoformat()

    @staticmethod
    def split_to_48h_chunks(dfrom: date, dto: date) -> List[Tuple[date, date]]:
        """
        Δημιουργεί διαστήματα <= 48h με ΕΠΙΚΑΛΥΨΗ 1 ημέρας
        για να καλύπτεται η λογική της υπηρεσίας.
        """
        chunks: List[Tuple[date, date]] = []
        cur = dfrom
        while cur <= dto:
            end = min(cur + timedelta(days=2), dto)
            chunks.append((cur, end))
            if end == dto:
                break
            cur = end
        return chunks


# --------- API ---------
@dataclass
class ApiConfig:
    """Ρυθμίσεις API client."""

    base_url: str
    api_key: Optional[str] = None
    timeout: int = 30


class ApiClient:
    """Απλός HTTP client (requests.Session)."""

    def __init__(self, cfg: ApiConfig):
        self.cfg = cfg
        self.s = requests.Session()
        self.s.headers.update(
            {"Accept": "application/json", "User-Agent": f"{APP_NAME}/1.0"}
        )
        if cfg.api_key:
            self.s.headers.update({"apiKey": cfg.api_key})

    def _url(self, path: str) -> str:
        """Δημιουργία πλήρους URL από base + path."""
        return self.cfg.base_url.rstrip("/") + path

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """GET με logging."""
        url = self._url(path)
        LOGGER.info("GET %s params=%s", url, params)
        r = self.s.get(url, params=params, timeout=self.cfg.timeout)
        LOGGER.info("HTTP %s %s", r.status_code, r.reason)
        return r


class FnBService:
    """Υπηρεσία για κλήσεις FnBDocuments και clearance."""

    def __init__(self, api: ApiClient):
        # Αποθήκευση API client
        self.api = api

    def retrieve_open_orders_span(
        self, issuer_vat: str, date_from: str, date_to: str
    ) -> List[Dict[str, Any]]:
        """
        Ανάκτηση open orders για μεγάλο εύρος ημερομηνιών με split σε 48h chunks.
        Επιστρέφει flat λίστα εγγράφων.
        """
        dfrom = DateUtils.parse(date_from) if date_from else None
        dto = DateUtils.parse(date_to) if date_to else None
        if not dfrom or not dto:
            df, dt = DateUtils.defaults()
            dfrom, dto = DateUtils.parse(df), DateUtils.parse(dt)  # type: ignore
        if dto < dfrom:
            raise ValueError("Η dateTo είναι πριν από την dateFrom.")

        chunks = DateUtils.split_to_48h_chunks(dfrom, dto)

        all_items: List[Dict[str, Any]] = []
        seen_marks: set = set()

        for a, b in chunks:
            params = {"dateFrom": a.isoformat(), "dateTo": b.isoformat()}
            path = OPEN_ENDPOINT.format(
                issuerVatNumber=(issuer_vat or "EL").strip() or "EL"
            )
            r = self.api.get(path, params=params)
            if r.status_code == 400:
                try:
                    detail = r.json()
                except Exception:
                    detail = r.text
                raise ValueError(f"400 Bad Request (validation): {detail}")
            r.raise_for_status()
            payload = r.json()
            batch = extract_items(payload)
            for it in batch:
                mk = get_mark_safe(it)
                if mk and mk in seen_marks:
                    continue
                if mk:
                    seen_marks.add(mk)
                all_items.append(it)
        return all_items

    def run_clearance(
        self,
        issuer_vat: str,
        date_from: str,
        date_to: str,
        dry_run: bool = False,
    ) -> Any:
        """
        Εκτέλεση κλήσης clearance (/automationsapi/fnb/clearance)
        για συγκεκριμένο issuerTin και εύρος ημερομηνιών.

        Επειδή το API επιτρέπει max 5 ημέρες ανά κλήση,
        σπάμε το διάστημα σε blocks <= 5 ημερών και κάνουμε
        πολλαπλά GET, ενώνοντας τα αποτελέσματα.

        Επιστρέφει ΛΙΣΤΑ με όλα τα blocks (συνενωμένα).
        """
        # Αν δεν δόθηκαν ημερομηνίες, πάμε στα default
        if not date_from or not date_to:
            df, dt = DateUtils.defaults()
            date_from, date_to = df, dt

        # Μετατροπή σε date objects με έλεγχο
        dfrom = DateUtils.parse(date_from)
        dto = DateUtils.parse(date_to)
        if not dfrom or not dto:
            raise ValueError("Μη έγκυρο εύρος ημερομηνιών.")
        if dto < dfrom:
            raise ValueError("Η dateTo είναι πριν από την dateFrom.")

        # issuerTin πρέπει να είναι ELxxxxxxxxx
        tin = issuer_vat.strip()
        if not tin.upper().startswith("EL"):
            tin = "EL" + tin

        # Θα μαζέψουμε όλα τα αποτελέσματα εδώ
        all_results: List[Any] = []

        # Σπάμε σε blocks <= 5 ημερών (inclusive)
        # π.χ. 1-5, 6-10, 11-15, ...
        cur = dfrom
        while cur <= dto:
            chunk_end = min(cur + timedelta(days=4), dto)  # 4 μέρες διαφορά ⇒ 5 ημερολογιακές
            from_str = cur.isoformat()
            to_str = chunk_end.isoformat()

            params = {
                "fromDate": from_str,
                "toDate": to_str,
                "issuerTin": tin,
                "dryRun": "true" if dry_run else "false",
            }

            LOGGER.info(
                "Clearance call for %s | %s → %s (dryRun=%s)",
                tin,
                from_str,
                to_str,
                dry_run,
            )
            r = self.api.get(CLEARANCE_ENDPOINT, params=params)

            if r.status_code == 400:
                try:
                    detail = r.json()
                except Exception:
                    detail = r.text
                # Σημειώνουμε στο log και συνεχίζουμε, ΔΕΝ ρίχνουμε όλη τη διαδικασία
                LOGGER.error("400 Bad Request (clearance) για %s: %s", tin, detail)
                raise ValueError(f"400 Bad Request (clearance validation): {detail}")

            r.raise_for_status()
            payload = r.json()

            # Προσθήκη στο συνολικό αποτέλεσμα
            if isinstance(payload, list):
                all_results.extend(payload)
            else:
                all_results.append(payload)

            # Logging με περιορισμένο μέγεθος
            try:
                truncated = json.dumps(payload, ensure_ascii=False)[:2000]
            except Exception:
                truncated = str(payload)[:2000]
            LOGGER.info(
                "Clearance result chunk %s → %s for %s: %s",
                from_str,
                to_str,
                tin,
                truncated,
            )

            # Επόμενο block: επόμενη μέρα μετά το chunk_end
            cur = chunk_end + timedelta(days=1)

        return all_results

    def run_clearance_with_http_log(
        self,
        issuer_vat: str,
        date_from: str,
        date_to: str,
        dry_run: bool = False,
    ) -> Tuple[List[Any], List[Dict[str, Any]]]:
        """
        Όπως το run_clearance, αλλά επιστρέφει και αναλυτικό log ανά chunk:
        - HTTP status/reason
        - from/to
        - truncated payload για γρήγορη προβολή στο UI
        """
        if not date_from or not date_to:
            df, dt = DateUtils.defaults()
            date_from, date_to = df, dt

        dfrom = DateUtils.parse(date_from)
        dto = DateUtils.parse(date_to)
        if not dfrom or not dto:
            raise ValueError("Μη έγκυρο εύρος ημερομηνιών.")
        if dto < dfrom:
            raise ValueError("Η dateTo είναι πριν από την dateFrom.")

        tin = issuer_vat.strip()
        if not tin.upper().startswith("EL"):
            tin = "EL" + tin

        all_results: List[Any] = []
        http_log: List[Dict[str, Any]] = []

        cur = dfrom
        while cur <= dto:
            chunk_end = min(cur + timedelta(days=4), dto)
            from_str = cur.isoformat()
            to_str = chunk_end.isoformat()

            params = {
                "fromDate": from_str,
                "toDate": to_str,
                "issuerTin": tin,
                "dryRun": "true" if dry_run else "false",
            }

            r = self.api.get(CLEARANCE_ENDPOINT, params=params)

            # Κρατάμε HTTP info για UI
            entry: Dict[str, Any] = {
                "issuerTin": tin,
                "fromDate": from_str,
                "toDate": to_str,
                "httpStatus": r.status_code,
                "httpReason": r.reason,
            }

            if r.status_code == 400:
                try:
                    detail = r.json()
                except Exception:
                    detail = r.text
                entry["error"] = detail
                http_log.append(entry)
                raise ValueError(f"400 Bad Request (clearance validation): {detail}")

            r.raise_for_status()
            payload = r.json()

            if isinstance(payload, list):
                all_results.extend(payload)
            else:
                all_results.append(payload)

            # truncated payload για να γράφει “Clearance result chunk ...”
            try:
                entry["truncated"] = json.dumps(payload, ensure_ascii=False)[:2000]
            except Exception:
                entry["truncated"] = str(payload)[:2000]

            http_log.append(entry)

            cur = chunk_end + timedelta(days=1)

        return all_results, http_log

# --------- Βοηθοί μορφοποίησης ---------
def _flatten(d: Dict[str, Any], parent: str = "", sep: str = ".") -> Dict[str, Any]:
    """Flatten ενός nested dict σε επίπεδο dict με key paths."""
    out: Dict[str, Any] = {}
    for k, v in d.items():
        key = f"{parent}{sep}{k}" if parent else k
        if isinstance(v, dict):
            out.update(_flatten(v, key, sep))
        else:
            out[key] = v
    return out


def get_mark_safe(item: Any) -> Optional[str]:
    """Ασφαλής ανάγνωση πεδίου MARK από διάφορες πιθανές θέσεις."""
    if not isinstance(item, dict):
        return None
    f = _flatten(item)
    return (
        f.get("mark")
        or f.get("MARK")
        or f.get("Mark")
        or f.get("header.mark")
        or f.get("document.mark")
    )


def get_table_id_safe(item: Any) -> Optional[str]:
    """Ασφαλής ανάγνωση πεδίου TableId από διάφορες πιθανές θέσεις."""
    if not isinstance(item, dict):
        return None
    f = _flatten(item)
    value = (
        f.get("TableId")
        or f.get("tableId")
        or f.get("TABLEID")
        or f.get("tableID")
        or f.get("header.TableId")
        or f.get("header.tableId")
        or f.get("document.TableId")
        or f.get("document.tableId")
    )
    return str(value) if value is not None else None



def get_issue_date_safe(item: Any) -> str:
    """Ασφαλής ανάγνωση ημερομηνίας έκδοσης για εμφάνιση/ταξινόμηση."""
    if not isinstance(item, dict):
        return ""
    f = _flatten(item)
    issued = (
        f.get("issueDate")
        or f.get("date")
        or f.get("header.issueDate")
        or f.get("dateIssued")
        or f.get("dateissued")
        or ""
    )
    return str(issued)[:10] if issued else ""


def get_total_safe(item: Any) -> float:
    """Ασφαλής ανάγνωση συνόλου ως αριθμός για ταξινόμηση."""
    if not isinstance(item, dict):
        return 0.0
    f = _flatten(item)
    value = f.get("total") or f.get("amount") or f.get("gross") or 0
    try:
        # Υποστήριξη τιμών τύπου "1.234,56", "1234.56", "€ 1234,56"
        s = str(value).strip().replace("€", "").replace(" ", "")
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        return float(s)
    except Exception:
        return 0.0


def extract_items(data: Any) -> List[Dict[str, Any]]:
    """Επιστροφή list[dict] από payload που μπορεί να έχει διάφορα wrappers."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # ψάχνουμε γνωστά keys
        for key in ("documents", "orders", "results", "items", "data"):
            v = data.get(key)
            if isinstance(v, list):
                return v
    return [data] if isinstance(data, dict) else []


def format_result_lines(
    data: Any,
    afm_label: str = "",
    afm_name: str = "",
    comments: Optional[Dict[str, str]] = None,
    company_comments: Optional[Dict[str, str]] = None,
    pins: Optional[Set[str]] = None,
) -> List[str]:
    """Επιστρέφει περιληπτικές γραμμές (MARK + Ημερομηνία + βασικά) με AFM/Όνομα."""
    items = extract_items(data)
    lines: List[str] = []

    for i, it in enumerate(items, 1):
        f = _flatten(it)
        mark = get_mark_safe(it)
        mark_str = str(mark) if mark is not None else None

        num = f.get("documentNumber") or f.get("docNumber") or f.get("number")
        series = f.get("series") or f.get("docSeries")
        issued = (
            f.get("issueDate")
            or f.get("date")
            or f.get("header.issueDate")
            or f.get("dateIssued")
            or f.get("dateissued")
        )
        buyer_vat = (
            f.get("buyer.vatNumber")
            or f.get("buyer.afm")
            or f.get("counterparty.vatNumber")
        )
        total = f.get("total") or f.get("amount") or f.get("gross")
        status = f.get("status") or f.get("state")
        table_id = get_table_id_safe(it)

        parts: List[str] = []

        # Αν είναι pinned, βάλε ένδειξη 📌
        if pins and mark_str and mark_str in pins:
            parts.append("📌")

        # Αν υπάρχει σχόλιο για το συγκεκριμένο MARK, βάλε εικονίδιο/ένδειξη
        if comments and mark_str and mark_str in comments:
            comment_preview = comments[mark_str]
            if len(comment_preview) > 40:
                comment_preview = comment_preview[:37] + "."
            parts.append(f"💬 {comment_preview}")

        if afm_label or afm_name:
            tag = f"[AFM:{afm_label}" + (f" | Όνομα:{afm_name}]" if afm_name else "]")
            parts.append(tag)

            # Αν υπάρχει σχόλιο για την εταιρεία/ΑΦΜ, το δείχνουμε στη γραμμή αποτελέσματος
            if company_comments and afm_label and str(afm_label) in company_comments:
                company_comment_preview = company_comments[str(afm_label)]
                if len(company_comment_preview) > 40:
                    company_comment_preview = company_comment_preview[:37] + "."
                parts.append(f"🏢💬 {company_comment_preview}")
        if issued:
            parts.append(f"Ημ:{issued}")
        if mark:
            parts.append(f"MARK:{mark}")
        if num:
            parts.append(f"Αρ:{num}")
        if series:
            parts.append(f"Σειρά:{series}")
        if table_id:
            parts.append(f"TableId:{table_id}")
        if buyer_vat:
            parts.append(f"ΑΦΜ:{buyer_vat}")
        if total is not None:
            parts.append(f"Σύνολο:{total}")
        if status:
            parts.append(f"Κατάσταση:{status}")

        line = " | ".join(map(str, parts)) if parts else json.dumps(
            it, ensure_ascii=False
        )
        lines.append(f"{i:>3}. {line}")
    return lines

# --------- Διαχείριση αρχείου ΑΦΜ | apiKey | Όνομα ---------
AFM_FILE_TEMPLATE = (
    "# Μορφή ανά γραμμή:\n"
    "# AFM_OR_ELxxxxxxx | API_KEY | ΟΝΟΜΑ\n"
    "# Το API_KEY και/ή το ΟΝΟΜΑ είναι προαιρετικά.\n"
    "# Παραδείγματα:\n"
    "# EL000000000 | AbCdEf123 | MoonHard Bistro\n"
    "# EL111111111 |  | Demo Client Χωρίς Key\n"
    "# EL222222222 | Zyx987 | \n"
    "# EL333333333 |  | \n"
)


def open_afm_file_in_editor():
    """Ανοίγει/δημιουργεί το txt με ΑΦΜ|apiKey|Όνομα στον προεπιλεγμένο editor."""
    AFM_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not AFM_FILE.exists():
        AFM_FILE.write_text(AFM_FILE_TEMPLATE, encoding="utf-8")
    try:
        if os.name == "nt":
            os.startfile(str(AFM_FILE))  # type: ignore[attr-defined]
        else:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", str(AFM_FILE)])
            else:
                subprocess.Popen(["xdg-open", str(AFM_FILE)])
    except Exception as e:
        messagebox.showerror("Σφάλμα", f"Αδυναμία ανοίγματος αρχείου: {e}")

class GoogleDriveCloudStore:
    """Διαχειρίζεται συγχρονισμό αρχείων TXT/JSON με Google Drive."""

    def __init__(self, folder_id: str):
        """Αρχικοποίηση με το ID του Google Drive φακέλου."""
        self.folder_id = folder_id
        self.drive = None

    def authenticate(self) -> None:
        """Σύνδεση στο Google Drive μέσω PyDrive2 με refresh token."""
        if GoogleAuth is None or GoogleDrive is None:
            raise ImportError("Λείπει το PyDrive2. Τρέξε: pip install PyDrive2")

        if not GOOGLE_CLIENT_SECRETS_FILE.exists():
            exe_folder_file = executable_dir() / "client_secrets.json"

            if exe_folder_file.exists():
                client_secrets_path = exe_folder_file
            else:
                raise FileNotFoundError(
                    "Δεν βρέθηκε το client_secrets.json.\n\n"
                    f"Έψαξα εδώ:\n"
                    f"1) {GOOGLE_CLIENT_SECRETS_FILE}\n"
                    f"2) {exe_folder_file}\n\n"
                    "Βάλε το client_secrets.json δίπλα στο .exe ή κάνε build με --add-data."
                )
        else:
            client_secrets_path = GOOGLE_CLIENT_SECRETS_FILE

        gauth = GoogleAuth()
        gauth.settings["client_config_file"] = str(client_secrets_path)

        # Ζητάμε refresh token για να δουλεύει σε επόμενα ανοίγματα.
        gauth.settings["get_refresh_token"] = True
        gauth.settings["oauth_scope"] = ["https://www.googleapis.com/auth/drive"]

        gauth.LoadCredentialsFile(str(GOOGLE_CREDS_FILE))

        if gauth.credentials is None:
            LOGGER.info("Πρώτη σύνδεση Google Drive. Άνοιγμα browser για login.")
            gauth.LocalWebserverAuth()
        elif gauth.access_token_expired:
            LOGGER.info("Ανανέωση Google Drive token.")
            try:
                gauth.Refresh()
            except Exception as e:
                LOGGER.warning("Το Google token έχει λήξει/ανακληθεί. Γίνεται νέο login: %s", e)

                try:
                    if GOOGLE_CREDS_FILE.exists():
                        GOOGLE_CREDS_FILE.unlink()
                        LOGGER.info("Διαγράφηκε το παλιό mycreds.txt: %s", GOOGLE_CREDS_FILE)
                except Exception as delete_error:
                    LOGGER.exception("Αποτυχία διαγραφής mycreds.txt: %s", delete_error)

                gauth.LocalWebserverAuth()
            try:
                gauth.Refresh()
            except Exception:
                LOGGER.warning("Αποτυχία refresh token. Διαγραφή credentials και νέο login.")
                try:
                    GOOGLE_CREDS_FILE.unlink(missing_ok=True)
                except Exception:
                    pass
                gauth.LocalWebserverAuth()
        else:
            gauth.Authorize()

        gauth.SaveCredentialsFile(str(GOOGLE_CREDS_FILE))
        self.drive = GoogleDrive(gauth)

    def _ensure_drive(self) -> None:
        """Εξασφαλίζει ότι υπάρχει ενεργή σύνδεση με Google Drive."""
        if self.drive is None:
            self.authenticate()

    def find_file(self, filename: str):
        """Βρίσκει αρχείο μέσα στον συγκεκριμένο Google Drive φάκελο."""
        self._ensure_drive()

        query = (
            f"'{self.folder_id}' in parents and "
            f"title = '{filename}' and "
            f"trashed = false"
        )

        files = self.drive.ListFile({"q": query}).GetList()

        if not files:
            return None

        return files[0]

    def download_text(self, filename: str, cache_file: Path) -> str:
        """
        Κατεβάζει αρχείο ως text από Google Drive.
        Αν πετύχει, ενημερώνει και το cache.
        """
        self._ensure_drive()

        cloud_file = self.find_file(filename)

        if cloud_file is None:
            raise FileNotFoundError(f"Δεν βρέθηκε στο Google Drive: {filename}")

        text = cloud_file.GetContentString()

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text, encoding="utf-8")

        LOGGER.info("Κατέβηκε από Google Drive: %s", filename)

        return text

    def upload_text(self, filename: str, text: str, cache_file: Path) -> None:
        """
        Ανεβάζει text στο Google Drive.
        Αν το αρχείο δεν υπάρχει, το δημιουργεί.
        """
        self._ensure_drive()

        cloud_file = self.find_file(filename)

        if cloud_file is None:
            cloud_file = self.drive.CreateFile(
                {
                    "title": filename,
                    "parents": [{"id": self.folder_id}],
                }
            )

        cloud_file.SetContentString(text)
        cloud_file.Upload()

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text, encoding="utf-8")

        LOGGER.info("Ανέβηκε στο Google Drive: %s", filename)
        
def get_gdrive_store() -> GoogleDriveCloudStore:
    """Επιστρέφει αντικείμενο Google Drive store."""
    return GoogleDriveCloudStore(GOOGLE_DRIVE_FOLDER_ID)


def load_cloud_text(file_key: str, default_value: str = "") -> str:
    """
    Φορτώνει text αρχείο.
    Προτεραιότητα:
    1. Google Drive
    2. Cache
    3. Local αρχείο
    4. Default value
    """
    meta = GDRIVE_FILES[file_key]
    cache_path: Path = meta["cache"]
    local_path: Path = meta["local"]

    try:
        store = get_gdrive_store()
        text = store.download_text(meta["filename"], cache_path)

        # Ενημέρωση και του παλιού local αρχείου.
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(text, encoding="utf-8")

        return text

    except Exception as e:
        LOGGER.exception("Αποτυχία φόρτωσης από Google Drive για %s: %s", file_key, e)

    if cache_path.exists():
        LOGGER.warning("Χρήση cache για %s", file_key)
        return cache_path.read_text(encoding="utf-8")

    if local_path.exists():
        LOGGER.warning("Χρήση local αρχείου για %s", file_key)
        return local_path.read_text(encoding="utf-8")

    return default_value


def save_cloud_text(file_key: str, text: str) -> None:
    """
    Αποθηκεύει text αρχείο.
    Γράφει:
    1. Google Drive
    2. Cache
    3. Local αρχείο
    """
    meta = GDRIVE_FILES[file_key]
    cache_path: Path = meta["cache"]
    local_path: Path = meta["local"]

    try:
        store = get_gdrive_store()
        store.upload_text(meta["filename"], text, cache_path)

    except Exception as e:
        LOGGER.exception("Αποτυχία αποθήκευσης στο Google Drive για %s: %s", file_key, e)

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(text, encoding="utf-8")

    except Exception as e:
        LOGGER.exception("Αποτυχία αποθήκευσης cache/local για %s: %s", file_key, e)


def load_cloud_json(file_key: str, default_value: Any) -> Any:
    """
    Φορτώνει JSON αρχείο.
    Προτεραιότητα:
    1. Google Drive
    2. Cache
    3. Local αρχείο
    4. Default value
    """
    text = load_cloud_text(
        file_key=file_key,
        default_value=json.dumps(default_value, ensure_ascii=False, indent=2),
    )

    try:
        return json.loads(text)
    except Exception as e:
        LOGGER.exception("Μη έγκυρο JSON για %s: %s", file_key, e)
        return default_value


def save_cloud_json(file_key: str, data: Any) -> None:
    """Αποθηκεύει JSON αρχείο σε Google Drive/cache/local."""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    save_cloud_text(file_key, text)        

def sync_all_local_files_to_google_drive() -> None:
    """Ανεβάζει όλα τα υπάρχοντα local αρχεία στο Google Drive."""
    try:
        # fnb_afm_keys.txt
        if AFM_FILE.exists():
            save_cloud_text("afm_keys", AFM_FILE.read_text(encoding="utf-8"))
        else:
            save_cloud_text("afm_keys", AFM_FILE_TEMPLATE)

        # fnb_comments.json
        if COMMENTS_FILE.exists():
            data = json.loads(COMMENTS_FILE.read_text(encoding="utf-8"))
            save_cloud_json("comments", data if isinstance(data, dict) else {})
        else:
            save_cloud_json("comments", {})

        # fnb_company_comments.json
        if COMPANY_COMMENTS_FILE.exists():
            data = json.loads(COMPANY_COMMENTS_FILE.read_text(encoding="utf-8"))
            save_cloud_json("company_comments", data if isinstance(data, dict) else {})
        else:
            save_cloud_json("company_comments", {})

        # fnb_layout.json
        if LAYOUT_FILE.exists():
            data = json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
            save_cloud_json("layout", data if isinstance(data, dict) else {})
        else:
            save_cloud_json("layout", {})

        # fnb_pins.json
        if PINS_FILE.exists():
            data = json.loads(PINS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                save_cloud_json("pins", data)
            elif isinstance(data, dict):
                save_cloud_json("pins", list(data.keys()))
            else:
                save_cloud_json("pins", [])
        else:
            save_cloud_json("pins", [])

        LOGGER.info("Ολοκληρώθηκε το upload όλων των local αρχείων στο Google Drive.")

    except Exception as e:
        LOGGER.exception("Αποτυχία sync όλων των αρχείων στο Google Drive: %s", e)

def sync_all_google_drive_files_to_local() -> None:
    """
    Κατεβάζει όλα τα cloud αρχεία από Google Drive
    και τα αποθηκεύει σε cache + local αρχεία.
    """
    try:
        store = get_gdrive_store()

        for file_key, meta in GDRIVE_FILES.items():
            filename = meta["filename"]
            cache_path: Path = meta["cache"]
            local_path: Path = meta["local"]

            LOGGER.info("Download sync από Google Drive: %s", filename)

            text = store.download_text(filename, cache_path)

            # Αποθήκευση και στο παλιό local αρχείο
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(text, encoding="utf-8")

            LOGGER.info("Ολοκληρώθηκε download sync για: %s", filename)

        LOGGER.info("Ολοκληρώθηκε το download sync όλων των αρχείων από Google Drive.")

    except Exception as e:
        LOGGER.exception("Αποτυχία download sync από Google Drive: %s", e)
        raise

def load_afm_key_name_triplets() -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Διαβάζει ΑΦΜ/apiKey/Όνομα από Google Drive/cache/local."""
    text = load_cloud_text("afm_keys", AFM_FILE_TEMPLATE)

    triplets: List[Tuple[str, Optional[str], Optional[str]]] = []

    for raw in text.splitlines():
        line = raw.strip()

        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split("|")]

        afm = parts[0] if len(parts) >= 1 else ""
        key = parts[1] if len(parts) >= 2 and parts[1] != "" else None
        name = parts[2] if len(parts) >= 3 and parts[2] != "" else None

        if afm:
            triplets.append((afm, key, name))

    return triplets


def save_afm_triplets(triplets: List[Tuple[str, Optional[str], Optional[str]]]) -> None:
    """Αποθηκεύει ΟΛΟ το αρχείο AFM σε Google Drive/cache/local."""
    lines = [AFM_FILE_TEMPLATE.rstrip(), ""]

    for afm, key, name in triplets:
        key_str = key or ""
        name_str = name or ""
        lines.append(f"{afm} | {key_str} | {name_str}".rstrip())

    text = "\n".join(lines) + "\n"
    save_cloud_text("afm_keys", text)


def load_selected_afms() -> List[str]:
    """Φορτώνει από JSON τη λίστα με τα επιλεγμένα ΑΦΜ (αν υπάρχει)."""
    try:
        if not SELECTED_AFMS_FILE.exists():
            return []
        data = json.loads(SELECTED_AFMS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(x) for x in data]
        return []
    except Exception as e:
        LOGGER.exception("Αποτυχία φόρτωσης selected AFMs: %s", e)
        return []


def save_selected_afms_list(selected: List[str]) -> None:
    """Αποθηκεύει σε JSON τη λίστα με τα επιλεγμένα ΑΦΜ."""
    try:
        SELECTED_AFMS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # dict.fromkeys για να φύγουν τυχόν duplicates κρατώντας σειρά
        SELECTED_AFMS_FILE.write_text(
            json.dumps(list(dict.fromkeys(selected)), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        LOGGER.exception("Αποτυχία αποθήκευσης selected AFMs: %s", e)

def load_comments() -> Dict[str, str]:
    """Φορτώνει σχόλια ανά MARK από Google Drive/cache/local."""
    data = load_cloud_json("comments", {})

    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}

    return {}

def save_comments(comments: Dict[str, str]) -> None:
    """Αποθηκεύει σχόλια ανά MARK σε Google Drive/cache/local."""
    save_cloud_json("comments", comments)


def load_company_comments() -> Dict[str, str]:
    """Φορτώνει σχόλια εταιρειών ανά ΑΦΜ από Google Drive/cache/local."""
    data = load_cloud_json("company_comments", {})

    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}

    return {}


def save_company_comments(comments: Dict[str, str]) -> None:
    """Αποθηκεύει σχόλια εταιρειών ανά ΑΦΜ σε Google Drive/cache/local."""
    save_cloud_json("company_comments", comments)


def load_layout() -> Dict[str, Any]:
    """Φορτώνει layout από Google Drive/cache/local."""
    data = load_cloud_json("layout", {})

    if isinstance(data, dict):
        return data

    return {}


def save_layout(layout: Dict[str, Any]) -> None:
    """Αποθηκεύει layout σε Google Drive/cache/local."""
    save_cloud_json("layout", layout)


def load_pins() -> Set[str]:
    """Φορτώνει pinned MARKs από Google Drive/cache/local."""
    data = load_cloud_json("pins", [])

    if isinstance(data, list):
        return {str(x) for x in data}

    if isinstance(data, dict):
        return {str(k) for k in data.keys()}

    return set()


def save_pins(pins: Set[str]) -> None:
    """Αποθηκεύει pinned MARKs σε Google Drive/cache/local."""
    save_cloud_json("pins", sorted(pins))

# --------- GUI ---------
class FnBApp(ctk.CTk):
    """Κύρια κλάση GUI εφαρμογής."""

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1180x720")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._last_json: Any = None
        self._last_clearance: Any = None  # αποθήκευση τελευταίου clearance payload
        # Λεξικό για σχόλια ανά MARK (string), φορτωμένο από δίσκο (αν υπάρχει)
        self._comments: Dict[str, str] = load_comments()
        # Λεξικό για σχόλια ανά εταιρεία/ΑΦΜ, φορτωμένο από δίσκο (αν υπάρχει)
        self._company_comments: Dict[str, str] = load_company_comments()
        # Pinned MARKs (set από strings)
        self._pinned_marks: Set[str] = load_pins()
        # Collapsed groups (set από group_id strings)
        self._collapsed_groups: Set[str] = set()
        # ---------- UI State (για layout persistence) ----------
        self.group_mode_var = tk.StringVar(value="AFM")  # AFM | DATE | STATUS | SERIES
        self.sort_mode_var = tk.StringVar(value="Ημ ↓")  # Ημ ↓ | Ημ ↑ | Σύνολο ↓ | Σύνολο ↑
        self.section_var = tk.StringVar(value="open_orders")  # open_orders | clearance | close_docs | logs | settings
        self.sidebar_collapsed_var = tk.BooleanVar(value=False)
        self.show_only_pinned_var = tk.BooleanVar(value=False)
        # Αν είναι ON: δείχνει μόνο ΑΦΜ που έχουν αποτελέσματα (current behavior)
        # Αν είναι OFF: δείχνει και ΑΦΜ που γύρισαν 0 αποτελέσματα
        self.show_only_afm_with_results_var = tk.BooleanVar(value=True)

        self.bind_all("<Control-k>", lambda e: self.on_close_docs())
        self.bind_all("<Control-l>", lambda e: self.on_clearance())
        self.bind_all("<Control-Shift-L>", lambda e: self.on_clearance_preview())
        self.bind_all("<Control-m>", lambda e: self.open_afm_selector())
        self.bind_all("<Control-Shift-l>", lambda e: self.on_clearance_preview())
        self.bind_all("<Control-Alt-a>", lambda e: open_afm_file_in_editor())
        self.bind_all("<Control-Alt-s>", lambda e: self.cycle_sort_mode())

        # Λίστα με επιλεγμένα ΑΦΜ – φορτώνεται από JSON (αν δεν υπάρχει, είναι κενή)
        self.selected_afms: List[str] = load_selected_afms()

        # Layout
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_toolbar()
        self._build_results()
        self._build_status()

        # Shortcuts
        self.bind_all("<Control-Return>", lambda e: self.on_fetch())
        self.bind_all("<F5>", lambda e: self.on_fetch())
        self.bind_all("<Control-s>", lambda e: self.on_save())
        # Collapse / Expand shortcuts
        self.bind_all("<Control-Alt-Down>", lambda e: self.on_collapse_all())
        self.bind_all("<Control-Alt-Up>", lambda e: self.on_expand_all())
        self.bind_all("<Control-c>", lambda e: self.copy_selected_line())
        self.bind_all("<Escape>", lambda e: self.destroy())
        self.bind_all("<Control-f>", lambda e: self.search_entry.focus_set())
        self.search_entry.bind("<Return>", lambda e: self.on_search())
        self.bind_all("<F9>", lambda e: self.on_check_aade_status())

        # Auto AADE status refresh
        self._aade_auto_interval = 10_000
        self._aade_auto_enabled = True
        self.after(1000, self._aade_auto_refresh)
        # Εφαρμογή αποθηκευμένου layout (π.χ. θέση/μέγεθος παραθύρου)
        self._apply_saved_layout()

        # Hook στο κλείσιμο για να αποθηκεύουμε layout
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # --------- Build Sections ---------
    def _build_header(self):
        """Κατασκευή header (2 γραμμές για πιο καθαρό layout)."""
        top = ctk.CTkFrame(self, corner_radius=14)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 4))

        # 2 rows
        top.grid_rowconfigure(0, weight=0)
        top.grid_rowconfigure(1, weight=0)

        # columns (0..11)
        for i in range(0, 12):
            top.grid_columnconfigure(i, weight=0)
        top.grid_columnconfigure(5, weight=0)   # apiKey entry να "απλώνει" ωραία
        top.grid_columnconfigure(10, weight=0)  # spacer πριν το AADE

        self.baseurl = tk.StringVar(value=BASE_URLS[0][1])
        self.vat = tk.StringVar(value="EL")
        dfrom, dto = DateUtils.defaults()
        self.dfrom = tk.StringVar(value=dfrom)
        self.dto = tk.StringVar(value=dto)
        self.apikey = tk.StringVar()

        # --------- Row 0: Base / AFM / apiKey ---------
        ctk.CTkLabel(top, text="Base:").grid(row=0, column=0, padx=(10, 6), pady=(6, 4), sticky="w")
        ctk.CTkComboBox(
            top,
            values=[u for _, u in BASE_URLS],
            variable=self.baseurl,
            width=260,
        ).grid(row=0, column=1, padx=(0, 10), pady=(6, 4), sticky="w")

        ctk.CTkLabel(top, text="ΑΦΜ:").grid(row=0, column=2, padx=(0, 6), pady=(6, 4), sticky="w")
        ctk.CTkEntry(top, textvariable=self.vat, width=140).grid(
            row=0, column=3, padx=(0, 10), pady=(6, 4), sticky="w"
        )

        ctk.CTkLabel(top, text="apiKey:").grid(row=0, column=4, padx=(0, 6), pady=(6, 4), sticky="w")
        ctk.CTkEntry(top, textvariable=self.apikey, width=380).grid(
            row=0, column=5, padx=(0, 10), pady=(6, 4), sticky="ew"
        )

        # --------- Row 1: Dates / Presets / Fetch / AADE ---------
        ctk.CTkLabel(top, text="Από:").grid(row=1, column=0, padx=(10, 6), pady=(0, 6), sticky="w")
        ctk.CTkEntry(top, textvariable=self.dfrom, width=120).grid(
            row=1, column=1, padx=(0, 10), pady=(0, 6), sticky="w"
        )

        ctk.CTkLabel(top, text="Έως:").grid(row=1, column=2, padx=(0, 6), pady=(0, 6), sticky="w")
        ctk.CTkEntry(top, textvariable=self.dto, width=120).grid(
            row=1, column=3, padx=(0, 10), pady=(0, 6), sticky="w"
        )

        self.preset_var = tk.StringVar(value="")
        self.preset_seg = ctk.CTkSegmentedButton(
            top,
            values=["Σήμερα", "Χτες", "7ημ", "Μήνας"],
            variable=self.preset_var,
            command=self.on_preset_segment,
        )
        self.preset_seg.grid(row=1, column=4, padx=(0, 10), pady=(0, 6), sticky="w")

        ctk.CTkButton(
            top, text="Ανάκτηση (Ctrl+Enter)", width=170, command=self.on_fetch
        ).grid(row=0, column=6, padx=(0, 10), pady=(0, 6), sticky="w")

        # AADE box (δεξιά)
        aade_box = ctk.CTkFrame(top, corner_radius=12)
        aade_box.grid(row=0, column=11, sticky="e", padx=(0, 10), pady=(0, 6))

        self.aade_light = ctk.CTkLabel(aade_box, text="●", width=10)
        self.aade_light.configure(text_color="#9CA3AF")
        self.aade_light.pack(side="left", padx=(10, 6), pady=6)

        self.aade_text = ctk.CTkLabel(aade_box, text="AADE: άγνωστο", anchor="w")
        self.aade_text.pack(side="left", padx=(0, 8), pady=6)

        self.aade_rtt = ctk.CTkLabel(aade_box, text="— ms", anchor="w")
        self.aade_rtt.pack(side="left", padx=(0, 10), pady=6)

        self.aade_btn = ctk.CTkButton(aade_box, text="🔄", width=36, command=self.on_check_aade_status)
        self.aade_btn.pack(side="left", padx=(0, 8), pady=6)

        self.aade_auto_switch = ctk.CTkSwitch(aade_box, text="Auto", command=self.on_toggle_aade_auto)
        self.aade_auto_switch.pack(side="left", padx=(0, 10), pady=6)
        self.aade_auto_switch.select()

    def _build_toolbar(self):
        """Toolbar 2 γραμμών: Actions επάνω, Search/Grouping κάτω."""
        bar = ctk.CTkFrame(self, corner_radius=14)
        bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        bar.grid_columnconfigure(0, weight=1)

        # 2 rows
        bar.grid_rowconfigure(0, weight=0)
        bar.grid_rowconfigure(1, weight=0)

        # ---------- Row 0 ----------
        row0 = ctk.CTkFrame(bar, fg_color="transparent")
        row0.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 4))
        row0.grid_columnconfigure(0, weight=1)  # left actions
        row0.grid_columnconfigure(1, weight=0)  # right utilities

        left0 = ctk.CTkFrame(row0, fg_color="transparent")
        left0.grid(row=0, column=0, sticky="w")

        right0 = ctk.CTkFrame(row0, fg_color="transparent")
        right0.grid(row=0, column=1, sticky="e")

        # Actions (αριστερά)
        self.close_btn = ctk.CTkButton(
            left0, text="Ακύρωση Δελτίων (Ctrl+K)", width=170, command=self.on_close_docs
        )
        self.close_btn.pack(side="left", padx=(0, 8), pady=0)

        self.clearance_btn = ctk.CTkButton(
            left0, text="Κλείσιμο Δελτίων (Ctrl+L)", width=170, command=self.on_clearance
        )
        self.clearance_btn.pack(side="left", padx=(0, 8), pady=0)

        self.clearance_preview_btn = ctk.CTkButton(
            left0, text="Preview Clearance (Ctrl+Shift+L)", width=210, command=self.on_clearance_preview
        )
        self.clearance_preview_btn.pack(side="left", padx=(0, 8), pady=0)

        self.afm_select_btn = ctk.CTkButton(
            left0, text="Επιλογή ΑΦΜ (Ctrl+M)", width=160, command=self.open_afm_selector
        )
        self.afm_select_btn.pack(side="left", padx=(0, 8), pady=0)

        self.afm_list_btn = ctk.CTkButton(
            left0,
            text="Λίστα ΑΦΜ/Keys/Ονόματα (Ctrl+Alt+A)",
            width=260,
            command=open_afm_file_in_editor,
        )
        self.afm_list_btn.pack(side="left", padx=(0, 8), pady=0)

        # Utilities (δεξιά)
        self.copy_btn = ctk.CTkButton(
            right0, text="Αντιγραφή (Ctrl+C)", width=170, command=self.copy_selected_line
        )
        self.copy_btn.pack(side="right", padx=(8, 0), pady=0)

        self.save_btn = ctk.CTkButton(
            right0, text="Αποθήκευση JSON (Ctrl+S)", width=200, command=self.on_save
        )
        self.save_btn.pack(side="right", padx=(8, 0), pady=0)

        self.upload_cloud_btn = ctk.CTkButton(
            right0,
            text="☁ Upload Cloud",
            width=140,
            command=self.on_upload_cloud,
        )
        self.upload_cloud_btn.pack(side="right", padx=(8, 0), pady=0)

        self.download_cloud_btn = ctk.CTkButton(
            right0,
            text="☁ Download Cloud",
            width=160,
            command=self.on_download_cloud,
        )
        self.download_cloud_btn.pack(side="right", padx=(8, 0), pady=0)
        # ---------- Row 1 ----------
        row1 = ctk.CTkFrame(bar, fg_color="transparent")
        row1.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        row1.grid_columnconfigure(0, weight=1)  # search + grouping left
        row1.grid_columnconfigure(1, weight=0)  # collapse/expand right

        left1 = ctk.CTkFrame(row1, fg_color="transparent")
        left1.grid(row=0, column=0, sticky="w")

        right1 = ctk.CTkFrame(row1, fg_color="transparent")
        right1.grid(row=0, column=1, sticky="e")

        # Search
        self.search_var = tk.StringVar()
        self.search_entry = ctk.CTkEntry(
            left1,
            placeholder_text="Αναζήτηση με ΑΦΜ ή Όνομα (Enter)",
            textvariable=self.search_var,
            width=340,
        )
        self.search_entry.pack(side="left", padx=(0, 8), pady=0)

        self.search_btn = ctk.CTkButton(left1, text="Αναζήτηση", width=120, command=self.on_search)
        self.search_btn.pack(side="left", padx=(0, 8), pady=0)

        self.clear_btn = ctk.CTkButton(left1, text="Καθαρισμός", width=120, command=self.on_clear_search)
        self.clear_btn.pack(side="left", padx=(0, 14), pady=0)

        # Grouping
        ctk.CTkLabel(left1, text="Group:", anchor="w").pack(side="left", padx=(0, 8))
        self.group_seg = ctk.CTkSegmentedButton(
            left1,
            values=["AFM", "DATE", "STATUS", "SERIES", "TABLEID"],
            variable=self.group_mode_var,
            command=self.on_group_mode_changed,
        )
        self.group_seg.pack(side="left", padx=(0, 12), pady=0)

        # Ταξινόμηση αποτελεσμάτων ανεξάρτητα από το grouping
        ctk.CTkLabel(left1, text="Sort:", anchor="w").pack(side="left", padx=(0, 8))
        self.sort_seg = ctk.CTkSegmentedButton(
            left1,
            values=["Ημ ↓", "Ημ ↑", "Σύνολο ↓", "Σύνολο ↑"],
            variable=self.sort_mode_var,
            command=self.on_sort_mode_changed,
        )
        self.sort_seg.pack(side="left", padx=(0, 12), pady=0)

        self.only_pinned_switch = ctk.CTkSwitch(
            left1,
            text="Μόνο 📌",
            variable=self.show_only_pinned_var,
            command=self.on_only_pinned_changed,
        )
        self.only_pinned_switch.pack(side="left", padx=(0, 12), pady=0)

        self.only_results_switch = ctk.CTkSwitch(
            left1,
            text="Μόνο ΑΦΜ με αποτελέσματα",
            variable=self.show_only_afm_with_results_var,
            command=self.on_only_afm_with_results_changed,
        )
        self.only_results_switch.pack(side="left", padx=(0, 0), pady=0)

        # Collapse / Expand (δεξιά)
        self.collapse_all_btn = ctk.CTkButton(
            right1, text="▾ Collapse (Ctrl+Alt+↓)", width=170, command=self.on_collapse_all
        )
        self.collapse_all_btn.pack(side="left", padx=(0, 8), pady=0)

        self.expand_all_btn = ctk.CTkButton(
            right1, text="▸ Expand (Ctrl+Alt+↑)", width=170, command=self.on_expand_all
        )
        self.expand_all_btn.pack(side="left", padx=(0, 0), pady=0)

    def _build_results(self):
        """Κατασκευή περιοχής αποτελεσμάτων (Listbox + scrollbar + context menu)."""
        center = ctk.CTkFrame(self, corner_radius=14)
        center.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 6))
        center.grid_rowconfigure(0, weight=1)
        center.grid_columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(
            center,
            activestyle="dotbox",
            selectmode="extended",
            bg="#0f172a",
            fg="#e5e7eb",
            highlightthickness=0,
            relief="flat",
            font=("Cascadia Mono", 11),
        )
        self.listbox.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)

        sb = ctk.CTkScrollbar(center, orientation="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        self.listbox.configure(yscrollcommand=sb.set)

        self.setup_context_menu()
        # Double click σε header/γραμμές group για collapse/expand
        self.listbox.bind("<Double-Button-1>", self.on_listbox_double_click)

    def _build_status(self):
        """Κατασκευή status bar."""
        self.status = ctk.CTkLabel(self, text="Έτοιμο.", anchor="w")
        self.status.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 6))

    def on_listbox_double_click(self, event):
        """Collapse/Expand group με διπλό κλικ (σε header ή σε οποιαδήποτε γραμμή του group)."""
        try:
            idx = self.listbox.nearest(event.y)
        except Exception:
            return "break"

        # Helper: αναγνώριση header γραμμής
        header_re = re.compile(r"^=+\s+\[(\+|\-)\]\s+(.+?)\s+=+$")

        # 1) Ψάξε ΠΑΝΩ από το σημείο click μέχρι να βρεις header
        header_idx = None
        header_line = None
        for i in range(idx, -1, -1):
            line = (self.listbox.get(i) or "").strip()
            if not line:
                continue
            if header_re.match(line):
                header_idx = i
                header_line = line
                break

            # Αν βρούμε άλλο group separator τύπου "=====" χωρίς [+/-], σταμάτα (ασφάλεια)
            if line.startswith("=====") and "[+" not in line and "[-" not in line:
                break

        if header_idx is None or not header_line:
            return "break"

        m = header_re.match(header_line)
        if not m:
            return "break"

        # Group id = αυτό που γράφει ο header, χωρίς το "| Σύνολο: ..."
        group_id = m.group(2).split(" | Σύνολο:", 1)[0].strip()

        if group_id in self._collapsed_groups:
            self._collapsed_groups.remove(group_id)
            LOGGER.info("Expanded group: %s", group_id)
        else:
            self._collapsed_groups.add(group_id)
            LOGGER.info("Collapsed group: %s", group_id)

        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())

        return "break"

    def on_upload_cloud(self):
        """Χειροκίνητο upload όλων των local αρχείων στο Google Drive."""
        try:
            self.status.configure(text="Upload cloud sync...")
            self.update_idletasks()

            sync_all_local_files_to_google_drive()

            self.status.configure(text="Ολοκληρώθηκε το upload cloud sync.")
            messagebox.showinfo(
                "Upload Cloud Sync",
                "Ανέβηκαν όλα τα local αρχεία στο Google Drive.",
            )

        except Exception as e:
            LOGGER.exception("Αποτυχία upload cloud sync: %s", e)
            self.status.configure(text="Σφάλμα upload cloud sync.")
            messagebox.showerror("Upload Cloud Sync", str(e))


    def on_download_cloud(self):
        """
        Χειροκίνητο download όλων των αρχείων από Google Drive
        και επαναφόρτωση των βασικών δεδομένων στο πρόγραμμα.
        """
        try:
            if not messagebox.askyesno(
                "Download Cloud Sync",
                "Θέλεις να κατεβάσεις τα αρχεία από Google Drive;\n\n"
                "Προσοχή: Θα αντικατασταθούν τα local αρχεία με τα cloud αρχεία.",
            ):
                return

            self.status.configure(text="Download cloud sync...")
            self.update_idletasks()

            sync_all_google_drive_files_to_local()

            # Επαναφόρτωση δεδομένων στη μνήμη του προγράμματος
            self._comments = load_comments()
            self._company_comments = load_company_comments()
            self._pinned_marks = load_pins()

            # Επανασχεδίαση αποτελεσμάτων αν υπάρχουν ήδη δεδομένα
            if self._last_json is not None:
                self._render_list(self._last_json, self.search_var.get())

            self.status.configure(text="Ολοκληρώθηκε το download cloud sync.")
            messagebox.showinfo(
                "Download Cloud Sync",
                "Κατέβηκαν όλα τα cloud αρχεία και ενημερώθηκε το πρόγραμμα.",
            )

        except Exception as e:
            LOGGER.exception("Αποτυχία download cloud sync: %s", e)
            self.status.configure(text="Σφάλμα download cloud sync.")
            messagebox.showerror("Download Cloud Sync", str(e))

    def on_sync_cloud(self):
        """Χειροκίνητο upload όλων των local αρχείων στο Google Drive."""
        try:
            self.status.configure(text="Cloud sync...")
            self.update_idletasks()

            sync_all_local_files_to_google_drive()

            self.status.configure(text="Ολοκληρώθηκε το cloud sync.")
            messagebox.showinfo("Cloud Sync", "Ανέβηκαν όλα τα αρχεία στο Google Drive.")

        except Exception as e:
            LOGGER.exception("Αποτυχία cloud sync: %s", e)
            self.status.configure(text="Σφάλμα cloud sync.")
            messagebox.showerror("Cloud Sync", str(e))

    def on_collapse_all(self):
        """Κάνει collapse όλα τα groups."""
        header_re = re.compile(r"^=+\s+\[(\+|\-)\]\s+(.+?)\s+=+$")
        self._collapsed_groups.clear()

        for i in range(self.listbox.size()):
            line = (self.listbox.get(i) or "").strip()
            m = header_re.match(line)
            if not m:
                continue
            group_id = m.group(2).split(" | Σύνολο:", 1)[0].strip()
            if group_id:
                self._collapsed_groups.add(group_id)

        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())
        self.status.configure(text="Collapse σε όλα τα groups.")

    def on_expand_all(self):
        """Κάνει expand όλα τα groups."""
        self._collapsed_groups.clear()
        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())
        self.status.configure(text="Expand σε όλα τα groups.")

    # --------- Βοηθητικό: επίλυση AFM triplets ---------
    def _resolve_afm_triplets(
        self, vat_input: str, default_key: Optional[str]
    ) -> List[Tuple[str, Optional[str], Optional[str]]]:
        """
        Υπολογίζει τη λίστα (afm, key, name) που θα χρησιμοποιηθεί
        τόσο για Ανάκτηση όσο και για Clearance.
        """
        vat_input = (vat_input or "").strip()

        # Αν το GUI έχει συγκεκριμένο ΑΦΜ, χρησιμοποιούμε μόνο αυτό
        if (vat_input and vat_input.upper() != "EL") or (
            default_key is not None and vat_input
        ):
            return [(vat_input or "EL", default_key, None)]

        # Αλλιώς διαβάζουμε από το αρχείο
        base_triplets = load_afm_key_name_triplets()

        # Φιλτράρισμα με βάση το AFM selector, αν υπάρχουν επιλεγμένα
        if self.selected_afms:
            allowed = set(self.selected_afms)
            base_triplets = [t for t in base_triplets if t[0] in allowed]

        if not base_triplets:
            return [(vat_input or "EL", default_key, None)]

        return base_triplets

    def add_comment_for_selection(self):
        """
        Προσθήκη ή επεξεργασία σχολίου για τη γραμμή.
        Βασίζεται στο MARK της γραμμής.
        """
        sel = self.listbox.curselection()
        if not sel:
            return

        text = self.listbox.get(sel[0])
        match = re.search(r"MARK:([A-Za-z0-9\-]+)", text)
        if not match:
            messagebox.showinfo(
                "Σχόλιο",
                "Δεν βρέθηκε MARK σε αυτή τη γραμμή.\nΣχόλιο υποστηρίζεται μόνο σε γραμμές παραστατικών.",
            )
            return

        mark_value = match.group(1)
        current_comment = self._comments.get(mark_value, "")

        new_comment = self._prompt_comment(
            "Σχόλιο για γραμμή",
            f"MARK: {mark_value}\nΔώσε σχόλιο (άφησέ το κενό για διαγραφή):",
            initial=current_comment,
        )
        if new_comment is None:
            # Πάτησε Άκυρο
            return

        if new_comment == "":
            # Κενό => διαγραφή σχολίου
            if mark_value in self._comments:
                self._comments.pop(mark_value, None)
                save_comments(self._comments)             
                LOGGER.info("Διαγράφηκε σχόλιο για MARK %s", mark_value)
                self.status.configure(text=f"Διαγράφηκε σχόλιο για MARK {mark_value}.")
        else:
            self._comments[mark_value] = new_comment
            LOGGER.info("Ορίστηκε σχόλιο για MARK %s: %s", mark_value, new_comment)
            self.status.configure(text=f"Ορίστηκε σχόλιο για MARK {mark_value}.")
            # Αποθήκευση σχολίων σε δίσκο
            save_comments(self._comments)

        # Ανασχεδίαση λίστας ώστε να φανεί/κρυφτεί το 💬
        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())

    def delete_comment_for_selection(self):
        """Διαγράφει το σχόλιο για το MARK της επιλεγμένης γραμμής, αν υπάρχει."""
        sel = self.listbox.curselection()
        if not sel:
            return

        text = self.listbox.get(sel[0])
        match = re.search(r"MARK:([A-Za-z0-9\-]+)", text)
        if not match:
            self.status.configure(text="Δεν βρέθηκε MARK σε αυτή τη γραμμή.")
            return

        mark_value = match.group(1)
        if mark_value not in self._comments:
            self.status.configure(text=f"Δεν υπάρχει σχόλιο για MARK {mark_value}.")
            return

        if not messagebox.askyesno(
            "Διαγραφή Σχολίου",
            f"Θέλεις σίγουρα να διαγράψεις το σχόλιο για MARK {mark_value};",
        ):
            return

        self._comments.pop(mark_value, None)
        LOGGER.info("Διαγράφηκε σχόλιο για MARK %s", mark_value)
        self.status.configure(text=f"Διαγράφηκε σχόλιο για MARK {mark_value}.")
        # Αποθήκευση σχολίων σε δίσκο μετά τη διαγραφή
        save_comments(self._comments)

        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())


    def _extract_afm_from_text_line(self, text: str) -> Optional[str]:
        """Εξάγει ΑΦΜ εταιρείας από γραμμή αποτελέσματος ή group header."""
        patterns = [
            r"\[AFM:([A-Za-z0-9]+)",
            r"^=+\s+\[[+\-]\]\s+AFM:([A-Za-z0-9]+)",
            r"ΑΦΜ:\s*([A-Za-z0-9]+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                return m.group(1).strip()
        return None

    def _extract_company_name_from_text_line(self, text: str) -> str:
        """Εξάγει όνομα εταιρείας από γραμμή αποτελέσματος ή group header, όπου υπάρχει."""
        m = re.search(r"Όνομα:([^\]]+)", text)
        if m:
            return m.group(1).strip()

        # Header τύπου: ===== [-] AFM:EL123 | Company Name | Σύνολο: 5 =====
        m = re.search(r"AFM:[A-Za-z0-9]+\s+\|\s+(.+?)\s+\|\s+Σύνολο:", text)
        if m:
            return m.group(1).strip()

        # Empty AFM line τύπου: EL123 | Company Name | 0 αποτελέσματα
        m = re.search(r"^[A-Za-z0-9]+\s+\|\s+(.+?)\s+\|\s+0 αποτελέσματα", text)
        if m:
            return m.group(1).strip()

        return ""

    def add_company_comment_for_selection(self):
        """Προσθήκη ή επεξεργασία μόνιμου σχολίου για εταιρεία/ΑΦΜ."""
        sel = self.listbox.curselection()
        if not sel:
            return

        text = self.listbox.get(sel[0]) or ""
        afm_value = self._extract_afm_from_text_line(text)
        if not afm_value:
            messagebox.showinfo(
                "Σχόλιο εταιρείας",
                "Δεν βρέθηκε ΑΦΜ εταιρείας σε αυτή τη γραμμή.",
            )
            return

        company_name = self._extract_company_name_from_text_line(text)
        current_comment = self._company_comments.get(afm_value, "")

        title_name = f" | {company_name}" if company_name else ""
        new_comment = self._prompt_comment(
            "Σχόλιο για εταιρεία",
            f"ΑΦΜ: {afm_value}{title_name}\nΔώσε σχόλιο εταιρείας (άφησέ το κενό για διαγραφή):",
            initial=current_comment,
        )
        if new_comment is None:
            return

        if new_comment == "":
            if afm_value in self._company_comments:
                self._company_comments.pop(afm_value, None)
                save_company_comments(self._company_comments)
                LOGGER.info("Διαγράφηκε σχόλιο εταιρείας για ΑΦΜ %s", afm_value)
                self.status.configure(text=f"Διαγράφηκε σχόλιο εταιρείας για ΑΦΜ {afm_value}.")
        else:
            self._company_comments[afm_value] = new_comment
            save_company_comments(self._company_comments)
            LOGGER.info("Ορίστηκε σχόλιο εταιρείας για ΑΦΜ %s: %s", afm_value, new_comment)
            self.status.configure(text=f"Ορίστηκε σχόλιο εταιρείας για ΑΦΜ {afm_value}.")

        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())

    def delete_company_comment_for_selection(self):
        """Διαγράφει το μόνιμο σχόλιο εταιρείας/ΑΦΜ της επιλεγμένης γραμμής."""
        sel = self.listbox.curselection()
        if not sel:
            return

        text = self.listbox.get(sel[0]) or ""
        afm_value = self._extract_afm_from_text_line(text)
        if not afm_value:
            self.status.configure(text="Δεν βρέθηκε ΑΦΜ εταιρείας σε αυτή τη γραμμή.")
            return

        if afm_value not in self._company_comments:
            self.status.configure(text=f"Δεν υπάρχει σχόλιο εταιρείας για ΑΦΜ {afm_value}.")
            return

        if not messagebox.askyesno(
            "Διαγραφή σχολίου εταιρείας",
            f"Θέλεις σίγουρα να διαγράψεις το σχόλιο εταιρείας για ΑΦΜ {afm_value};",
        ):
            return

        self._company_comments.pop(afm_value, None)
        save_company_comments(self._company_comments)
        LOGGER.info("Διαγράφηκε σχόλιο εταιρείας για ΑΦΜ %s", afm_value)
        self.status.configure(text=f"Διαγράφηκε σχόλιο εταιρείας για ΑΦΜ {afm_value}.")

        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())

    # --------- Πυρήνας λειτουργιών ---------
    def on_fetch(self):
        """Ανάκτηση για πολλά ΑΦΜ ή για ένα (από GUI), με άθροιση σε 48h chunks."""
        base_url = self.baseurl.get().strip()
        dfrom = self.dfrom.get().strip()
        dto = self.dto.get().strip()
        default_key = (self.apikey.get() or "").strip() or None

        # Έλεγχος ημερομηνιών
        try:
            _df = DateUtils.parse(dfrom) if dfrom else None
            _dt = DateUtils.parse(dto) if _df and dto else None
            if _df and _dt and _dt < _df:
                raise ValueError("Η dateTo είναι πριν από την dateFrom.")
        except Exception as e:
            messagebox.showerror("Σφάλμα Ημερομηνιών", str(e))
            return

        vat_input = (self.vat.get() or "").strip()
        triplets = self._resolve_afm_triplets(vat_input, default_key)

        self.status.configure(text="Ανάκτηση...")
        t0 = time.perf_counter()
        self.update_idletasks()
        self.listbox.delete(0, tk.END)

        all_collected: Dict[str, Dict[str, Any]] = {}

        try:
            for afm, key, name in triplets:
                cfg = ApiConfig(base_url=base_url, api_key=(key or default_key))
                svc = FnBService(ApiClient(cfg))
                batch = svc.retrieve_open_orders_span(afm, dfrom, dto)
                all_collected[afm] = {"name": name, "items": batch}
        except Exception as e:
            LOGGER.exception("Αποτυχία: %s", e)
            messagebox.showerror("Σφάλμα", str(e))
            self.status.configure(text="Σφάλμα.")
            dt = time.perf_counter() - t0
            self.status.configure(text=f"Σφάλμα μετά από {dt:.2f}s.")
            return

        self._last_json = all_collected
        self._render_list(self._last_json, self.search_var.get())
        dt = time.perf_counter() - t0
        self.status.configure(text=f"Ολοκληρώθηκε σε {dt:.2f}s.")

    def on_save(self):
        """Αποθήκευση τελευταίου JSON αποτελέσματος σε αρχείο."""
        if self._last_json is None:
            messagebox.showinfo(
                "Αποθήκευση", "Δεν υπάρχουν δεδομένα για αποθήκευση."
            )
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialfile="fnb_open_orders.json",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._last_json, f, ensure_ascii=False, indent=2)
            LOGGER.info("Αποθήκευση JSON: %s", path)
            messagebox.showinfo("Αποθήκευση", f"Αποθηκεύτηκε: {path}")
        except Exception as e:
            LOGGER.exception("Αποτυχία αποθήκευσης: %s", e)
            messagebox.showerror("Σφάλμα", str(e))

    def copy_selected_line(self):
        """Αντιγραφή επιλεγμένων γραμμών από το Listbox στο clipboard."""
        sel = self.listbox.curselection()
        if not sel:
            return
        text = "\n".join(self.listbox.get(i) for i in sel)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.configure(text=f"Αντιγράφηκαν {len(sel)} γραμμές.")

    # --------- Context Menu / MARK ---------
    def setup_context_menu(self):
        """Δημιουργεί context menu για MARK, JSON, ΑΦΜ, Σχόλιο και Pin."""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="📋 Αντιγραφή MARK", command=self.copy_mark_from_selection
        )
        self.context_menu.add_command(
            label="📋 Αντιγραφή ΑΦΜ", command=self.copy_afm_from_selection
        )
        self.context_menu.add_command(
            label="👁 Προβολή JSON", command=self.show_json_for_selection
        )
        self.context_menu.add_command(
            label="📧 Αντιγραφή για Support", command=self.copy_support_message_from_selection
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="📌 Pin / Unpin MARK", command=self.toggle_pin_for_selection
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="💬 Προσθήκη / Επεξεργασία Σχολίου Παραστατικού",
            command=self.add_comment_for_selection,
        )
        self.context_menu.add_command(
            label="🗑 Διαγραφή Σχολίου Παραστατικού",
            command=self.delete_comment_for_selection,
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="🏢💬 Προσθήκη / Επεξεργασία Σχολίου Εταιρείας",
            command=self.add_company_comment_for_selection,
        )
        self.context_menu.add_command(
            label="🏢🗑 Διαγραφή Σχολίου Εταιρείας",
            command=self.delete_company_comment_for_selection,
        )
        self.listbox.bind("<Button-3>", self.show_context_menu)

    def show_context_menu(self, event):
        """Εμφάνιση context menu στη θέση του δεξιού κλικ."""
        try:
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(self.listbox.nearest(event.y))
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def copy_mark_from_selection(self):
        """Αντιγράφει το MARK:xxxxxx από την επιλεγμένη γραμμή."""
        sel = self.listbox.curselection()
        if not sel:
            return
        text = self.listbox.get(sel[0])
        match = re.search(r"MARK:([A-Za-z0-9\-]+)", text)
        if match:
            mark_value = match.group(1)
            self.clipboard_clear()
            self.clipboard_append(mark_value)
            self.status.configure(text=f"Αντιγράφηκε MARK: {mark_value}")
        else:
            self.status.configure(text="Δεν βρέθηκε MARK σε αυτή τη γραμμή.")

    def _parse_fields_from_line(self, text: str) -> Dict[str, str]:
        """Εξαγωγή βασικών πεδίων από γραμμή listbox."""
        out: Dict[str, str] = {}

        m = re.search(r"\[AFM:([A-Za-z0-9]+)", text)
        if m:
            out["AFM"] = m.group(1)

        m = re.search(r"Όνομα:([^\]]+)", text)
        if m:
            out["Όνομα"] = m.group(1).strip()

        m = re.search(r"MARK:([A-Za-z0-9\-]+)", text)
        if m:
            out["MARK"] = m.group(1)

        m = re.search(r"Ημ:([^|]+)", text)
        if m:
            out["Ημερομηνία"] = m.group(1).strip()

        m = re.search(r"Σύνολο:([^|]+)", text)
        if m:
            out["Σύνολο"] = m.group(1).strip()

        m = re.search(r"Κατάσταση:([^|]+)", text)
        if m:
            out["Κατάσταση"] = m.group(1).strip()

        m = re.search(r"Σειρά:([^|]+)", text)
        if m:
            out["Σειρά"] = m.group(1).strip()

        m = re.search(r"TableId:([^|]+)", text)
        if m:
            out["TableId"] = m.group(1).strip()

        m = re.search(r"Αρ:([^|]+)", text)
        if m:
            out["Αριθμός"] = m.group(1).strip()

        return out

    def copy_support_message_from_selection(self):
        """Φτιάχνει έτοιμο μήνυμα για support από την επιλεγμένη γραμμή."""
        sel = self.listbox.curselection()
        if not sel:
            return

        text = self.listbox.get(sel[0]) or ""
        fields = self._parse_fields_from_line(text)

        if "MARK" not in fields and "AFM" not in fields:
            self.status.configure(text="Η επιλογή δεν είναι γραμμή παραστατικού.")
            return

        lines = []
        lines.append("OpenDeltia – Στοιχεία παραστατικού")
        if fields.get("AFM"): lines.append(f"AFM: {fields['AFM']}")
        if fields.get("Όνομα"): lines.append(f"Όνομα: {fields['Όνομα']}")
        if fields.get("MARK"): lines.append(f"MARK: {fields['MARK']}")
        if fields.get("Ημερομηνία"): lines.append(f"Ημερομηνία: {fields['Ημερομηνία']}")
        if fields.get("Αριθμός"): lines.append(f"Αριθμός: {fields['Αριθμός']}")
        if fields.get("Σειρά"): lines.append(f"Σειρά: {fields['Σειρά']}")
        if fields.get("TableId"): lines.append(f"TableId: {fields['TableId']}")
        if fields.get("Σύνολο"): lines.append(f"Σύνολο: {fields['Σύνολο']}")
        if fields.get("Κατάσταση"): lines.append(f"Κατάσταση: {fields['Κατάσταση']}")

        mk = fields.get("MARK")
        if mk and mk in self._comments:
            lines.append(f"Σχόλιο παραστατικού: {self._comments[mk]}")

        afm = fields.get("AFM")
        if afm and afm in self._company_comments:
            lines.append(f"Σχόλιο εταιρείας: {self._company_comments[afm]}")

        msg = "\n".join(lines)

        self.clipboard_clear()
        self.clipboard_append(msg)
        self.status.configure(text="Αντιγράφηκε μήνυμα για Support.")

    def _find_item_by_mark(self, mark: str):
        """
        Επιστρέφει (afm, name, item_dict) για το δοθέν MARK,
        ψάχνοντας μέσα στο self._last_json.
        """
        if not isinstance(self._last_json, dict):
            return None
        for afm, info in self._last_json.items():
            if not isinstance(info, dict):
                continue
            name = info.get("name")
            items = info.get("items") or []
            for it in items:
                mk = get_mark_safe(it)
                if mk is not None and str(mk) == str(mark):
                    return afm, name, it
        return None

    def show_json_for_selection(self):
        """Εμφανίζει popup με full JSON του επιλεγμένου εγγράφου (από MARK)."""
        sel = self.listbox.curselection()
        if not sel:
            return

        text = self.listbox.get(sel[0])
        match = re.search(r"MARK:([A-Za-z0-9\-]+)", text)
        if not match:
            messagebox.showinfo(
                "Προβολή JSON",
                "Δεν βρέθηκε MARK σε αυτή τη γραμμή.",
            )
            return

        mark_value = match.group(1)
        found = self._find_item_by_mark(mark_value)
        if not found:
            messagebox.showinfo(
                "Προβολή JSON",
                f"Δεν βρέθηκε JSON για MARK {mark_value}.",
            )
            return

        afm, name, item = found
        pretty = json.dumps(item, ensure_ascii=False, indent=2)

        win = ctk.CTkToplevel(self)
        title_extra = f" | {name}" if name else ""
        win.title(f"JSON για MARK {mark_value} (AFM: {afm}{title_extra})")
        win.geometry("780x580")
        win.grab_set()
        win.focus_set()

        # Text widget για εμφάνιση JSON
        txt = tk.Text(
            win,
            wrap="none",
            bg="#020617",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            font=("Cascadia Mono", 10),
        )
        txt.pack(fill="both", expand=True, padx=8, pady=8)

        txt.insert("1.0", pretty)
        txt.configure(state="disabled")

        # Scrollbars
        ysb = tk.Scrollbar(win, orient="vertical", command=txt.yview)
        ysb.pack(side="right", fill="y")
        txt.configure(yscrollcommand=ysb.set)

        xsb = tk.Scrollbar(win, orient="horizontal", command=txt.xview)
        xsb.pack(side="bottom", fill="x")
        txt.configure(xscrollcommand=xsb.set)

        # Κουμπιά κάτω (αντιγραφή / κλείσιμο)
        btn_frame = ctk.CTkFrame(win)
        btn_frame.pack(fill="x", padx=8, pady=(0, 8))

        def copy_all_json():
            """Αντιγραφή ολόκληρου του JSON στο clipboard."""
            self.clipboard_clear()
            self.clipboard_append(pretty)
            self.status.configure(text=f"Αντιγράφηκε JSON για MARK {mark_value}.")

        copy_btn = ctk.CTkButton(
            btn_frame,
            text="Αντιγραφή JSON",
            width=150,
            command=copy_all_json,
        )
        copy_btn.pack(side="right", padx=4, pady=4)

        close_btn = ctk.CTkButton(
            btn_frame,
            text="Κλείσιμο",
            width=120,
            fg_color="#6b7280",
            hover_color="#4b5563",
            command=win.destroy,
        )
        close_btn.pack(side="right", padx=4, pady=4)

        win.bind("<Escape>", lambda e: win.destroy())

    def copy_afm_from_selection(self):
        """Αντιγράφει το ΑΦΜ από την επιλεγμένη γραμμή (header ή λεπτομέρεια)."""
        sel = self.listbox.curselection()
        if not sel:
            return

        text = self.listbox.get(sel[0])

        # 1) Προσπαθούμε πρώτα από το tag [AFM:...]
        m = re.search(r"\[AFM:([A-Za-z0-9]+)", text)
        if not m:
            # 2) Έπειτα από πεδίο ΑΦΜ:xxxx
            m = re.search(r"ΑΦΜ:([A-Za-z0-9]+)", text)
        if not m:
            # 3) Header τύπου "===== ΑΦΜ: ELxxxxxxxxx ..."
            m = re.search(r"ΑΦΜ:\s*([A-Za-z0-9]+)", text)

        if not m:
            self.status.configure(text="Δεν βρέθηκε ΑΦΜ σε αυτή τη γραμμή.")
            return

        afm_val = m.group(1)
        self.clipboard_clear()
        self.clipboard_append(afm_val)
        self.status.configure(text=f"Αντιγράφηκε ΑΦΜ: {afm_val}")

    def toggle_pin_for_selection(self):
        """
        Κάνει Pin/Unpin το MARK της επιλεγμένης γραμμής.
        Αν δεν βρεθεί MARK, δεν κάνει τίποτα.
        """
        sel = self.listbox.curselection()
        if not sel:
            return

        text = self.listbox.get(sel[0])
        match = re.search(r"MARK:([A-Za-z0-9\-]+)", text)
        if not match:
            self.status.configure(text="Δεν βρέθηκε MARK σε αυτή τη γραμμή για pin/unpin.")
            return

        mark_value = match.group(1)
        if mark_value in self._pinned_marks:
            # Unpin
            self._pinned_marks.remove(mark_value)
            save_pins(self._pinned_marks)
            self.status.configure(text=f"Unpinned MARK: {mark_value}")
        else:
            # Pin
            self._pinned_marks.add(mark_value)
            save_pins(self._pinned_marks)
            self.status.configure(text=f"Pinned MARK: {mark_value}")

        # Αν έχουμε ήδη αποτελέσματα, κάνε refresh για να φανεί το 📌
        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())

    # --------- Close Docs / MARKs / Issuer ---------
    def _now_iso_gr(self) -> str:
        """Τρέχουσα ημερομηνία/ώρα Europe/Athens σε μορφή YYYY-MM-DDTHH:MM:SS."""
        dt = datetime.now(GR_TZ) if GR_TZ else datetime.now()
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    def _collect_marks_from_last(self) -> List[int]:
        """Συλλογή μοναδικών MARK (ακέραιοι) από το _last_json."""
        marks: List[int] = []
        if not isinstance(self._last_json, dict):
            return marks
        seen: set = set()
        for _, info in self._last_json.items():
            items = (info or {}).get("items", [])
            for it in items:
                mk = get_mark_safe(it)
                if not mk:
                    continue
                try:
                    imk = int(str(mk).strip())
                except Exception:
                    continue
                if imk not in seen:
                    seen.add(imk)
                    marks.append(imk)
        return marks

    def _build_close_payload(
        self, number_val: int, internal_val: int, marks: List[int]
    ) -> dict:
        """
        Δημιουργία payload για ειδικό ακυρωτικό:
        ενημερώνει DateIssued, DispatchDate, Number, InternalDocumentId, MultipleConnectedMarks.
        """
        payload = deepcopy(CLOSE_DOC_BASE)
        now_iso = self._now_iso_gr()
        payload["DateIssued"] = now_iso
        payload["DistributionDetails"]["DispatchDate"] = now_iso
        payload["Number"] = number_val
        payload["DistributionDetails"]["InternalDocumentId"] = f"AMVtest-13-{internal_val}"
        payload["MultipleConnectedMarks"] = marks

        br = payload["Issuer"].get("BranchCode")
        try:
            if isinstance(br, str) and br.isdigit():
                payload["Issuer"]["BranchCode"] = int(br)
        except Exception:
            pass

        return payload

    def _apply_issuer_values(self, payload: dict, issuer: dict):
        """Γέμισμα των Issuer πεδίων από user input."""
        iss = payload.get("Issuer", {})
        addr = iss.get("Address", {})

        iss["RegisteredName"] = issuer.get("RegisteredName", "").strip()
        iss["BrandName"] = issuer.get("BrandName", "").strip()

        afm = issuer.get("CompanyAFM", "").strip()
        if afm.upper().startswith("EL"):
            afm = afm[2:]
        iss["Vat"] = f"EL{afm}"

        iss["TaxOffice"] = issuer.get("CompanyDoy", "").strip()

        addr["CountryCode"] = "GR"
        addr["City"] = issuer.get("City", "").strip()
        addr["Street"] = issuer.get("Street", "").strip()
        addr["Number"] = issuer.get("Number", "").strip()
        addr["Postal"] = issuer.get("Postal", "").strip()
        iss["Address"] = addr

        br = issuer.get("Branch", "").strip()
        iss["Branch"] = br
        try:
            iss["BranchCode"] = int(br)
        except Exception:
            iss["BranchCode"] = br

        payload["Issuer"] = iss

    def _prompt_issuer_data(self) -> Optional[dict]:
        """Modal φόρμα για στοιχεία εκδότη (Issuer) με βασικούς ελέγχους."""
        win = ctk.CTkToplevel(self)
        win.title("Στοιχεία Εκδότη (Issuer)")
        win.geometry("520x430")
        win.grab_set()
        win.focus_set()

        fields = [
            ("RegisteredName", "Επωνυμία (RegisteredName)"),
            ("BrandName", "Διακριτικός Τίτλος (BrandName)"),
            ("CompanyAFM", "ΑΦΜ (CompanyAFM, μόνο ψηφία)"),
            ("CompanyDoy", "ΔΟΥ (CompanyDoy)"),
            ("City", "Πόλη (City)"),
            ("Street", "Οδός (Street)"),
            ("Number", "Αριθμός (Number)"),
            ("Postal", "Τ.Κ. (Postal)"),
            ("Branch", "Υποκ/μα (Branch/BranchCode)"),
        ]

        inputs: Dict[str, tk.StringVar] = {}

        frm = ctk.CTkFrame(win, corner_radius=12)
        frm.pack(fill="both", expand=True, padx=14, pady=14)

        for i, (key, label) in enumerate(fields):
            frm.grid_rowconfigure(i, weight=0)
            lbl = ctk.CTkLabel(frm, text=label, anchor="w")
            lbl.grid(row=i, column=0, padx=(8, 8), pady=(6, 0), sticky="w")
            var = tk.StringVar()
            ent = ctk.CTkEntry(frm, textvariable=var, width=360)
            ent.grid(row=i, column=1, padx=(0, 8), pady=(6, 0), sticky="ew")
            inputs[key] = var

        btns = ctk.CTkFrame(frm)
        btns.grid(row=len(fields), column=0, columnspan=2, sticky="ew", pady=(14, 0))
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=0)
        btns.grid_columnconfigure(2, weight=0)

        result: Dict[str, str] = {}
        cancelled = {"value": True}

        def on_ok():
            """Έλεγχος πεδίων + επιστροφή αποτελέσματος."""
            afm = inputs["CompanyAFM"].get().strip()
            if afm.upper().startswith("EL"):
                afm = afm[2:]
            if afm and not afm.isdigit():
                messagebox.showerror(
                    "Σφάλμα", "Το ΑΦΜ πρέπει να περιέχει μόνο ψηφία (ή EL+ψηφία)."
                )
                return

            postal = inputs["Postal"].get().strip()
            if postal and not postal.isdigit():
                messagebox.showerror(
                    "Σφάλμα", "Ο Ταχυδρομικός Κώδικας πρέπει να είναι μόνο ψηφία."
                )
                return

            for k in inputs:
                result[k] = inputs[k].get().strip()
            cancelled["value"] = False
            win.destroy()

        def on_cancel():
            """Ακύρωση – δεν επιστρέφεται issuer dict."""
            cancelled["value"] = True
            win.destroy()

        ok_btn = ctk.CTkButton(btns, text="OK (Enter)", command=on_ok)
        ok_btn.grid(row=0, column=1, padx=6, pady=6, sticky="e")

        cancel_btn = ctk.CTkButton(
            btns,
            text="Άκυρο (Esc)",
            fg_color="#6b7280",
            hover_color="#4b5563",
            command=on_cancel,
        )
        cancel_btn.grid(row=0, column=2, padx=(0, 6), pady=6, sticky="e")

        win.bind("<Return>", lambda e: on_ok())
        win.bind("<Escape>", lambda e: on_cancel())

        # Focus στο πρώτο input (RegisteredName)
        win.after(100, lambda: frm.winfo_children()[1].focus_set())

        self.wait_window(win)
        return None if cancelled["value"] else result

    def _prompt_comment(self, title: str, prompt: str, initial: str = "") -> Optional[str]:
        """Εμφανίζει μικρό παράθυρο για εισαγωγή/επεξεργασία σχολίου."""
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("520x180")
        win.grab_set()
        win.focus_set()

        frm = ctk.CTkFrame(win, corner_radius=12)
        frm.pack(fill="both", expand=True, padx=14, pady=14)

        lbl = ctk.CTkLabel(frm, text=prompt, anchor="w", justify="left")
        lbl.grid(row=0, column=0, columnspan=2, padx=8, pady=(6, 4), sticky="w")

        var = tk.StringVar(value=initial)
        ent = ctk.CTkEntry(frm, textvariable=var, width=440)
        ent.grid(row=1, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="ew")

        btns = ctk.CTkFrame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=0)
        btns.grid_columnconfigure(2, weight=0)

        result: Dict[str, Any] = {"value": None}

        def on_ok():
            """ΟΚ -> επιστρέφει το σχόλιο (ή κενό string)."""
            result["value"] = var.get().strip()
            win.destroy()

        def on_cancel():
            """Άκυρο -> None."""
            result["value"] = None
            win.destroy()

        ok_btn = ctk.CTkButton(btns, text="OK (Enter)", command=on_ok)
        ok_btn.grid(row=0, column=1, padx=6, pady=6, sticky="e")

        cancel_btn = ctk.CTkButton(
            btns,
            text="Άκυρο (Esc)",
            fg_color="#6b7280",
            hover_color="#4b5563",
            command=on_cancel,
        )
        cancel_btn.grid(row=0, column=2, padx=(0, 6), pady=6, sticky="e")

        win.bind("<Return>", lambda e: on_ok())
        win.bind("<Escape>", lambda e: on_cancel())

        win.after(100, lambda: ent.focus_set())
        self.wait_window(win)
        return result["value"]

    def on_close_docs(self):
        """Ρουτίνα για 'Ακύρωση Δελτίων' με δημιουργία JSON και αποθήκευση."""
        if self._last_json is None:
            messagebox.showinfo(
                "Κλείσιμο Δελτίων",
                "Δεν υπάρχουν δεδομένα. Εκτέλεσε πρώτα 'Ανάκτηση'.",
            )
            return

        try:
            number_rand = self._ask_number("Κλείσιμο Δελτίων", "Τιμή για το πεδίο Number:")
            if number_rand is None:
                return
        except Exception as e:
            messagebox.showerror("Σφάλμα", f"{e}")
            return

        try:
            internal_rand = self._ask_number(
                "Κλείσιμο Δελτίων",
                "Τιμή για InternalDocumentId (AMVtest-13-{random}):",
            )
            if internal_rand is None:
                return
        except Exception as e:
            messagebox.showerror("Σφάλμα", f"{e}")
            return

        marks = self._collect_marks_from_last()
        if not marks:
            messagebox.showinfo(
                "Κλείσιμο Δελτίων",
                "Δεν βρέθηκαν MARKs στην τελευταία ανάκτηση.",
            )
            return

        try:
            payload = self._build_close_payload(number_rand, internal_rand, marks)
            issuer_values = self._prompt_issuer_data()
            if issuer_values is None:
                return
            self._apply_issuer_values(payload, issuer_values)

            # CALL API
            response = self.api.clearance(payload)

            print(f"HTTP {response.status_code} {response.reason}")
            print(response.text)

            LOGGER.info("HTTP %s %s", response.status_code, response.reason)
            LOGGER.info("Response: %s", response.text)

            path = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON", "*.json"), ("All files", "*.*")],
                initialfile="close_delivery_orders.json",
            )
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            LOGGER.info("Αποθήκευση Close-Docs JSON: %s", path)
            messagebox.showinfo("Κλείσιμο Δελτίων", f"Αποθηκεύτηκε: {path}")
            self.status.configure(
                text=f"Κλείσιμο Δελτίων: Αρ. Marks: {len(marks)}"
            )
        except Exception as e:
            LOGGER.exception("Αποτυχία δημιουργίας/αποθήκευσης JSON: %s", e)
            messagebox.showerror("Σφάλμα", str(e))

    def _ask_number(self, title: str, prompt: str):
        """
        Εισαγωγή αριθμού για Number / InternalDocumentId:
        - ακέραιος
        - 'r' για τυχαίο
        - 'min-max' για τυχαίο μέσα σε εύρος
        """
        dlg = ctk.CTkInputDialog(
            text=(
                f"{prompt}\n"
                f"- Δώσε ακέραιο (π.χ. 123456789)\n"
                f"- ή 'r' για τυχαίο\n"
                f"- ή εύρος 'min-max' (π.χ. 1-76573857)"
            ),
            title=title,
        )
        s = dlg.get_input()
        if s is None:
            return None

        s = s.strip()
        MAXV = 65535

        if s.lower() == "r":
            return random.randint(1, MAXV)

        m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", s)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            a = max(1, a)
            b = min(MAXV, b)
            if a > b:
                raise ValueError("Άκυρο εύρος μετά τα όρια.")
            return random.randint(a, b)

        if s.isdigit():
            val = int(s)
            if 1 <= val <= MAXV:
                return val

        raise ValueError("Μη έγκυρη τιμή. Δώσε ακέραιο, 'r' ή εύρος 'min-max'.")

    # --------- ΝΕΑ Ρουτίνα: Κλήση Clearance API ---------
    def on_clearance(self):
        """
        Εκτελεί το GET στο /automationsapi/fnb/clearance
        για κάθε AFM που προκύπτει από το GUI / AFM αρχείο.
        """
        base_url = self.baseurl.get().strip()
        dfrom = self.dfrom.get().strip()
        dto = self.dto.get().strip()
        default_key = (self.apikey.get() or "").strip() or None
        vat_input = (self.vat.get() or "").strip()

        # Έλεγχος ημερομηνιών
        try:
            _df = DateUtils.parse(dfrom) if dfrom else None
            _dt = DateUtils.parse(dto) if _df and dto else None
            if _df and _dt and _dt < _df:
                raise ValueError("Η dateTo είναι πριν από την dateFrom.")
        except Exception as e:
            messagebox.showerror("Σφάλμα Ημερομηνιών", str(e))
            return

        triplets = self._resolve_afm_triplets(vat_input, default_key)
        if not triplets:
            messagebox.showinfo("Κλείσιμο Δελτίων", "Δεν βρέθηκαν ΑΦΜ για clearance.")
            return

        # Επιβεβαίωση πριν από πραγματική κλήση (dryRun=False)
        if not messagebox.askyesno(
            "Κλείσιμο Δελτίων",
            f"Θα εκτελεστεί IMPACT FnB clearance (dryRun=False)\n"
            f"για {len(triplets)} ΑΦΜ, από {dfrom} έως {dto}.\n\n"
            f"Συνέχεια;",
        ):
            return

        self.status.configure(text="Εκτέλεση clearance...")
        self.update_idletasks()

        all_results: Dict[str, Any] = {}
        errors: List[Tuple[str, str]] = []

        for afm, key, name in triplets:
            try:
                cfg = ApiConfig(base_url=base_url, api_key=(key or default_key))
                svc = FnBService(ApiClient(cfg))
                payload, http_log = svc.run_clearance_with_http_log(afm, dfrom, dto, dry_run=False)
                all_results[afm] = {
                    "name": name,
                    "result": payload,
                    "http_log": http_log,
                }
            except Exception as e:
                LOGGER.exception("Σφάλμα clearance για %s: %s", afm, e)
                errors.append((afm, str(e)))

        self._last_clearance = all_results

        ok_count = len(all_results)
        err_count = len(errors)
        msg = f"Clearance ολοκληρώθηκε για {ok_count} ΑΦΜ."
        if err_count:
            msg += f" Υπήρξαν σφάλματα σε {err_count} ΑΦΜ (δες log)."

        messagebox.showinfo("Κλείσιμο Δελτίων", msg)
        self.status.configure(text=msg)
        # ----- UI Viewer με HTTP result + chunk logs -----

        lines: List[str] = []
        for afm, data in all_results.items():
            name = data.get("name") or ""
            title_name = f" ({name})" if name else ""
            lines.append(f"=== {afm}{title_name} ===")

            for h in (data.get("http_log") or []):
                lines.append(f"HTTP {h.get('httpStatus')} {h.get('httpReason')}")
                pretty = ""
                try:
                    pretty = json.dumps(json.loads(h.get("truncated") or "{}"), indent=2, ensure_ascii=False)
                except Exception:
                    pretty = h.get("truncated")

                lines.append(
                    f"Clearance result chunk {h.get('fromDate')} → {h.get('toDate')} for {h.get('issuerTin')}:"
                )
                lines.append(pretty)
                lines.append("")

        viewer_title = f"Κλείσιμο Δελτίων • OK:{len(all_results)} • ERR:{len(errors)}"
        self._show_text_viewer(viewer_title, "\n".join(lines))

    def on_clearance_preview(self):
        """Dry-run clearance (dryRun=True) και προβολή αποτελεσμάτων σε popup."""
        base_url = self.baseurl.get().strip()
        dfrom = self.dfrom.get().strip()
        dto = self.dto.get().strip()
        default_key = (self.apikey.get() or "").strip() or None
        vat_input = (self.vat.get() or "").strip()

        # Έλεγχος ημερομηνιών
        try:
            _df = DateUtils.parse(dfrom) if dfrom else None
            _dt = DateUtils.parse(dto) if _df and dto else None
            if _df and _dt and _dt < _df:
                raise ValueError("Η dateTo είναι πριν από την dateFrom.")
        except Exception as e:
            messagebox.showerror("Σφάλμα Ημερομηνιών", str(e))
            return

        triplets = self._resolve_afm_triplets(vat_input, default_key)
        if not triplets:
            messagebox.showinfo("Preview Clearance", "Δεν βρέθηκαν ΑΦΜ για clearance preview.")
            return

        self.status.configure(text="Preview clearance (dryRun=True)...")
        self.update_idletasks()

        t0 = time.perf_counter()
        preview_all: Dict[str, Any] = {}
        errors: List[Tuple[str, str]] = []

        for afm, key, name in triplets:
            try:
                cfg = ApiConfig(base_url=base_url, api_key=(key or default_key))
                svc = FnBService(ApiClient(cfg))
                payload = svc.run_clearance(afm, dfrom, dto, dry_run=True)
                preview_all[afm] = {"name": name, "result": payload}
            except Exception as e:
                LOGGER.exception("Σφάλμα preview clearance για %s: %s", afm, e)
                errors.append((afm, str(e)))

        dt = time.perf_counter() - t0
        self._last_clearance = preview_all  # κρατάμε το preview σαν “τελευταίο”

        # Popup viewer
        win = ctk.CTkToplevel(self)
        win.title(f"Preview Clearance (dryRun=True) • {dt:.2f}s")
        win.geometry("900x620")
        win.grab_set()
        win.focus_set()

        txt = tk.Text(
            win,
            wrap="none",
            bg="#0f172a",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief="flat",
            font=("Cascadia Mono", 10),
        )
        txt.pack(fill="both", expand=True, padx=10, pady=10)

        out = {
            "meta": {"count": len(preview_all), "errors": len(errors), "duration_s": round(dt, 2)},
            "preview": preview_all,
            "errors": [{"afm": a, "error": err} for a, err in errors],
        }
        txt.insert("1.0", json.dumps(out, ensure_ascii=False, indent=2))
        txt.configure(state="disabled")

        self.status.configure(text=f"Preview ολοκληρώθηκε σε {dt:.2f}s • OK:{len(preview_all)} • ERR:{len(errors)}")

    def _show_text_viewer(self, title: str, content: str) -> None:
        """Popup viewer με scroll + copy, για να δείχνουμε αποτελέσματα στο UI."""
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("1000x680")
        win.grab_set()
        win.focus_set()

        txt = tk.Text(
            win,
            wrap="none",
            bg="#0f172a",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief="flat",
            font=("Cascadia Mono", 10),
        )
        txt.pack(fill="both", expand=True, padx=10, pady=(10, 6))

        # Scrollbars
        ysb = tk.Scrollbar(win, orient="vertical", command=txt.yview)
        ysb.pack(side="right", fill="y")
        txt.configure(yscrollcommand=ysb.set)

        xsb = tk.Scrollbar(win, orient="horizontal", command=txt.xview)
        xsb.pack(side="bottom", fill="x")
        txt.configure(xscrollcommand=xsb.set)

        txt.insert("1.0", content)
        txt.configure(state="disabled")

        btn_frame = ctk.CTkFrame(win)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        def _copy_all():
            """Αντιγραφή όλου του κειμένου στο clipboard."""
            self.clipboard_clear()
            self.clipboard_append(content)
            self.status.configure(text="Αντιγράφηκε το αποτέλεσμα στο clipboard.")

        ctk.CTkButton(btn_frame, text="Αντιγραφή", width=140, command=_copy_all).pack(
            side="right", padx=6, pady=6
        )
        ctk.CTkButton(btn_frame, text="Κλείσιμο", width=120, command=win.destroy).pack(
            side="right", padx=6, pady=6
        )
    def _apply_saved_layout(self):
        """Εφαρμογή αποθηκευμένου layout (γεωμετρία + UI state)."""
        layout = load_layout()
        if not isinstance(layout, dict):
            return

        # Geometry
        geom = layout.get("geometry")
        if isinstance(geom, str) and geom:
            try:
                self.geometry(geom)
            except Exception:
                LOGGER.warning("Μη έγκυρη geometry στο layout: %s", geom)

        # UI states
        gm = layout.get("group_mode")
        if isinstance(gm, str):
            self.group_mode_var.set(gm)

        sec = layout.get("section")
        if isinstance(sec, str):
            self.section_var.set(sec)

        sc = layout.get("sidebar_collapsed")
        if isinstance(sc, bool):
            self.sidebar_collapsed_var.set(sc)

        sop = layout.get("show_only_pinned")
        if isinstance(sop, bool):
            self.show_only_pinned_var.set(sop)

        soawr = layout.get("show_only_afm_with_results")
        if isinstance(soawr, bool):
            self.show_only_afm_with_results_var.set(soawr)
            # Sync και το UI του switch (για να μην μείνει “οπτικά” λάθος)
            if hasattr(self, "only_results_switch"):
                if soawr:
                    self.only_results_switch.select()
                else:
                    self.only_results_switch.deselect()

        # Search query (αν υπάρχει)
        last_q = layout.get("search_query")
        if isinstance(last_q, str):
            self.search_var.set(last_q)

        # Header state (αν υπάρχει)
        baseurl = layout.get("baseurl")
        if isinstance(baseurl, str) and baseurl:
            self.baseurl.set(baseurl)

        vat = layout.get("vat")
        if isinstance(vat, str) and vat:
            self.vat.set(vat)

        apikey = layout.get("apikey")
        if isinstance(apikey, str):
            self.apikey.set(apikey)

        dfrom = layout.get("dfrom")
        if isinstance(dfrom, str) and dfrom:
            self.dfrom.set(dfrom)

        dto = layout.get("dto")
        if isinstance(dto, str) and dto:
            self.dto.set(dto)

        aa = layout.get("aade_auto")
        if isinstance(aa, bool):
            if aa:
                self.aade_auto_switch.select()
            else:
                self.aade_auto_switch.deselect()
            self._aade_auto_enabled = aa

    def on_closing(self):
        """Αποθήκευση layout + UI state πριν κλείσει η εφαρμογή."""
        layout: Dict[str, Any] = {
            "geometry": self.geometry(),

            # UI state
            "group_mode": self.group_mode_var.get(),
            "section": self.section_var.get(),
            "sidebar_collapsed": bool(self.sidebar_collapsed_var.get()),
            "show_only_pinned": bool(self.show_only_pinned_var.get()),
            "show_only_afm_with_results": bool(self.show_only_afm_with_results_var.get()),
            "aade_auto": bool(self.aade_auto_switch.get()),

            # Search
            "search_query": self.search_var.get(),

            # Header fields
            "baseurl": self.baseurl.get(),
            "vat": self.vat.get(),
            "apikey": self.apikey.get(),
            "dfrom": self.dfrom.get(),
            "dto": self.dto.get(),
        }
        save_layout(layout)
        self.destroy()

    # --------- AADE Status ---------
    def _aade_status_url(self) -> str:
        """Επιστρέφει το URL για MyData status, με βάση το base URL."""
        base_url = (self.baseurl.get() or "").strip().rstrip("/")
        return f"{base_url}/MyData/status"

    def _update_aade_ui(
        self, status: str, ms: Optional[int], code: Optional[int], error_text: Optional[str]
    ):
        """Ενημέρωση AADE status indicator."""
        if status == "up":
            txt, color = "AADE: Online", "#22C55E"
        elif status == "degraded":
            txt, color = "AADE: Προβλήματα", "#F59E0B"
        elif status == "down":
            txt, color = "AADE: Offline", "#EF4444"
        else:
            txt, color = "AADE: Άγνωστο", "#9CA3AF"

        self.aade_light.configure(text="●", text_color=color)
        suffix = f"{ms} ms" if ms is not None else "— ms"
        code_str = f" • HTTP {code}" if code is not None else ""
        self.aade_text.configure(text=f"{txt}{code_str}")
        self.aade_rtt.configure(text=suffix)

    def on_check_aade_status(self):
        """Εκτέλεση GET στο /MyData/status με μέτρηση χρόνου απόκρισης."""
        url = self._aade_status_url()
        timeout = 5
        try:
            t0 = time.perf_counter()
            r = requests.get(url, timeout=timeout)
            dt_ms = int((time.perf_counter() - t0) * 1000)
            code = r.status_code

            if 200 <= code < 300:
                self._update_aade_ui("up", dt_ms, code, None)
            elif code >= 500:
                self._update_aade_ui("down", dt_ms, code, r.text[:120])
            else:
                self._update_aade_ui("degraded", dt_ms, code, r.text[:120])

            LOGGER.info("AADE status check: %s | %d ms | code=%s", url, dt_ms, code)
        except Exception as e:
            self._update_aade_ui("down", None, None, str(e))
            LOGGER.exception("AADE status check failed: %s", e)

    def on_toggle_aade_auto(self):
        """Toggle για auto-refresh AADE status."""
        self._aade_auto_enabled = bool(self.aade_auto_switch.get())
        if self._aade_auto_enabled:
            try:
                self.on_check_aade_status()
            except Exception as e:
                LOGGER.exception("AADE manual ping on toggle failed: %s", e)

    def _aade_auto_refresh(self):
        """Περιοδικός έλεγχος AADE status."""
        try:
            if getattr(self, "_aade_auto_enabled", False):
                self.on_check_aade_status()
        except Exception as e:
            LOGGER.exception("AADE auto-refresh failed: %s", e)
        finally:
            self.after(self._aade_auto_interval, self._aade_auto_refresh)

    # --------- Presets / Rendering / Search ---------
    def on_preset_segment(self, value: str):
        """Callback από τα presets (Σήμερα, Χτες, 7ημ, Μήνας)."""
        mapping = {
            "Σήμερα": "today",
            "Χτες": "yesterday",
            "7ημ": "last7",
            "Μήνας": "month",
        }
        kind = mapping.get(value)
        if kind:
            self._set_date_preset(kind)

    def _set_date_preset(self, kind: str):
        """Ορισμός γρήγορων presets ημερομηνιών."""
        today = date.today()

        if kind == "today":
            dfrom = today
            dto = today
        elif kind == "yesterday":
            dfrom = today - timedelta(days=1)
            dto = dfrom
        elif kind == "last7":
            dfrom = today - timedelta(days=6)
            dto = today
        elif kind == "month":
            dfrom = today.replace(day=1)
            dto = today
        else:
            return

        self.dfrom.set(dfrom.isoformat())
        self.dto.set(dto.isoformat())
        self.status.configure(
            text=f"Preset: {kind} • {self.dfrom.get()} → {self.dto.get()}"
        )

    def _render_list(self, data: Any, query: str):
        """Εμφάνιση αποτελεσμάτων με Smart Grouping, Sorting, Pinned section και σχόλια εταιρειών."""
        self.listbox.delete(0, tk.END)

        if not isinstance(data, dict):
            self.status.configure(text="Δεν υπάρχουν έγκυρα δεδομένα για εμφάνιση.")
            return

        q = (query or "").strip().lower()
        # Αν το query δεν έχει ΚΑΝΕΝΑ γράμμα/αριθμό (π.χ. '.', '---'), το αγνοούμε ώστε να μην κρύβει τα πάντα
        if q and not any(ch.isalnum() for ch in q):
            q = ""

        mode = (self.group_mode_var.get() or "AFM").upper()
        sort_mode = self.sort_mode_var.get() or "Ημ ↓"
        only_pinned = bool(self.show_only_pinned_var.get())
        only_with_results = bool(self.show_only_afm_with_results_var.get())

        # --------- 1) Flatten entries (κάθε γραμμή = (afm, name, item)) ---------
        entries: List[Tuple[str, str, Dict[str, Any]]] = []
        empty_afms: List[Tuple[str, str]] = []  # (afm, name)

        for afm, info in data.items():
            if not isinstance(info, dict):
                continue

            afm_s = str(afm)
            name = str(info.get("name") or "")
            items = info.get("items") or []

            # Αν το items δεν είναι λίστα, το θεωρούμε σαν 0 αποτελέσματα
            if not isinstance(items, list):
                items = []

            if len(items) == 0:
                empty_afms.append((afm_s, name))

            for it in items:
                if not isinstance(it, dict):
                    continue
                entries.append((afm_s, name, it))

        # --------- 2) Search filter (AFM / Name / MARK / Series / TableId / BuyerVat / Σχόλια) ---------
        def entry_matches(afm: str, name: str, item: Dict[str, Any]) -> bool:
            if not q:
                return True
            f = _flatten(item)

            mark = get_mark_safe(item) or ""
            table_id = get_table_id_safe(item) or ""
            series = f.get("series") or f.get("docSeries") or ""
            buyer = f.get("buyer.vatNumber") or f.get("buyer.afm") or f.get("counterparty.vatNumber") or ""
            mark_comment = self._comments.get(str(mark), "") if mark else ""
            company_comment = self._company_comments.get(str(afm), "")

            hay = " ".join(
                [afm, name, str(mark), str(series), str(table_id), str(buyer), mark_comment, company_comment]
            ).lower()
            return q in hay

        entries = [e for e in entries if entry_matches(*e)]

        # --------- 3) Only pinned filter (αν είναι ενεργό) ---------
        if only_pinned:
            entries = [
                (afm, name, it)
                for (afm, name, it) in entries
                if (mk := get_mark_safe(it)) is not None and str(mk) in self._pinned_marks
            ]

        # --------- Helpers για sort/group ---------
        def sort_entries(entries_to_sort: List[Tuple[str, str, Dict[str, Any]]]) -> None:
            """Ταξινομεί τις γραμμές μέσα σε κάθε group με βάση την ημερομηνία."""
            if sort_mode == "Ημ ↑":
                entries_to_sort.sort(
                    key=lambda e: (get_issue_date_safe(e[2]) or "9999-99-99", e[0], str(get_mark_safe(e[2]) or ""))
                )
                return

            # Για Ημ ↓ αλλά και για Σύνολο ↑/↓, οι γραμμές μέσα στο ΑΦΜ μένουν με νεότερα πρώτα.
            # Το Σύνολο ↑/↓ ταξινομεί τα groups βάσει πλήθους γραμμών, όχι βάσει ποσού παραστατικού.
            entries_to_sort.sort(
                key=lambda e: (get_issue_date_safe(e[2]) or "", e[0], str(get_mark_safe(e[2]) or "")),
                reverse=True,
            )

        sort_entries(entries)

        # Αν δεν έμεινε τίποτα
        if not entries:
            # Αν το switch είναι OFF και ΔΕΝ είμαστε σε only pinned, δείξε τα ΑΦΜ με 0 αποτελέσματα
            if (not only_with_results) and (not only_pinned) and empty_afms:
                group_id = "EMPTY_AFMS"
                is_collapsed = group_id in self._collapsed_groups
                symbol = "+" if is_collapsed else "-"

                self.listbox.insert(
                    tk.END,
                    f"===== [{symbol}] {group_id} | Σύνολο: {len(empty_afms)} ====="
                )

                if not is_collapsed:
                    for afm_s, name in sorted(empty_afms, key=lambda x: x[0]):
                        company_comment = self._company_comments.get(afm_s, "")
                        comment_part = f" | 🏢💬 {company_comment}" if company_comment else ""
                        nm = f" | {name}" if name else ""
                        self.listbox.insert(tk.END, f"{afm_s}{nm}{comment_part} | 0 αποτελέσματα")

                self.listbox.insert(tk.END, "")
                self.status.configure(
                    text=f"Mode: {mode} | Sort: {sort_mode} | Φίλτρο: '{q}' | Γραμμές: 0 | Empty AFMs: {len(empty_afms)}"
                )
                return

            self.status.configure(text=f"Φίλτρο: '{q}' | Καμία εγγραφή δεν ταιριάζει.")
            return

        # --------- Helpers για grouping ---------
        def group_key_for(afm: str, name: str, it: Dict[str, Any]) -> str:
            f = _flatten(it)

            if mode == "AFM":
                base = f"{afm}" + (f" | {name}" if name else "")
                company_comment = self._company_comments.get(str(afm), "")
                if company_comment:
                    comment_preview = company_comment[:57] + "..." if len(company_comment) > 60 else company_comment
                    base += f" | 🏢💬 {comment_preview}"
                return base

            if mode == "DATE":
                issued = get_issue_date_safe(it) or "UnknownDate"
                return issued

            if mode == "STATUS":
                st = f.get("status") or f.get("state") or "UnknownStatus"
                return str(st)

            if mode == "SERIES":
                ser = f.get("series") or f.get("docSeries") or "UnknownSeries"
                return str(ser)

            if mode == "TABLEID":
                return str(get_table_id_safe(it) or "UnknownTableId")

            return "AFM"

        def sort_key_for_group(k: str):
            """Κλειδί ταξινόμησης group.

            Για Sort=Σύνολο ταξινομεί με βάση το πλήθος γραμμών κάθε group.
            Στο Group=AFM αυτό σημαίνει: πόσα παραστατικά έχει το κάθε ΑΦΜ.
            """
            group_count = len(groups.get(k, []))

            if sort_mode == "Σύνολο ↓":
                return (-group_count, str(k))
            if sort_mode == "Σύνολο ↑":
                return (group_count, str(k))

            # Για DATE θέλουμε descending (νεότερα πρώτα)
            if mode == "DATE":
                # Αν δεν είναι YYYY-MM-DD, πάει κάτω
                return (0, k) if DATE_RE.match(k) else (1, k)
            return str(k)

        # --------- 4) Pinned section (πάνω-πάνω) ---------
        pinned_entries = [
            e for e in entries
            if (mk := get_mark_safe(e[2])) is not None and str(mk) in self._pinned_marks
        ]
        sort_entries(pinned_entries)

        if pinned_entries and not only_pinned:
            pinned_group_id = f"PINNED"
            pinned_collapsed = pinned_group_id in self._collapsed_groups
            symbol = "+" if pinned_collapsed else "-"

            self.listbox.insert(
                tk.END,
                f"===== [{symbol}] {pinned_group_id} | Σύνολο: {len(pinned_entries)} ====="
            )

            if not pinned_collapsed:
                for afm, name, it in pinned_entries:
                    ln = format_result_lines(
                        [it],
                        afm_label=str(afm),
                        afm_name=str(name),
                        comments=self._comments,
                        company_comments=self._company_comments,
                        pins=self._pinned_marks,
                    )[0]
                    self.listbox.insert(tk.END, ln)
            self.listbox.insert(tk.END, "")

        # --------- 5) Grouping ---------
        groups: Dict[str, List[Tuple[str, str, Dict[str, Any]]]] = {}
        for afm, name, it in entries:
            k = group_key_for(afm, name, it)
            groups.setdefault(k, []).append((afm, name, it))

        # Ταξινόμηση group keys. Τα DATE groups κρατάνε νεότερα πρώτα.
        group_keys = sorted(groups.keys(), key=sort_key_for_group, reverse=(mode == "DATE" and not sort_mode.startswith("Σύνολο")))

        total_lines = 0
        shown_groups = 0

        for gk in group_keys:
            items = groups[gk]
            sort_entries(items)
            shown_groups += 1

            group_id = f"{mode}:{gk}"
            is_collapsed = group_id in self._collapsed_groups
            symbol = "+" if is_collapsed else "-"

            self.listbox.insert(
                tk.END,
                f"===== [{symbol}] {group_id} | Σύνολο: {len(items)} ====="
            )

            if not is_collapsed:
                for afm, name, it in items:
                    ln = format_result_lines(
                        [it],
                        afm_label=str(afm),
                        afm_name=str(name),
                        comments=self._comments,
                        company_comments=self._company_comments,
                        pins=self._pinned_marks,
                    )[0]
                    self.listbox.insert(tk.END, ln)
                    total_lines += 1

            self.listbox.insert(tk.END, "")

        # --------- 6) Empty AFMs section (μόνο αν το switch είναι OFF και δεν είμαστε σε only pinned) ---------
        empty_count_shown = 0
        if (not only_with_results) and (not only_pinned) and empty_afms:
            group_id = "EMPTY_AFMS"
            is_collapsed = group_id in self._collapsed_groups
            symbol = "+" if is_collapsed else "-"

            self.listbox.insert(
                tk.END,
                f"===== [{symbol}] {group_id} | Σύνολο: {len(empty_afms)} ====="
            )

            if not is_collapsed:
                for afm_s, name in sorted(empty_afms, key=lambda x: x[0]):
                    company_comment = self._company_comments.get(afm_s, "")
                    comment_part = f" | 🏢💬 {company_comment}" if company_comment else ""
                    nm = f" | {name}" if name else ""
                    self.listbox.insert(tk.END, f"{afm_s}{nm}{comment_part} | 0 αποτελέσματα")
                empty_count_shown = len(empty_afms)

            self.listbox.insert(tk.END, "")

        self.status.configure(
            text=f"Mode: {mode} | Sort: {sort_mode} | Φίλτρο: '{q}' | Γραμμές: {total_lines} | Groups: {shown_groups} | Empty AFMs: {empty_count_shown}"
        )

    def on_search(self):
        """Εφαρμογή φίλτρου ΑΦΜ/Ονόματος."""
        if self._last_json is None:
            messagebox.showinfo(
                "Αναζήτηση", "Δεν υπάρχουν αποτελέσματα. Εκτέλεσε πρώτα 'Ανάκτηση'."
            )
            return
        self._render_list(self._last_json, self.search_var.get())

    def on_clear_search(self):
        """Καθαρισμός φίλτρου."""
        self.search_var.set("")
        if self._last_json is not None:
            self._render_list(self._last_json, "")

    def on_group_mode_changed(self, *_):
        """Αλλαγή group mode και refresh αποτελεσμάτων."""
        LOGGER.info("Group mode changed: %s", self.group_mode_var.get())
        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())


    def on_sort_mode_changed(self, *_):
        """Αλλαγή ταξινόμησης και refresh αποτελεσμάτων."""
        LOGGER.info("Sort mode changed: %s", self.sort_mode_var.get())
        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())

    def cycle_sort_mode(self):
        """Κάνει γρήγορη εναλλαγή sort mode με Ctrl+Alt+S."""
        modes = ["Ημ ↓", "Ημ ↑", "Σύνολο ↓", "Σύνολο ↑"]
        current = self.sort_mode_var.get()
        try:
            next_index = (modes.index(current) + 1) % len(modes)
        except ValueError:
            next_index = 0
        self.sort_mode_var.set(modes[next_index])
        self.on_sort_mode_changed()

    def on_only_pinned_changed(self, *_):
        """Εμφάνιση μόνο pinned και refresh αποτελεσμάτων."""
        LOGGER.info("Show only pinned changed: %s", bool(self.show_only_pinned_var.get()))
        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())

    def on_only_afm_with_results_changed(self, *_):
        """Εμφάνιση μόνο ΑΦΜ με αποτελέσματα (ή και 0) και refresh αποτελεσμάτων."""
        LOGGER.info(
            "Show only AFM with results changed: %s",
            bool(self.show_only_afm_with_results_var.get()),
        )
        if self._last_json is not None:
            self._render_list(self._last_json, self.search_var.get())

    # --------- AFM Selector με Add / Edit / Delete + Checklist save ---------
    def open_afm_selector(self):
        """Παράθυρο με λίστα AFM (checkboxes + add/edit/delete + αποθήκευση επιλογών)."""
        triplets = load_afm_key_name_triplets()

        # Αν δεν υπάρχουν εγγραφές, ΑΝΟΙΓΟΥΜΕ κανονικά το παράθυρο για να μπορείς να κάνεις Add
        if not triplets:
            triplets = []

        total = len(triplets)

        win = ctk.CTkToplevel(self)
        win.title("Επιλογή ΑΦΜ για Ανάκτηση")
        win.geometry("740x540")
        win.grab_set()
        win.focus_set()

        # Αν δεν υπάρχουν αποθηκευμένα selected_afms, η προεπιλογή είναι 'όλα'
        preselected = (
            set(self.selected_afms)
            if self.selected_afms
            else {afm for (afm, _, _) in triplets}
        )

        header_frame = ctk.CTkFrame(win, corner_radius=12)
        header_frame.pack(fill="x", padx=10, pady=(10, 0))

        self.afm_header_label = ctk.CTkLabel(
            header_frame,
            text=f"Επιλογή ΑΦΜ (επιλεγμένα: {len(preselected)} / {total})",
            anchor="w",
        )
        self.afm_header_label.pack(side="left", padx=8, pady=6)

        # Search bar για live φίλτρο ΑΦΜ/Ονόματος
        afm_search_var = tk.StringVar()

        def apply_afm_filter(*_):
            """Εφαρμογή φίλτρου στα AFM checkboxes με βάση το search."""
            q = (afm_search_var.get() or "").strip().lower()
            row_idx = 0
            for afm, key, name in triplets:
                cb = afm_widgets.get(afm)
                if cb is None:
                    continue

                # Κείμενα στα οποία θα γίνει η αναζήτηση
                texts = [str(afm).lower()]
                if key:
                    texts.append(str(key).lower())
                if name:
                    texts.append(str(name).lower())

                if not q or any(q in t for t in texts):
                    # Εμφάνιση και επανα-τοποθέτηση στη σωστή σειρά
                    cb.grid(row=row_idx, column=0, sticky="w", padx=6, pady=3)
                    row_idx += 1
                else:
                    # Απόκρυψη
                    cb.grid_remove()

            # Η κεφαλίδα δείχνει πάντα πόσα είναι επιλεγμένα, όχι πόσα φαίνονται
            update_header()

        afm_search_entry = ctk.CTkEntry(
            header_frame,
            placeholder_text="Φίλτρο ΑΦΜ ή Ονόματος",
            textvariable=afm_search_var,
            width=260,
        )
        afm_search_entry.pack(side="right", padx=8, pady=6)
        afm_search_var.trace_add("write", apply_afm_filter)
       
        sf = ctk.CTkScrollableFrame(win, corner_radius=12)
        sf.pack(fill="both", expand=True, padx=10, pady=10)

        afm_vars: Dict[str, tk.BooleanVar] = {}
        afm_widgets: Dict[str, ctk.CTkCheckBox] = {}

        def update_header():
            """Ενημέρωση header με πλήθος επιλεγμένων AFM."""
            selected_count = sum(1 for v in afm_vars.values() if v.get())
            self.afm_header_label.configure(
                text=f"Επιλογή ΑΦΜ (επιλεγμένα: {selected_count} / {total})"
            )

        def save_all_to_file():
            """Αποθήκευση όλων των triplets στο txt (auto-sync)."""
            try:
                save_afm_triplets(triplets)
            except Exception as e:
                LOGGER.exception("Αποτυχία αποθήκευσης AFM triplets: %s", e)
                messagebox.showerror(
                    "Σφάλμα", f"Αποτυχία αποθήκευσης AFM αρχείου: {e}"
                )

        def edit_afm(old_afm: str):
            """Inline edit AFM / apiKey / Όνομα με διπλό κλικ."""
            idx = None
            cur_key: Optional[str] = None
            cur_name: Optional[str] = None
            for i, (afm, key, name) in enumerate(triplets):
                if afm == old_afm:
                    idx = i
                    cur_key = key
                    cur_name = name
                    break
            if idx is None:
                messagebox.showerror("Σφάλμα", "Η εγγραφή δεν βρέθηκε.")
                return

            edit_win = ctk.CTkToplevel(win)
            edit_win.title(f"Επεξεργασία AFM: {old_afm}")
            edit_win.geometry("520x220")
            edit_win.grab_set()
            edit_win.focus_set()

            frm = ctk.CTkFrame(edit_win, corner_radius=12)
            frm.pack(fill="both", expand=True, padx=14, pady=14)

            lbl_afm = ctk.CTkLabel(frm, text="ΑΦΜ (π.χ. EL801737126):", anchor="w")
            lbl_afm.grid(row=0, column=0, padx=(8, 8), pady=(6, 0), sticky="w")
            var_afm = tk.StringVar(value=old_afm)
            ent_afm = ctk.CTkEntry(frm, textvariable=var_afm, width=260)
            ent_afm.grid(row=0, column=1, padx=(0, 8), pady=(6, 0), sticky="ew")

            lbl_key = ctk.CTkLabel(frm, text="API Key (προαιρετικό):", anchor="w")
            lbl_key.grid(row=1, column=0, padx=(8, 8), pady=(6, 0), sticky="w")
            var_key = tk.StringVar(value=cur_key or "")
            ent_key = ctk.CTkEntry(frm, textvariable=var_key, width=260)
            ent_key.grid(row=1, column=1, padx=(0, 8), pady=(6, 0), sticky="ew")

            lbl_name = ctk.CTkLabel(
                frm, text="Όνομα Πελάτη (προαιρετικό):", anchor="w"
            )
            lbl_name.grid(row=2, column=0, padx=(8, 8), pady=(6, 0), sticky="w")
            var_name = tk.StringVar(value=cur_name or "")
            ent_name = ctk.CTkEntry(frm, textvariable=var_name, width=260)
            ent_name.grid(row=2, column=1, padx=(0, 8), pady=(6, 0), sticky="ew")

            btns_inner = ctk.CTkFrame(frm)
            btns_inner.grid(
                row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0)
            )
            btns_inner.grid_columnconfigure(0, weight=1)
            btns_inner.grid_columnconfigure(1, weight=0)
            btns_inner.grid_columnconfigure(2, weight=0)

            def on_edit_ok():
                new_afm = var_afm.get().strip()
                new_key = var_key.get().strip()
                new_name = var_name.get().strip()

                if not new_afm:
                    messagebox.showerror("Σφάλμα", "Το πεδίο ΑΦΜ είναι υποχρεωτικό.")
                    return

                existing_afms = {a for (a, _, _) in triplets}
                if new_afm != old_afm and new_afm in existing_afms:
                    messagebox.showerror(
                        "Σφάλμα", "Υπάρχει ήδη εγγραφή με αυτό το ΑΦΜ."
                    )
                    return

                triplets[idx] = (new_afm, new_key or None, new_name or None)

                cb = afm_widgets.get(old_afm)
                if cb is not None:
                    label_text = new_afm
                    if new_name:
                        label_text += f" | {new_name}"
                    elif new_key:
                        label_text += " | (χωρίς όνομα)"
                    cb.configure(text=label_text)

                if new_afm != old_afm:
                    var = afm_vars.pop(old_afm, None)
                    w = afm_widgets.pop(old_afm, None)
                    if var is not None:
                        afm_vars[new_afm] = var
                    if w is not None:
                        afm_widgets[new_afm] = w

                    # Αν ήταν στα selected_afms, αντικατάστησέ το
                    if old_afm in self.selected_afms:
                        self.selected_afms = [
                            new_afm if x == old_afm else x
                            for x in self.selected_afms
                        ]

                save_all_to_file()
                save_selected_afms_list(self.selected_afms)
                update_header()
                self.status.configure(text=f"Ενημερώθηκε το ΑΦΜ: {new_afm}")
                edit_win.destroy()

            def on_edit_cancel():
                edit_win.destroy()

            btn_ok = ctk.CTkButton(
                btns_inner, text="Αποθήκευση (Enter)", command=on_edit_ok
            )
            btn_ok.grid(row=0, column=1, padx=6, pady=6, sticky="e")
            btn_cancel = ctk.CTkButton(
                btns_inner,
                text="Άκυρο (Esc)",
                fg_color="#6b7280",
                hover_color="#4b5563",
                command=on_edit_cancel,
            )
            btn_cancel.grid(row=0, column=2, padx=(0, 6), pady=6, sticky="e")

            edit_win.bind("<Return>", lambda e: on_edit_ok())
            edit_win.bind("<Escape>", lambda e: on_edit_cancel())
            edit_win.after(100, lambda: ent_afm.focus_set())

        def add_afm_row(
            row_index: int,
            afm: str,
            key: Optional[str],
            name: Optional[str],
            checked: bool,
        ):
            """Προσθήκη μίας γραμμής AFM (checkbox + inline edit)."""
            label_text = afm
            if name:
                label_text += f" | {name}"
            elif key:
                label_text += " | (χωρίς όνομα)"

            var = tk.BooleanVar(value=checked)

            def _make_trace(v: tk.BooleanVar):
                def _traced(*_):
                    update_header()

                v.trace_add("write", _traced)

            _make_trace(var)

            cb = ctk.CTkCheckBox(sf, text=label_text, variable=var)
            cb.grid(row=row_index, column=0, sticky="w", padx=6, pady=3)
            cb.bind("<Double-Button-1>", lambda e, a=afm: edit_afm(a))

            afm_vars[afm] = var
            afm_widgets[afm] = cb

        for i, (afm, key, name) in enumerate(triplets):
            add_afm_row(i, afm, key, name, checked=(afm in preselected))

        btns = ctk.CTkFrame(win)
        btns.pack(fill="x", padx=10, pady=(0, 6))
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=0)
        btns.grid_columnconfigure(2, weight=0)
        btns.grid_columnconfigure(3, weight=0)
        btns.grid_columnconfigure(4, weight=0)
        btns.grid_columnconfigure(5, weight=0)

        def select_all():
            """Επιλογή όλων."""
            for v in afm_vars.values():
                v.set(True)
            update_header()

        def select_none():
            """Καμία επιλογή."""
            for v in afm_vars.values():
                v.set(False)
            update_header()

        def delete_selected():
            """Διαγραφή επιλεγμένων AFM."""
            nonlocal triplets, total
            to_delete = [afm for afm, var in afm_vars.items() if var.get()]
            if not to_delete:
                messagebox.showinfo(
                    "Διαγραφή", "Δεν έχεις επιλέξει κανένα ΑΦΜ για διαγραφή."
                )
                return

            if not messagebox.askyesno(
                "Διαγραφή ΑΦΜ",
                f"Θέλεις σίγουρα να διαγράψεις {len(to_delete)} ΑΦΜ;",
            ):
                return

            # Διαγραφή από triplets, widgets, selected_afms
            new_triplets = []
            for afm, key, name in triplets:
                if afm in to_delete:
                    w = afm_widgets.pop(afm, None)
                    if w is not None:
                        w.destroy()
                    afm_vars.pop(afm, None)
                    if afm in self.selected_afms:
                        self.selected_afms = [x for x in self.selected_afms if x != afm]
                else:
                    new_triplets.append((afm, key, name))

            triplets = new_triplets
            total = len(triplets)
            save_all_to_file()
            save_selected_afms_list(self.selected_afms)
            update_header()
            self.status.configure(text=f"Διαγράφηκαν {len(to_delete)} ΑΦΜ.")

        def add_new_afm():
            """Προσθήκη νέου AFM / API Key / Ονόματος."""
            nonlocal total, triplets

            add_win = ctk.CTkToplevel(win)
            add_win.title("Προσθήκη νέου ΑΦΜ")
            add_win.geometry("520x220")
            add_win.grab_set()
            add_win.focus_set()

            frm = ctk.CTkFrame(add_win, corner_radius=12)
            frm.pack(fill="both", expand=True, padx=14, pady=14)

            lbl_afm = ctk.CTkLabel(frm, text="ΑΦΜ (π.χ. EL801737126):", anchor="w")
            lbl_afm.grid(row=0, column=0, padx=(8, 8), pady=(6, 0), sticky="w")
            var_afm = tk.StringVar()
            ent_afm = ctk.CTkEntry(frm, textvariable=var_afm, width=260)
            ent_afm.grid(row=0, column=1, padx=(0, 8), pady=(6, 0), sticky="ew")

            lbl_key = ctk.CTkLabel(frm, text="API Key (προαιρετικό):", anchor="w")
            lbl_key.grid(row=1, column=0, padx=(8, 8), pady=(6, 0), sticky="w")
            var_key = tk.StringVar()
            ent_key = ctk.CTkEntry(frm, textvariable=var_key, width=260)
            ent_key.grid(row=1, column=1, padx=(0, 8), pady=(6, 0), sticky="ew")

            lbl_name = ctk.CTkLabel(
                frm, text="Όνομα Πελάτη (προαιρετικό):", anchor="w"
            )
            lbl_name.grid(row=2, column=0, padx=(8, 8), pady=(6, 0), sticky="w")
            var_name = tk.StringVar()
            ent_name = ctk.CTkEntry(frm, textvariable=var_name, width=260)
            ent_name.grid(row=2, column=1, padx=(0, 8), pady=(6, 0), sticky="ew")

            btns_inner = ctk.CTkFrame(frm)
            btns_inner.grid(
                row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0)
            )
            btns_inner.grid_columnconfigure(0, weight=1)
            btns_inner.grid_columnconfigure(1, weight=0)
            btns_inner.grid_columnconfigure(2, weight=0)

            def on_add_ok():
                nonlocal total, triplets
                afm_new = var_afm.get().strip()
                key_new = var_key.get().strip()
                name_new = var_name.get().strip()

                if not afm_new:
                    messagebox.showerror("Σφάλμα", "Το πεδίο ΑΦΜ είναι υποχρεωτικό.")
                    return
                if afm_new in afm_vars:
                    messagebox.showerror(
                        "Σφάλμα", "Αυτό το ΑΦΜ υπάρχει ήδη στη λίστα."
                    )
                    return

                triplets.append((afm_new, key_new or None, name_new or None))
                total = len(triplets)

                new_index = len(triplets) - 1
                add_afm_row(
                    new_index, afm_new, key_new or None, name_new or None, checked=True
                )

                # Προσθέτουμε και στη selected_afms και αποθηκεύουμε checklist
                if afm_new not in self.selected_afms:
                    self.selected_afms.append(afm_new)
                save_all_to_file()
                save_selected_afms_list(self.selected_afms)

                update_header()
                self.status.configure(text=f"Προστέθηκε νέο ΑΦΜ: {afm_new}")
                add_win.destroy()

            def on_add_cancel():
                add_win.destroy()

            btn_ok = ctk.CTkButton(btns_inner, text="Προσθήκη (Enter)", command=on_add_ok)
            btn_ok.grid(row=0, column=1, padx=6, pady=6, sticky="e")
            btn_cancel = ctk.CTkButton(
                btns_inner,
                text="Άκυρο (Esc)",
                fg_color="#6b7280",
                hover_color="#4b5563",
                command=on_add_cancel,
            )
            btn_cancel.grid(row=0, column=2, padx=(0, 6), pady=6, sticky="e")

            add_win.bind("<Return>", lambda e: on_add_ok())
            add_win.bind("<Escape>", lambda e: on_add_cancel())
            add_win.after(100, lambda: ent_afm.focus_set())

        def on_ok():
            """Αποθήκευση selected AFMs στο self.selected_afms + JSON."""
            selected = [afm for afm, var in afm_vars.items() if var.get()]
            self.selected_afms = selected
            save_selected_afms_list(self.selected_afms)

            if self.selected_afms:
                self.status.configure(
                    text=f"Επιλεγμένα ΑΦΜ για ανάκτηση: {len(self.selected_afms)}"
                )
            else:
                self.status.configure(
                    text="Καμία συγκεκριμένη επιλογή ΑΦΜ (θα χρησιμοποιηθούν όλα από το αρχείο)."
                )
            win.destroy()

        def on_cancel():
            win.destroy()

        add_btn = ctk.CTkButton(btns, text="Προσθήκη", width=120, command=add_new_afm)
        add_btn.grid(row=0, column=0, padx=6, pady=6, sticky="w")

        all_btn = ctk.CTkButton(btns, text="Επιλογή Όλων", width=120, command=select_all)
        all_btn.grid(row=0, column=1, padx=6, pady=6, sticky="w")

        none_btn = ctk.CTkButton(
            btns,
            text="Καμία",
            width=100,
            fg_color="#6b7280",
            hover_color="#4b5563",
            command=select_none,
        )
        none_btn.grid(row=0, column=2, padx=6, pady=6, sticky="w")

        del_btn = ctk.CTkButton(
            btns,
            text="Διαγραφή",
            width=110,
            fg_color="#b91c1c",
            hover_color="#7f1d1d",
            command=delete_selected,
        )
        del_btn.grid(row=0, column=3, padx=6, pady=6, sticky="w")

        ok_btn = ctk.CTkButton(btns, text="OK (Enter)", width=120, command=on_ok)
        ok_btn.grid(row=0, column=4, padx=6, pady=6, sticky="e")

        cancel_btn = ctk.CTkButton(
            btns,
            text="Άκυρο (Esc)",
            width=120,
            fg_color="#6b7280",
            hover_color="#4b5563",
            command=on_cancel,
        )
        cancel_btn.grid(row=0, column=5, padx=(0, 6), pady=6, sticky="e")

        win.bind("<Return>", lambda e: on_ok())
        win.bind("<Escape>", lambda e: on_cancel())

        update_header()


# --------- Εκκίνηση ---------
if __name__ == "__main__":
    app = FnBApp()
    app.mainloop()
