<?php

declare(strict_types=1);

namespace App\Services;

final class InvoiceNumberService
{
    public function __construct(
        private readonly string $prefix,
    ) {}
}
