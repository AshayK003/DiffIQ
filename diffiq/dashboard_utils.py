"""Utility functions extracted from the Streamlit dashboard for testability."""


_BADGE_LABELS: dict[str, str] = {
    "ready": "Ready",
    "queued": "Queued",
    "no-pdf": "No PDF",
    "downloading": "Downloading",
}
_KNOWN_BADGE_CLASSES: set[str] = {"ready", "error", "queued", "no-pdf", "downloading"}


def status_badge_html(status: str) -> str:
    """Render a color-coded status badge span.

    Maps status strings to muted-pastel badges matching the minimalist
    colour palette: green (ready), red (error), amber (queued), gray (no-pdf),
    blue (downloading).

    Args:
        status: Filing status string (e.g. 'READY', 'ERROR_DOWNLOAD', 'QUEUED').

    Returns:
        HTML span with appropriate badge CSS class and label.
    """
    if status.startswith("ERROR_"):
        return '<span class="badge badge-error">Error</span>'
    css = status.lower().replace("_", "-")
    label = _BADGE_LABELS.get(css, status)
    css_class = css if css in _KNOWN_BADGE_CLASSES else "error"
    return f'<span class="badge badge-{css_class}">{label}</span>'
