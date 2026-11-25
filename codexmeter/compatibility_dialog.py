"""Compatibility status UI. All rendering occurs on the Tk thread."""
import json
from .compatibility_readers import SUPPORTED_STREAM_VERSIONS
import tkinter as tk
from tkinter import ttk
from .compatibility import COMPONENTS

EXPLANATIONS = {
    "wrapper_missing": "The installed chat-status helper is missing. Enable the Desktop wrapper again to repair it.",
    "wrapper_inactive": "Desktop has no live wrapper connection. Fully quit Desktop and reopen it from Start. If this persists after an update, check for a CodexMeter update.",
    "wrapper_listener": "Desktop started with its normal connection because the wrapper could not open a private socket. Check for a CodexMeter update.",
    "wrapper_protocol": "Desktop's live-status response has changed. Check for a CodexMeter update.",
    "unsupported_version": "Codex is using a data format this version of CodexMeter does not understand.",
    "schema": "A required Codex database field is missing.",
    "structure": "Codex data no longer matches the expected structure.",
    "closed": "Codex is closed. Waiting for it to open.",
    "missing": "A required local data source was not found.",
    "locked": "Codex's database is temporarily busy.",
    "corrupt": "A local database could not be read correctly.",
    "ambiguous_account": "More than one unread-chat account was found; CodexMeter will not guess.",
    "incomplete": "Waiting for complete chat-owner and state information.",
    "no_history": "No compatible local usage history is available.",
    "authentication": "Codex needs an authenticated account for quota readings.",
    "expired": "The last source validation has expired.",
    "timeout": "The source did not respond in time.",
    "connection": "The local Codex connection is unavailable.",
    "starting": "Waiting for the first validated reading.",
    "reader_error": "The reading failed. The cause is not yet known.",
    "ok": "Current data passed the compatibility checks.",
}

def summary(snapshot):
    rows = snapshot.get("components", {})
    incompatible = [v["label"] for v in rows.values() if v.get("unresolved_incompatibility")]
    if incompatible:
        return "Codex data format needs attention: " + ", ".join(incompatible) + "."
    unavailable = [v["label"] for v in rows.values() if v.get("state") in ("unavailable", "stale")]
    if unavailable:
        return "Readings unavailable: " + ", ".join(unavailable) + "."
    if not rows or any(v.get("state") == "checking" for v in rows.values()):
        return "Checking Codex data compatibility…"
    return "Codex readings are available."

def diagnostic_report(snapshot):
    from . import __version__
    from .compatibility import safe_details, REASONS
    import re
    report = {"codexmeter": __version__, "supported_stream_versions": sorted(SUPPORTED_STREAM_VERSIONS),
              "version_provenance": "local executable metadata", "components": {}, "versions": {}}
    for key, row in snapshot.get("components", {}).items():
        if key not in COMPONENTS or not isinstance(row, dict):
            continue
        report["components"][key] = {
            "state": row.get("state") if row.get("state") in
                {"checking", "compatible", "unavailable", "stale", "incompatible"} else "unknown",
            "reason": row.get("reason") if row.get("reason") in REASONS else "reader_error",
            "details": safe_details(row.get("details")),
            "unresolved_format_details": safe_details(row.get("incompatibility_details")),
            "last_validated_utc": row.get("last_validated_utc") if type(row.get("last_validated_utc")) in (int, float) else None,
        }
    for key in ("desktop", "quota_cli", "codexmeter"):
        value = snapshot.get("versions", {}).get(key)
        report["versions"][key] = value if isinstance(value, str) and re.fullmatch(r"[0-9A-Za-z.+_-]{1,64}", value) else "unknown"
    return json.dumps(report, indent=2)

def show_compatibility(root, get_snapshot):
    from .update_dialog import show_updates
    window = tk.Toplevel(root)
    window.title("CodexMeter — Codex data status")
    window.geometry("680x510")
    frame = ttk.Frame(window, padding=18)
    frame.pack(fill="both", expand=True)
    heading = tk.StringVar()
    ttk.Label(frame, textvariable=heading, wraplength=630,
              font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 12))
    text = tk.Text(frame, wrap="word", height=16, state="disabled")
    text.pack(fill="both", expand=True)
    actions = ttk.Frame(frame)
    actions.pack(fill="x", pady=(12, 0))
    ttk.Button(actions, text="Check for updates…", command=lambda: show_updates(window)).pack(side="left")
    def copy():
        window.clipboard_clear()
        window.clipboard_append(diagnostic_report(get_snapshot()))
    ttk.Button(actions, text="Copy diagnostics", command=copy).pack(side="left", padx=8)
    ttk.Button(actions, text="Close", command=window.destroy).pack(side="right")
    def refresh():
        if not window.winfo_exists():
            return
        snapshot = get_snapshot()
        heading.set(summary(snapshot))
        lines = []
        confirmed = False
        for key, row in snapshot.get("components", {}).items():
            if key not in COMPONENTS:
                continue
            confirmed |= bool(row.get("unresolved_incompatibility"))
            lines.append(COMPONENTS[key][0] + ": " + row.get("state", "unknown"))
            if key == "stream" and row.get("reason") == "missing":
                lines.append("Desktop is missing its legacy pipe. Open the control panel and enable the Desktop wrapper for live chat counts.")
            else:
                lines.append(EXPLANATIONS.get(row.get("reason"), EXPLANATIONS["reader_error"]))
            if row.get("unresolved_incompatibility"):
                lines.append("A format incompatibility remains unresolved until fresh valid readings resume.")
            lines.append("")
        lines.append("Check for a CodexMeter update." if confirmed else
                     "Unavailable readings do not prove a format change. Working readings continue normally.")
        lines.append("Nothing is installed or restarted automatically. Diagnostics stay on this computer.")
        lines.append("\nTechnical details\n" + diagnostic_report(snapshot))
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("end", "\n".join(lines))
        text.configure(state="disabled")
        window.after(1000, refresh)
    refresh()
    window.lift()
    return window
