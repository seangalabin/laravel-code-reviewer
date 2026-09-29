<?php

declare(strict_types=1);

namespace App\Services;

use App\DTOs\CouponDiscountData;
use App\Models\Coupon;

final class CouponService
{
    public function findByCode(string $code): ?Coupon
    {
        return Coupon::query()->where('code', $code)->first();
    }

    /**
     * Returns the discount breakdown, or false when the coupon cannot be applied.
     *
     * @return array{coupon_id: int, discount: CouponDiscountData}|false
     */
    public function applyCoupon(string $code, int $subtotalCents): array|false
    {
        $coupon = $this->findByCode($code);

        if ($coupon === null || $coupon->expires_at?->isPast()) {
            return false;
        }

        $discount = $coupon->is_percentage
            ? new CouponDiscountData(kind: 'percentage', value: $coupon->percent)
            : new CouponDiscountData(kind: 'fixed', value: ['amount_cents' => $coupon->amount_cents, 'currency' => $coupon->currency]);

        return [
            'coupon_id' => $coupon->id,
            'discount' => $discount,
        ];
    }
}
