<?php

declare(strict_types=1);

namespace App\Services;

final class EscalationPolicy
{
    /**
     * Who gets paged when an export fails.
     *
     * @var list<string>
     */
    private const ESCALATION_RECIPIENTS = [
        'ops@example.com',
        'oncall@example.com',
    ];

    /**
     * @return list<string>
     */
    public function recipients(): array
    {
        return self::ESCALATION_RECIPIENTS;
    }
}
