"""Dated desktop token reports; unavailable data must not look like today's usage."""
import datetime as dt
from .persistence import atomic_write_json

REPORT_VERSION = 1
MAX_REPORT_AGE_SEC = 300


def publish_report(path, details, now):
    atomic_write_json(path, {
        'version': REPORT_VERSION, 'observed_at': now.isoformat(),
        'first_date': (now.date()-dt.timedelta(days=6)).isoformat(),
        'last_date': now.date().isoformat(),
        'state': 'available' if details is not None else 'unavailable',
        'data': details,
    })


def report_lines(report, now=None):
    now = now or dt.datetime.now().astimezone()
    if not isinstance(report, dict) or report.get('version') != REPORT_VERSION:
        return ['Saved token report has no supported observation time. Refresh usage before relying on it.']
    try:
        observed = dt.datetime.fromisoformat(report['observed_at'])
        if observed.tzinfo is None:
            raise ValueError('Missing timezone')
        first = dt.date.fromisoformat(report['first_date'])
        last = dt.date.fromisoformat(report['last_date'])
        if last-first != dt.timedelta(days=6):
            raise ValueError('Invalid reporting window')
        age = (now-observed).total_seconds()
        stale = not 0 <= age <= MAX_REPORT_AGE_SEC or last != now.date()
        lines = [f"Observed: {observed.isoformat(timespec='seconds')}"]
        if report.get('state') != 'available':
            return lines + ['Token breakdown and cost estimates are unavailable. Refresh usage to try again.']
        if stale:
            lines.append('STALE saved report; these are not current usage figures.')
        for key, title in (('today', f'Recorded day {last}' if stale else 'Today'),
                           ('week', f'Recorded week {first} to {last}' if stale else 'Last 7 days')):
            part = report['data'][key]
            lines.append(f"{title} — recorded total {part['total_tokens']:,} tokens")
            for label, tokens, cost in zip(('Input (uncached)', 'Cached input', 'Output'), part['tokens'], part['cost_micro_usd']):
                lines.append(f"  {label:18} {tokens:>15,}   ${cost / 1e6:,.4f}")
            lines.append(f"  Unpriced tokens: {part['unpriced_tokens']:,}; breakdown unavailable: {part['unknown_tokens']:,}")
            for model, item in sorted(part['models'].items()):
                lines.append(f"  {model}: {item['tokens']:,} tokens; priced subtotal ${item['cost_usd']:,.4f}; unpriced {item['unpriced_tokens']:,}  {'; '.join(item['reasons'])}")
            lines.append('')
        return lines
    except (KeyError, ValueError, TypeError, AttributeError):
        return ['Saved token report is invalid. Refresh usage before relying on it.']
