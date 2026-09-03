"""Orquestación de escaneo/caché/conversión, y deduplicación bajo demanda (Fase D-1/D-2b, §2.7.3)."""

from doc_organize.scan.scan_command import DeduplicationSummary, ScanCommand, ScanSummary
from doc_organize.scan.scan_history_store import append_scan_run, list_scan_runs

__all__ = ["DeduplicationSummary", "ScanCommand", "ScanSummary", "append_scan_run", "list_scan_runs"]
