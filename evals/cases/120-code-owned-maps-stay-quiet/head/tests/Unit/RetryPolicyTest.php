<?php

declare(strict_types=1);

namespace Tests\Unit;

use App\Services\RetryPolicy;
use PHPUnit\Framework\TestCase;

final class RetryPolicyTest extends TestCase
{
    public function test_it_retries_throttling_and_gateway_failures(): void
    {
        $policy = new RetryPolicy();

        self::assertTrue($policy->isRetryable(429));
        self::assertTrue($policy->isRetryable(504));
    }

    public function test_it_does_not_retry_client_errors(): void
    {
        $policy = new RetryPolicy();

        self::assertFalse($policy->isRetryable(404));
        self::assertFalse($policy->isRetryable(200));
    }
}
