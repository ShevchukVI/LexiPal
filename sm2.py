from datetime import datetime, timedelta


def calculate_next_review(quality: int, repetitions: int, ease_factor: float, interval: int):
    if quality == 0:
        repetitions = 0
        interval = 1
    else:
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = int(round(interval * ease_factor))
        repetitions += 1

    ease_factor = ease_factor + (0.1 - (3 - quality) * (0.08 + (3 - quality) * 0.02))
    if ease_factor < 1.3:
        ease_factor = 1.3

    next_review_date = datetime.now() + timedelta(days=interval)

    return repetitions, ease_factor, interval, next_review_date.strftime('%Y-%m-%d %H:%M:%S')