from datetime import date, timedelta

# Simple SM-2 implementation for spacing (Ebbinghaus-style spacing)
# fields: ease(float), interval(int, days), repetition(int)

def sm2_update(ease: float, interval: int, repetition: int, quality: int, profile: dict = None):
    # quality: 0-5
    if quality < 3:
        repetition = 0
        interval = 1
    else:
        if repetition == 0:
            interval = 1
        elif repetition == 1:
            interval = 6
        else:
            interval = max(1, int(round(interval * ease)))
        repetition += 1
    # update ease
    ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if ease < 1.3:
        ease = 1.3

    # apply profile-based modifiers
    multiplier = 1.0
    if profile and isinstance(profile, dict):
        diff = profile.get('difficulty', 'normal')
        # easier -> longer intervals, hard -> shorter intervals
        mapping = {'easy': 1.2, 'normal': 1.0, 'hard': 0.8}
        multiplier = mapping.get(diff, 1.0)
        # if user studies very little, be conservative
        hours = profile.get('study_hours_per_day')
        try:
            if hours is not None:
                h = float(hours)
                if h < 0.5:
                    multiplier *= 0.8
                elif h > 2:
                    multiplier *= 1.05
        except Exception:
            pass

    adjusted_interval = max(1, int(round(interval * multiplier)))
    next_review = date.today() + timedelta(days=adjusted_interval)
    return ease, adjusted_interval, repetition, next_review.isoformat()

