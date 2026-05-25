"""SEC EDGAR data client. Wraps edgartools and normalises output."""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from typing import Optional
from datetime import date

import pandas as pd
from edgar import Company, set_identity


def init_edgar() -> None:
    identity = os.environ.get("EDGAR_IDENTITY")
    if not identity:
        raise RuntimeError("Set EDGAR_IDENTITY env var.")
    set_identity(identity)


@dataclass
class CompanyData:
    ticker: str
    cik: str
    name: str
    sic: str
    sic_description: str
    fiscal_year_end: str
    income_statement: pd.DataFrame
    balance_sheet: pd.DataFrame
    cash_flow: pd.DataFrame
    latest_10k_date: Optional[date] = None
    latest_10k_url: Optional[str] = None
    latest_10q_date: Optional[date] = None
    recent_filings: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _as_df(obj):
    if obj is None:
        return pd.DataFrame()
    if isinstance(obj, pd.DataFrame):
        return obj
    if hasattr(obj, "to_dataframe"):
        try:
            return obj.to_dataframe()
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def fetch_company(ticker: str, years_history: int = 5) -> CompanyData:
    init_edgar()
    co = Company(ticker)
    notes: list[str] = []

    try:
        fin = co.get_financials()
        income = _as_df(fin.income_statement())
        balance = _as_df(fin.balance_sheet())
        try:
            cash = _as_df(fin.cash_flow_statement())
        except AttributeError:
            try:
                cash = _as_df(fin.cashflow_statement())
            except AttributeError:
                cash = pd.DataFrame()
    except Exception as e:
        notes.append(f"financials_fetch_error: {e}")
        income = pd.DataFrame()
        balance = pd.DataFrame()
        cash = pd.DataFrame()

    filings = []
    latest_10k_date = None
    latest_10k_url = None
    latest_10q_date = None
    try:
        for f in co.get_filings(form="10-K").head(years_history):
            filings.append({
                "form": f.form,
                "filing_date": f.filing_date,
                "period_of_report": getattr(f, "period_of_report", None),
                "url": getattr(f, "document_url", None),
            })
        if filings:
            latest_10k_date = filings[0]["filing_date"]
            latest_10k_url = filings[0]["url"]
        for f in co.get_filings(form="10-Q").head(4):
            filings.append({
                "form": f.form,
                "filing_date": f.filing_date,
                "period_of_report": getattr(f, "period_of_report", None),
                "url": getattr(f, "document_url", None),
            })
            if not latest_10q_date:
                latest_10q_date = f.filing_date
    except Exception as e:
        notes.append(f"filings_fetch_error: {e}")

    try:
        sic = str(getattr(co, "sic", "")) or ""
        sic_desc = str(getattr(co, "sic_description", "")) or ""
        name = str(getattr(co, "name", ticker))
        fye = str(getattr(co, "fiscal_year_end", ""))
        cik = str(getattr(co, "cik", ""))
    except Exception:
        sic, sic_desc, name, fye, cik = "", "", ticker, "", ""

    return CompanyData(
        ticker=ticker.upper(), cik=cik, name=name, sic=sic, sic_description=sic_desc,
        fiscal_year_end=fye, income_statement=income, balance_sheet=balance, cash_flow=cash,
        latest_10k_date=latest_10k_date, latest_10k_url=latest_10k_url,
        latest_10q_date=latest_10q_date, recent_filings=filings, notes=notes,
    )


PERIOD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _get_period_columns(df: pd.DataFrame) -> list[str]:
    if df.empty or not hasattr(df, "columns"):
        return []
    return [c for c in df.columns if PERIOD_RE.match(str(c))]


def _find_value(df, period_col, concepts, labels, standard_concepts=None):
    if df.empty or period_col not in df.columns:
        return None

    def _filter(mask):
        if "abstract" in df.columns:
            mask = mask & (df["abstract"] != True)
        return mask

    if "standard_concept" in df.columns and standard_concepts:
        for sc in standard_concepts:
            mask = df["standard_concept"].astype(str).str.lower() == sc.lower()
            mask = _filter(mask)
            if mask.any():
                rows = df.loc[mask, period_col].dropna()
                if not rows.empty:
                    try: return float(rows.iloc[0])
                    except: pass

    if "concept" in df.columns:
        for c in concepts:
            mask = df["concept"].astype(str) == c
            mask = _filter(mask)
            if mask.any():
                rows = df.loc[mask, period_col].dropna()
                if not rows.empty:
                    try: return float(rows.iloc[0])
                    except: pass

    if "label" in df.columns:
        norm = df["label"].astype(str).str.lower().str.strip()
        for lbl in labels:
            mask = norm == lbl.lower().strip()
            mask = _filter(mask)
            if mask.any():
                rows = df.loc[mask, period_col].dropna()
                if not rows.empty:
                    try: return float(rows.iloc[0])
                    except: pass
        for lbl in labels:
            mask = df["label"].astype(str).str.contains(lbl, case=False, na=False, regex=False)
            mask = _filter(mask)
            if mask.any():
                rows = df.loc[mask, period_col].dropna()
                if not rows.empty:
                    try: return float(rows.iloc[0])
                    except: pass
    return None


