<?php

declare(strict_types=1);

namespace App\Services;

final class RetryPolicy
{
    /**
     * Upstream responses worth retrying rather than failing outright.
     *
     * @var list<int>
     */
    private const RETRYABLE_STATUS_CODES = [429, 502, 503, 504];

    public function isRetryable(int $statusCode): bool
    {
        return in_array($statusCode, self::RETRYABLE_STATUS_CODES, true);
    }
}
