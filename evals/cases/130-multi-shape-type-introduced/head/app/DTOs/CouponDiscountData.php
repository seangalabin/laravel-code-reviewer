<?php

declare(strict_types=1);

namespace App\DTOs;

final readonly class CouponDiscountData
{
    /**
     * @param 'percentage'|'fixed' $kind
     * @param mixed $value int percent when kind is 'percentage'; array{amount_cents: int, currency: string} when 'fixed'
     */
    public function __construct(
        public string $kind,
        public mixed $value,
    ) {
    }
}