LABEL_MAP_IS = {
    "revenue": {"standard_concept": ["Revenue"], "concept": ["us-gaap_Revenues", "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap_RevenueFromContractWithCustomerIncludingAssessedTax", "us-gaap_SalesRevenueNet"], "label": ["Revenues", "Revenue", "Total revenue", "Net sales", "Net revenue"]},
    "cost_of_revenue": {"concept": ["us-gaap_CostOfRevenue", "us-gaap_CostOfGoodsAndServicesSold", "us-gaap_CostOfGoodsSold", "us-gaap_CostOfServices", "us-gaap_CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"], "label": ["Cost of revenue", "Cost of revenues", "Cost of goods sold", "Cost of products sold", "Cost of products and services sold", "Cost of products and services", "Cost of sales"]},
    "gross_profit": {"standard_concept": ["Gross Profit"], "concept": ["us-gaap_GrossProfit"], "label": ["Gross profit", "Gross Profit"]},
    "sga": {"concept": ["us-gaap_SellingGeneralAndAdministrativeExpense", "us-gaap_GeneralAndAdministrativeExpense"], "label": ["Selling, general and administrative", "Selling, general and administrative expenses", "Selling, general & administrative"]},
    "operating_income": {"standard_concept": ["Operating Income"], "concept": ["us-gaap_OperatingIncomeLoss"], "label": ["Operating income", "Income from operations", "Operating profit", "Operating income (loss)"]},
    "other_income": {"concept": ["us-gaap_OtherNonoperatingIncomeExpense", "us-gaap_NonoperatingIncomeExpense"], "label": ["Other income, net"]},
    "tax": {"concept": ["us-gaap_IncomeTaxExpenseBenefit"], "label": ["Provision for income taxes", "Income tax expense"]},
    "net_income": {"standard_concept": ["Net Income"], "concept": ["us-gaap_NetIncomeLoss", "us-gaap_ProfitLoss"], "label": ["Net income", "NET INCOME"]},
    "diluted_eps": {"concept": ["us-gaap_EarningsPerShareDiluted"], "label": ["Diluted"]},
    "diluted_shares": {"concept": ["us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding"], "label": ["Diluted shares"]},
}

LABEL_MAP_BS = {
    "cash": {"concept": ["us-gaap_CashAndCashEquivalentsAtCarryingValue", "us-gaap_Cash"], "label": ["Cash and cash equivalents"]},
    "short_term_investments": {"concept": ["us-gaap_ShortTermInvestments"], "label": ["Short-term investments", "Investments"]},
    "total_assets": {"standard_concept": ["Total Assets"], "concept": ["us-gaap_Assets"], "label": ["Total assets"]},
    "total_liabilities": {"concept": ["us-gaap_Liabilities"], "label": ["Total liabilities"]},
    "total_equity": {"concept": ["us-gaap_StockholdersEquity"], "label": ["Total stockholders' equity"]},
    "debt": {"concept": ["us-gaap_LongTermDebt", "us-gaap_LongTermDebtNoncurrent"], "label": ["Long-term debt"]},
}

LABEL_MAP_CF = {
    "operating_cash_flow": {"concept": ["us-gaap_NetCashProvidedByUsedInOperatingActivities"], "label": ["Net cash provided by operating activities"]},
    "capex": {"concept": ["us-gaap_PaymentsToAcquirePropertyPlantAndEquipment"], "label": ["Capital expenditures", "Purchases of property"]},
    "depreciation": {"concept": ["us-gaap_DepreciationDepletionAndAmortization", "us-gaap_DepreciationAndAmortization"], "label": ["Depreciation and amortization", "Depreciation"]},
}


def extract_historical_metrics(cd: CompanyData) -> dict:
    metrics = {}
    inc = cd.income_statement
    bs = cd.balance_sheet
    cf = cd.cash_flow
    if inc.empty:
        return metrics
    periods = _get_period_columns(inc)
    if not periods:
        return metrics
    for period in sorted(periods):
        m = {"period": period}
        for name, ref in LABEL_MAP_IS.items():
            m[name] = _find_value(inc, period, ref.get("concept", []), ref.get("label", []), ref.get("standard_concept", []))

        # Computed fallbacks: derive gross_profit from revenue - cost_of_revenue
        # when the direct label is absent (covers conglomerates like HON that
        # report cost line items without a standalone gross profit label).
        if m.get("gross_profit") is None:
            rev = m.get("revenue")
            cor = m.get("cost_of_revenue")
            if rev is not None and cor is not None and rev > 0 and cor > 0:
                m["gross_profit"] = rev - cor

        # Derive operating_income from gross_profit - sga when both are available
        # and the direct label is absent.
        if m.get("operating_income") is None:
            gp = m.get("gross_profit")
            sga = m.get("sga")
            if gp is not None and sga is not None:
                m["operating_income"] = gp - abs(sga)

        bs_periods = _get_period_columns(bs)
        bs_p = period if period in bs_periods else (bs_periods[-1] if bs_periods else None)
        for name, ref in LABEL_MAP_BS.items():
            m[name] = _find_value(bs, bs_p, ref.get("concept", []), ref.get("label", []), ref.get("standard_concept", [])) if bs_p else None
        cf_periods = _get_period_columns(cf)
        cf_p = period if period in cf_periods else (cf_periods[-1] if cf_periods else None)
        for name, ref in LABEL_MAP_CF.items():
            m[name] = _find_value(cf, cf_p, ref.get("concept", []), ref.get("label", []), ref.get("standard_concept", [])) if cf_p else None
        metrics[period] = m
    return metrics


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AGX"
    cd = fetch_company(ticker)
    print(f"{cd.ticker} | {cd.name}")
    for period, m in extract_historical_metrics(cd).items():
        rev = m.get("revenue")
        ni = m.get("net_income")
        rev_s = f"${rev/1e6:,.0f}M" if rev else "n/a"
        ni_s = f"${ni/1e6:,.0f}M" if ni else "n/a"
        print(f"  {period}: Rev={rev_s}  NI={ni_s}")
