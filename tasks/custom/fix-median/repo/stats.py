def mean(values):
    return sum(values) / len(values)


def median(values):
    """Return the median of a non-empty list of numbers."""
    n = len(values)
    mid = n // 2
    if n % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2
