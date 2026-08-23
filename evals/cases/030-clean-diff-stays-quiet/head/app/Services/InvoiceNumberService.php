<?php

declare(strict_types=1);

namespace App\Services;

final class InvoiceNumberService
{
    public function __construct(
        private readonly string $prefix,
    ) {}

    /**
     * Format a sequence number as a padded, prefixed invoice reference.
     */
    public function formatReference(int $sequence): string
    {
        return sprintf('%s-%06d', $this->prefix, $sequence);
    }
}
