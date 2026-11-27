"""Chart series derived from the same read-only report figures as the tables."""
import calendar

from billing.models import Payment


def report_charts(report, payments):
    period = report['period']
    if period.month:
        days = calendar.monthrange(period.year, period.month)[1]
        cash, bank = [0] * days, [0] * days
        for payment in payments:
            if payment.method == Payment.Method.TIEN_MAT:
                cash[payment.paid_date.day - 1] += int(payment.amount)
            elif payment.method == Payment.Method.CHUYEN_KHOAN:
                bank[payment.paid_date.day - 1] += int(payment.amount)
        labels = [f'{day}/{period.month}' for day in range(1, days + 1)]
    else:
        labels = [f'Tháng {row["month"]}' for row in report['months']]
        cash = [int(row['cash']) for row in report['months']]
        bank = [int(row['bank']) for row in report['months']]

    stats = report['room_stats']
    invoice_totals = [0] * len(labels)
    if not period.month:
        for row in report['issued']:
            invoice_totals[row['invoice'].month - 1] += int(row['invoice'].total_amount)
    today = report['today']
    observed = len(labels)
    if period.year == today.year:
        observed = today.day if period.month == today.month else today.month if not period.month else len(labels)
    # Future empty periods stay blank rather than suggesting a drop in collections.
    last_activity = max((index + 1 for index in range(len(labels))
                         if cash[index] or bank[index] or invoice_totals[index]), default=0)
    observed = max(observed, last_activity)
    return {
        'collections': {'labels': labels, 'cash': cash, 'bank': bank, 'invoice': invoice_totals,
                        'daily': bool(period.month), 'observed_count': observed},
        'debt': [{'label': row['label'], 'value': int(row['amount']), 'count': row['count']}
                 for row in report['aging']],
        'rooms': [{'label': label, 'value': stats[key]} for key, label in (
            ('dang_thue', 'Đang thuê'), ('trong', 'Phòng trống'), ('bao_tri', 'Đang sửa chữa'))],
    }
