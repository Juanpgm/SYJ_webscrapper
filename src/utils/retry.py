from tenacity import retry, stop_after_attempt, wait_exponential


def retry_policy(max_attempts: int = 3):
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
