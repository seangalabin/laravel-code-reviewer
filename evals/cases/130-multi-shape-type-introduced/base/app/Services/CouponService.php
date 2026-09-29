<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\Coupon;

final class CouponService
{
    public function findByCode(string $code): ?Coupon
    {
        return Coupon::query()->where('code', $code)->first();
    }
}
