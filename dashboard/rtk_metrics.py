"""Recent RTK output estimates, with lifetime and outlier contributions retained."""
from datetime import datetime, timedelta, timezone


def window_metrics(connection, now=None):
    now = now or datetime.now().astimezone()
    cutoffs = {'today': now.replace(hour=0, minute=0, second=0, microsecond=0),
               'seven_days': now - timedelta(days=7), 'lifetime': None}
    result = {}
    for key, cutoff in cutoffs.items():
        where = ' WHERE julianday(timestamp) >= julianday(?) AND julianday(timestamp) <= julianday(?)' if cutoff else ''
        args = (cutoff.isoformat(), now.isoformat()) if cutoff else ()
        row = connection.execute(
            'SELECT COUNT(*) AS total_commands, COALESCE(SUM(saved_tokens),0) AS total_saved, '
            'COALESCE(SUM(input_tokens),0) AS total_input, COALESCE(SUM(output_tokens),0) AS total_output, '
            'COALESCE(SUM(exec_time_ms),0) AS total_time_ms, '
            'COALESCE(SUM(CASE WHEN saved_tokens > 0 THEN 1 ELSE 0 END),0) AS optimized_commands, '
            'COALESCE(MAX(saved_tokens),0) AS largest_saved, COALESCE(MAX(input_tokens),0) AS largest_input '
            'FROM commands' + where, args).fetchone()
        value = dict(row)
        value['avg_savings_pct'] = round(100 * value['total_saved'] / value['total_input'], 1) if value['total_input'] else 0
        value['largest_saved_share_pct'] = round(100 * value['largest_saved'] / value['total_saved'], 1) if value['total_saved'] else 0
        value['largest_input_share_pct'] = round(100 * value['largest_input'] / value['total_input'], 1) if value['total_input'] else 0
        result[key] = value
    last = connection.execute('SELECT timestamp FROM commands ORDER BY julianday(timestamp) DESC LIMIT 1').fetchone()
    result['last_recorded_at'] = last['timestamp'] if last else None
    result['recent_use'] = False
    if last:
        try:
            recorded = datetime.fromisoformat(last['timestamp'].replace('Z', '+00:00'))
            if recorded.tzinfo is None:
                recorded = recorded.replace(tzinfo=timezone.utc)
            result['recent_use'] = 0 <= (now - recorded).total_seconds() <= 300
        except (TypeError, ValueError):
            pass
    result['collected_at'] = now.isoformat()
    return result
